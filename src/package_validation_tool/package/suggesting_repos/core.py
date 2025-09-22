# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Entrypoint to suggesting (git) repos for each local archive in the package.

Implements the CLI sub-command `suggest-package-repos`, see suggest_package_repos() function. Under
the hood, this function creates a RepoSuggester object and invokes its methods to find suggestions
for (git) repos.
"""

import logging
import os
import shutil
from typing import List, Tuple

from package_validation_tool.operation_cache import disk_cached_operation
from package_validation_tool.package import SUPPORTED_PACKAGE_TYPES
from package_validation_tool.package.rpm.source_package import RPMSourcepackage
from package_validation_tool.package.suggesting_repos import (
    PackageRemoteReposStats,
    PackageRemoteReposSuggestions,
)
from package_validation_tool.package.suggesting_repos.suggestion_methods import SUGGESTION_METHODS
from package_validation_tool.package.suggesting_repos.version_utils import (
    VersionInfo,
    extract_version_from_archive_name,
    verify_commit_exists,
    verify_tag_exists,
)
from package_validation_tool.utils import clone_git_repo

log = logging.getLogger(__name__)


class RepoSuggester:
    """
    For a given source package (SRPM), suggest upstream (git) repos based on the local archives
    (extracted from the source package) and on all URLs (parsed from the spec file of the source
    package). Additionally, try to find a git tag/commit that corresponds to the version of the
    local archive.

    Methods must be called in the following order:
      - find_suggestions()
      - update_suggestions_with_tags()
      - get_suggestion_result() -- returns PackageRemoteReposSuggestions object with all analysis
                                   results

    The resulting PackageRemoteReposSuggestions object can be printed as JSON via
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
        self._suggestion_result = PackageRemoteReposSuggestions()
        self._suggestion_result.source_package_name = source_package_name
        self._suggestion_result.local_archives = [os.path.basename(x) for x in local_archives]

        self._local_archives = local_archives
        self._spec_sources = spec_sources

        # vars to track the object state, to not violate the order in which methods must be called
        self._find_suggestions_called = False
        self._update_suggestions_called = False

    def has_local_archives(self) -> bool:
        """Return whether the package contains local archives."""
        return len(self._local_archives) > 0

    def _find_version_in_git_repo(
        self, repo: str, version_info: VersionInfo, archive: str = ""
    ) -> Tuple[str, str]:
        """Find git commit and tag for a repo based on version extracted from local archive."""
        success, repo_dir = clone_git_repo(repo, bare=True)
        if not success:
            log.debug("Failed to clone repository %s", repo)
            return "", ""

        try:
            if version_info.is_commit_hash:
                full_commit_hash = verify_commit_exists(repo_dir, version_info.version)
                return full_commit_hash, ""
            else:
                full_commit_hash, tag = verify_tag_exists(
                    archive,
                    repo_dir,
                    version_info.version,
                    version_info.date,
                    version_info.suffix,
                )
                return full_commit_hash, tag
        finally:
            if repo_dir and os.path.exists(repo_dir):
                shutil.rmtree(repo_dir)

    def _find_suggestions_for_archive(self, local_archive: str):
        """Find suggestions for an archive (can be several suggestions for one archive)."""
        local_archive_basename = os.path.basename(local_archive)
        log.info("Suggesting repos for archive %s", local_archive_basename)

        suggested_repos = []  # list of RemoteRepoSuggestion objects
        for suggestion_method in SUGGESTION_METHODS:
            suggested_repos.extend(suggestion_method(local_archive_basename, self._spec_sources))

        if local_archive_basename in self._suggestion_result.suggestions:
            raise RuntimeError(
                f"Called suggesting repos for archive {local_archive_basename} twice; must be impossible"
            )
        self._suggestion_result.suggestions[local_archive_basename] = suggested_repos

    def find_suggestions(self):
        """For each local archive, find suggestions. Updates suggestion_result."""
        if self._find_suggestions_called:
            raise RuntimeError("Cannot invoke find_suggestions twice")
        for local_archive in self._local_archives:
            self._find_suggestions_for_archive(local_archive)
        self._find_suggestions_called = True

    def _update_suggestions_with_tags_for_archive(self, local_archive: str):
        """Find git tag/commit for each suggestion for an archive."""
        local_archive_basename = os.path.basename(local_archive)
        if not self._suggestion_result.suggestions.get(local_archive_basename):
            return

        log.info("Finding git tags for %s", local_archive_basename)
        for repo_result in self._suggestion_result.suggestions[local_archive_basename]:
            version_info = extract_version_from_archive_name(local_archive_basename)
            commit_hash, tag = self._find_version_in_git_repo(
                repo_result.repo, version_info, local_archive_basename
            )
            repo_result.commit_hash = commit_hash
            repo_result.tag = tag
            # TODO: the commit/tag may be empty (i.e. not found), thus we must either remove the
            #       suggested repo from list of suggestions or at least lower the confidence score

    def update_suggestions_with_tags(self):
        """For each local archive, find git tag/commit. Updates suggestion_result."""
        if not self._find_suggestions_called:
            raise RuntimeError("Cannot invoke update_suggestions_with_tags before find_suggestions")
        for local_archive in self._local_archives:
            self._update_suggestions_with_tags_for_archive(local_archive)
        self._update_suggestions_called = True

    def get_suggestion_result(self):
        return self._suggestion_result

    @staticmethod
    def get_stats(suggestion_result: PackageRemoteReposSuggestions) -> PackageRemoteReposStats:
        suggested_local_archives = sum(1 for x in suggestion_result.suggestions.values() if x)

        package_stats = PackageRemoteReposStats()
        package_stats.suggested_local_archives = suggested_local_archives
        package_stats.total_local_archives = len(suggestion_result.local_archives)
        if package_stats.total_local_archives > 0:
            package_stats.suggested_archives_ratio = (
                float(package_stats.suggested_local_archives) / package_stats.total_local_archives
            )
        return package_stats

    @staticmethod
    def get_suggestions(suggestion_result: PackageRemoteReposSuggestions) -> List[str]:
        """Print repo suggestions."""
        text = []

        # for each local archive in package, print highest-confidence suggested repo URL
        for local_archive, repo_results in suggestion_result.suggestions.items():
            sorted_results = sorted(repo_results, key=lambda x: x.confidence, reverse=True)
            if sorted_results:
                repo = sorted_results[0].repo
                text.append(f"Repo suggestion for {local_archive}: {repo}")
            else:
                text.append(f"Repo suggestion for {local_archive}: <no repo found>")

        return text


