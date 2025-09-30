# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Entrypoint to suggesting remote archives for each local archive in the package.

Implements the CLI sub-command `suggest-package-archives`, see
suggest_remote_package_archives() function. Under the hood, this function creates a
RemotePackageArchivesSuggester object and invokes its methods to apply transformations (if requested
by the user), find suggestions for remote archives, get statistics, etc.
"""

import logging
import os
from typing import List, Optional

from package_validation_tool.operation_cache import disk_cached_operation
from package_validation_tool.package import SUPPORTED_PACKAGE_TYPES
from package_validation_tool.package.rpm.source_package import RPMSourcepackage
from package_validation_tool.package.suggesting_archives import (
    PackageRemoteArchivesStats,
    PackageRemoteArchivesSuggestions,
)
from package_validation_tool.package.suggesting_archives.suggestion_methods import (
    SUGGESTION_METHODS,
)
from package_validation_tool.package.suggesting_archives.transformation_methods import (
    TRANSFORMATION_METHODS,
)

log = logging.getLogger(__name__)


class RemotePackageArchivesSuggester:
    """
    For a given source package (SRPM), suggest remote (upstream) archives based on the local
    archives (extracted from the source package) and on Source stanzas (parsed from the spec file of
    the source package).

    Methods must be called in the following order:
      - apply_transformations() -- optional
      - find_suggestions()
      - determine_unused_spec_sources() -- optional
      - get_suggestion_result() -- returns PackageRemoteArchivesSuggestions object with all analysis
                                   results

    The resulting PackageRemoteArchivesSuggestions object can be printed as JSON via
    write_json_output() func.

    Additionally, static methods with user-friendly output representations are available:
      - get_stats() -- prints condensed statistics on the results in JSON format
      - get_suggestions() -- prints suggestions in plaintext format
    """

    def __init__(
        self,
        source_package_name: str,
        local_archives: List[str],
        spec_sources: List[str],
    ):
        self._suggestion_result = PackageRemoteArchivesSuggestions()
        self._suggestion_result.source_package_name = source_package_name

        # let's keep original archives + Source stanzas from package (before any transformations),
        # so that we can compare and give recommendations to the package maintainers
        self._suggestion_result.orig_local_archives = [os.path.basename(x) for x in local_archives]
        self._suggestion_result.orig_spec_sources = [x for x in spec_sources]

        # let's init after-transformations archives + Source stanzas to the same values as original
        # ones above; these will be overwritten if any transformations are applied
        self._suggestion_result.trans_local_archives = [os.path.basename(x) for x in local_archives]
        self._suggestion_result.trans_spec_sources = [x for x in spec_sources]

        # let's init unused Source stanzas to the same values as original ones above (i.e. all
        # Sources are unused by default); these will be overwritten if any suggestions ran
        self._suggestion_result.unused_spec_sources = [x for x in spec_sources]

        # intermediate mutable objects, can change after each transformation
        self._local_archives = local_archives
        self._spec_sources = spec_sources

        # vars to track the object state, to not violate the order in which methods must be called
        self._apply_transformations_called = False
        self._find_suggestions_called = False

    def has_local_archives_and_spec_sources(self) -> bool:
        """Return whether the package contains local archives and/or Source lines in spec file."""
        return len(self._local_archives) > 0 and len(self._spec_sources) > 0

    def _apply_one_transformation(self, transformation_method) -> bool:
        """Try to apply a transformation. Return true if applied, false otherwise."""
        if not self._local_archives:
            return False
        transformation_result = transformation_method(self._local_archives, self._spec_sources)
        if not transformation_result:
            return False
        self._suggestion_result.transformations.append(transformation_result)
        self._local_archives = transformation_result.output_local_archives.copy()
        self._spec_sources = transformation_result.output_spec_sources.copy()
        return True

    def apply_transformations(self):
        """Try to apply all available transformations. Updates local_archives and spec_sources."""
        if self._apply_transformations_called:
            raise RuntimeError("Cannot invoke apply_transformations twice")
        if self._find_suggestions_called:
            raise RuntimeError("Cannot invoke apply_transformations after find_suggestions")
        # transformations may return only the basenames of newly created archives, therefore assume
        # that all new archives are created in the same directory as the original archives and
        # construct full paths after each transformation
        local_archives_dir = os.path.dirname(self._local_archives[0])
        for transformation_method in TRANSFORMATION_METHODS:
            applied = self._apply_one_transformation(transformation_method)
            if applied:
                # fix archive names (to absolute paths) if they are only basenames
                for idx, archive in enumerate(self._local_archives):
                    if archive == os.path.basename(archive):
                        self._local_archives[idx] = os.path.join(local_archives_dir, archive)

        self._suggestion_result.trans_local_archives = [
            os.path.basename(x) for x in self._local_archives
        ]
        self._suggestion_result.trans_spec_sources = [x for x in self._spec_sources]
        self._apply_transformations_called = True

    def _find_suggestions_for_archive(self, local_archive: str):
        """Find suggestions for an archive (can be several suggestions for one archive)."""
        local_archive_basename = os.path.basename(local_archive)
        log.info("Suggesting remote archives for %s", local_archive_basename)

        suggested_remote_archives = []  # list of RemoteArchiveSuggestion objects
        for suggestion_method in SUGGESTION_METHODS:
            suggested_remote_archives.extend(
                suggestion_method(local_archive_basename, self._spec_sources)
            )

        assert local_archive_basename not in self._suggestion_result.suggestions
        self._suggestion_result.suggestions[local_archive_basename] = suggested_remote_archives

    def find_suggestions(self):
        """For each local archive, find suggestions. Updates suggestion_result."""
        if self._find_suggestions_called:
            raise RuntimeError("Cannot invoke find_suggestions twice")
        for local_archive in self._local_archives:
            self._find_suggestions_for_archive(local_archive)
        self._find_suggestions_called = True

    def determine_unused_spec_sources(self):
        """Detects which Source lines in the spec were unused. Updates suggestion_result."""
        if not self._find_suggestions_called:
            raise RuntimeError(
                "Cannot invoke determine_unused_spec_sources before find_suggestions"
            )
        all_spec_sources = set(self._spec_sources)
        used_spec_sources: set[str] = set()
        for remote_archive_results in self._suggestion_result.suggestions.values():
            used_spec_sources.update(
                x.spec_source for x in remote_archive_results if x.spec_source is not None
            )
        self._suggestion_result.unused_spec_sources = list(all_spec_sources - used_spec_sources)

    def get_suggestion_result(self):
        return self._suggestion_result

    @staticmethod
    def get_stats(
        suggestion_result: PackageRemoteArchivesSuggestions,
    ) -> PackageRemoteArchivesStats:
        suggested_local_archives = sum(1 for x in suggestion_result.suggestions.values() if x)

        package_stats = PackageRemoteArchivesStats()
        package_stats.transformations_applied = len(suggestion_result.transformations)
        package_stats.suggested_local_archives = suggested_local_archives
        package_stats.total_local_archives = len(suggestion_result.trans_local_archives)
        if package_stats.total_local_archives > 0:
            package_stats.suggested_archives_ratio = (
                float(package_stats.suggested_local_archives) / package_stats.total_local_archives
            )
        package_stats.unused_spec_sources = len(suggestion_result.unused_spec_sources)
        package_stats.all_spec_sources = len(suggestion_result.trans_spec_sources)
        if package_stats.all_spec_sources > 0:
            package_stats.unused_specs_ratio = (
                float(package_stats.unused_spec_sources) / package_stats.all_spec_sources
            )
        return package_stats

    @staticmethod
    def get_suggestions(suggestion_result: PackageRemoteArchivesSuggestions) -> List[str]:
        """Print suggestions how to modify the local archives and/or Sources in spec file."""
        text = []

        # construct one list of local archives (after transformations) and one list of corresponding
        # highest-confidence suggested remote archive URLs
        new_local_archives = list()
        new_spec_sources = list()
        for local_archive, remote_archive_results in suggestion_result.suggestions.items():
            new_local_archives.append(local_archive)
            sorted_results = sorted(
                remote_archive_results, key=lambda x: x.confidence, reverse=True
            )
            if sorted_results:
                new_spec_sources.append(sorted_results[0].remote_archive)

        # note that automatically preparing a "suggested" source package is currently considered too
        # complex and too brittle (consider for example, how you could encode name/version macros in
        # the Source lines of the spec file in an automatic manner...)
        if set(suggestion_result.orig_local_archives) != set(new_local_archives):
            text.append("We suggest to change local archives in package sources:")
            text.append("   - from:")
            for orig_local_archive in suggestion_result.orig_local_archives:
                text.append(f"        {orig_local_archive}")
            text.append("   - to:")
            for new_local_archive in new_local_archives:
                text.append(f"        {new_local_archive}")
        else:
            text.append("✓ We have no suggestions to change local archives in package sources")

        if set(suggestion_result.orig_spec_sources) != set(new_spec_sources):
            text.append("We suggest to change Source lines in package spec file:")
            text.append("   - from:")
            for orig_spec_source in suggestion_result.orig_spec_sources:
                text.append(f"        {orig_spec_source}")
            text.append("   - to:")
            for new_spec_source in new_spec_sources:
                text.append(f"        {new_spec_source}")
        else:
            text.append("✓ We have no suggestions to change Source lines in package spec file")

        return text


@disk_cached_operation
def _get_remote_archives_for_source_package(
    source_package: RPMSourcepackage,
    transform_archives: bool = False,
) -> PackageRemoteArchivesSuggestions:
    """
    Helper to suggest_remote_package_archives() that caches the result on disk.

    Works on source packages (SRPMs). This cached operation is useful when two RPMs resolve to the
    same SRPM -- the second RPM will reuse the cached PackageRemoteArchivesSuggestions.
    """
    source_package_name = source_package.get_name()
    local_archives, spec_sources = source_package.get_local_and_spec_source_archives()

    if source_package_name is None:
        raise ValueError("Unable to determine source package name")

    remote_package_archive_suggester = RemotePackageArchivesSuggester(
        source_package_name=source_package_name,
        local_archives=local_archives,
        spec_sources=spec_sources,
    )

    if not remote_package_archive_suggester.has_local_archives_and_spec_sources():
        log.warning("No local archives and/or Source stanzas in the spec file")
        return remote_package_archive_suggester.get_suggestion_result()  # empty result

    if transform_archives:
        remote_package_archive_suggester.apply_transformations()

    remote_package_archive_suggester.find_suggestions()
    remote_package_archive_suggester.determine_unused_spec_sources()
    return remote_package_archive_suggester.get_suggestion_result()


@disk_cached_operation
def get_remote_archives_for_package(
    package_name: str,
    srpm_file: Optional[str] = None,
    package_type: str = "rpm",
    transform_archives: bool = False,
) -> PackageRemoteArchivesSuggestions:
    """
    Helper to suggest_remote_package_archives() that caches the result on disk.

    Works on final binary packages (RPMs). This is useful when the same RPM is processed twice --
    the second invocation will reuse the cached PackageRemoteArchivesSuggestions.
    """
    if package_type not in SUPPORTED_PACKAGE_TYPES:
        raise ValueError(f"Unsupported package type: {package_type}")

    # note: it is important to keep `source_package` for the lifetime of this function, because
    # internally RPMSourcepackage uses tempfile.TemporaryDirectory to keep local archive files which
    # deletes the files as soon as the (function) context is left
    if package_type == "rpm":
        source_package = RPMSourcepackage(package_name, srpm_file=srpm_file)

    # fixup name of the source package (as originally it is the final package name, not the source
    # package name, e.g. `openssh-clients` instead of `openssh`); this is important for caching
    #
    # FIXME: this triggers a slow "download-extract-parse" routine, even though we only need to
    #        learn the name of source package and then we probably get the result from the cache
    source_package_name = source_package.get_name()
    if source_package_name is None:
        raise ValueError("Unable to determine source package name")
    source_package.package_name = source_package_name

    return _get_remote_archives_for_source_package(
        source_package=source_package,
        transform_archives=transform_archives,
    )


def suggest_remote_package_archives(
    package_name: str,
    srpm_file: Optional[str] = None,
    output_json_path: Optional[str] = None,
    package_type: str = "rpm",
    transform_archives: bool = False,
) -> bool:
    """
    First find a source package for the given package. Then suggest remote (upstream) archives based
    on the local archives (extracted from the source package) and on Source stanzas (parsed from the
    the spec file of the source package):

      - If a Source stanza contains a well-formed and accessible URL to the remote archive, this URL
        is a single suggested remote archive for the corresponding local archive.
      - If a Source stanza contains a well-formed but inaccessible URL to the remote archive, the
        function uses heuristics to suggest a list of remote archives based on the URL (e.g.,
        domain) and on the package name.
      - If a Source stanza contains a badly-formed URL to the remote archive (e.g., only the
        basename), the function uses heuristics to suggest a list of remote archives based on the
        package name. Heuristics include:
          - a set of well-known web-sites which host source code archives,
          - requests to Repology [TBD],
          - cross-checking Source stanzas from other repos such as Fedora or CentOS Stream [TBD],
          - parsing the comments pertaining to the Source stanza in the spec file [TBD].

    Additionally, before matching local vs remote archives, this function optionally performs
    transformations on these archives. Current transformations include:

      - Extracting "archive of archives". In some cases, maintainers of the package choose to fold
        multiple source-code archives in a single huge archive. To suggest remote archives in this
        case, the local archive must be unfolded first, and then a remote archive must be searched
        for each extracted archive. See _transform_extract_nested_archives().
      - Modifying Source stanzas of the original spec, by removing URL fragments (last part of a URL
        after the hash mark `#`). See _transform_remove_url_fragment_from_spec_sources().

    Return true if each local archive was matched to at least one accessible remote archive (i.e.,
    all archives in the source package have a matching source on the internet).
    """

    suggestion_result = get_remote_archives_for_package(
        package_name=package_name,
        srpm_file=srpm_file,
        package_type=package_type,
        transform_archives=transform_archives,
    )

    text = RemotePackageArchivesSuggester.get_suggestions(suggestion_result)
    for line in text:
        log.info(line)

    package_stats = RemotePackageArchivesSuggester.get_stats(suggestion_result)
    log.info("Suggesting remote archives results: %r", package_stats)

    if output_json_path:
        suggestion_result.write_json_output(output_json_path)

    return package_stats.suggested_local_archives == package_stats.total_local_archives