@disk_cached_operation
def _get_repos_for_source_package(
    source_package: RPMSourcepackage,
) -> PackageRemoteReposSuggestions:
    """
    Helper to suggest_package_repos() that caches the result on disk.

    Works on source packages (SRPMs). This cached operation is useful when two RPMs resolve to the
    same SRPM -- the second RPM will reuse the cached PackageRemoteReposSuggestions.
    """
    source_package_name = source_package.get_name()
    local_archives, spec_sources = source_package.get_local_and_spec_source_archives()

    # we want to use everything that looks like a URL in the spec file, not only Source lines
    spec_sources.extend(source_package.get_repourls())
    spec_sources = list(set(spec_sources))  # remove duplicates

    repo_suggester = RepoSuggester(
        source_package_name=source_package_name,
        local_archives=local_archives,
        spec_sources=spec_sources,
    )

    if not repo_suggester.has_local_archives():
        log.warning("No local archives in the package")
        return repo_suggester.get_suggestion_result()  # empty result

    repo_suggester.find_suggestions()
    repo_suggester.update_suggestions_with_tags()
    return repo_suggester.get_suggestion_result()


@disk_cached_operation
def get_repos_for_package(
    package_name: str,
    srpm_file: str = None,
    package_type: str = "rpm",
) -> PackageRemoteReposSuggestions:
    """
    Helper to suggest_package_repos() that caches the result on disk.

    Works on final binary packages (RPMs). This is useful when the same RPM is processed twice --
    the second invocation will reuse the cached PackageRemoteReposSuggestions.
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
    source_package.package_name = source_package.get_name()

    return _get_repos_for_source_package(
        source_package=source_package,
    )


def suggest_package_repos(
    package_name: str,
    srpm_file: str = None,
    output_json_path: str = None,
    package_type: str = "rpm",
) -> bool:
    """
    First find a source package for the given package. Then suggest upstream (git) repos based on
    the local archives (extracted from the source package) and on all URLs (parsed from the the spec
    file of the source package):

      - Suggest URLs from the spec file that match the basename of the local archive.
      - Download web pages for every URL in the spec file, and then scrape all links in these web
        pages. Return only those links that seem related to the local archive.
      - Guess repo URL based on the basename of the local archive, trying several well-known repo
        hosting platforms (like GitLab and GitHub).
      - Find repo URL based on the basename of the local archive, by querying GitHub's public API.

    Only those repos are suggested that are proper accessible code repos. Note that currently only
    git repos are supported.

    Return true if each local archive has at least one suggestion for a repo (i.e., all archives in
    the source package have seemingly-corresponding repos on the internet).
    """

    suggestion_result = get_repos_for_package(
        package_name=package_name,
        srpm_file=srpm_file,
        package_type=package_type,
    )

    text = RepoSuggester.get_suggestions(suggestion_result)
    for line in text:
        log.info(line)

    package_stats = RepoSuggester.get_stats(suggestion_result)
    log.info("Suggesting repos results: %r", package_stats)

    if output_json_path:
        suggestion_result.write_json_output(output_json_path)

    return package_stats.suggested_local_archives == package_stats.total_local_archives
