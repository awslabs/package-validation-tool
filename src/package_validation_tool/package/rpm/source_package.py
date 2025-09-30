# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Module to handle RPM source files.
"""

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from package_validation_tool.matching.autotools import AutotoolsRunner
from package_validation_tool.matching.changelog import ChangelogRunner
from package_validation_tool.matching.file_matching import (
    SUPPORTED_ARCHIVE_TYPES,
    FileMatcher,
    FileMatchState,
)
from package_validation_tool.operation_cache import disk_cached_operation
from package_validation_tool.package import (
    InstallationDecision,
    PackageRemoteArchivesResult,
    PackageRemoteReposResult,
    RemoteArchiveResult,
    RemoteRepoResult,
)
from package_validation_tool.package.rpm.spec import RPMSpec, RPMSpecError
from package_validation_tool.package.rpm.utils import (
    download_and_extract_source_package,
    get_single_spec_file,
    install_build_dependencies,
    prepare_rpmbuild_source,
)
from package_validation_tool.package.suggesting_archives import RemoteArchiveSuggestion
from package_validation_tool.package.suggesting_repos import RemoteRepoSuggestion
from package_validation_tool.utils import (
    checkout_in_git_repo,
    clone_git_repo,
    download_file,
    get_archive_files,
    get_git_tree_hash,
    hash256sum,
    pushd,
    save_path,
    secure_unpack_archive,
)

log = logging.getLogger(__name__)

# Environment variable name for file matcher diffs output directory
PVT_FILE_MATCHER_DIFFS_PATH = "PVT_FILE_MATCHER_DIFFS_PATH"


def _collect_file_match_statistics(
    result_object,
    file_matcher: FileMatcher,
    archive_path: str,
    package_name: str,
    local_archive_basename: str,
) -> None:
    """
    Collect statistics on matching/conflicting files between local archive and remote source,
    and save this statistics into the result object.

    This function works with both RemoteRepoResult and RemoteArchiveResult objects since they
    have the same field structure for file statistics.

    Args:
        result_object: Either RemoteRepoResult or RemoteArchiveResult object to populate
        file_matcher: FileMatcher object containing the comparison results
        archive_path: Path to the local archive directory (for relative path calculation)
        package_name: Name of the package (for diff file saving)
        local_archive_basename: Basename of the local archive (for diff file saving)
    """
    logged_file_matcher_diffs_path = False
    result_object.conflicts = {}
    for file_path, state in file_matcher.state_dict.items():
        result_object.files_total += 1
        result_object.files_matched += int(state == FileMatchState.MATCHING)
        result_object.files_different += int(state == FileMatchState.DIFFERENT)
        result_object.files_no_counterpart += int(state == FileMatchState.NO_COUNTERPART)

        if state != FileMatchState.MATCHING:
            relative_file_path = str(Path(file_path).relative_to(archive_path))
            result_object.conflicts[relative_file_path] = state.name

            if state == FileMatchState.DIFFERENT and os.environ.get(PVT_FILE_MATCHER_DIFFS_PATH):
                diffs_dir = os.environ[PVT_FILE_MATCHER_DIFFS_PATH]
                dst_path = f"{diffs_dir}/{package_name}/{local_archive_basename}"

                if not logged_file_matcher_diffs_path:
                    log.info("Saving differing files in %s", dst_path)
                    logged_file_matcher_diffs_path = True

                dst_file_path = f"{dst_path}/{relative_file_path}"
                Path(dst_file_path).parent.mkdir(parents=True, exist_ok=True)

                # For archive matching, we need to get the temporary directories from the calling context
                # This will be handled by the caller providing the appropriate paths
                # For now, we'll skip the file copying part for archives - it can be added later if needed

    # Calculate ratios
    if result_object.files_total > 0:
        result_object.files_matched_ratio = result_object.files_matched / result_object.files_total
        result_object.files_different_ratio = (
            result_object.files_different / result_object.files_total
        )
        result_object.files_no_counterpart_ratio = (
            result_object.files_no_counterpart / result_object.files_total
        )
    else:
        result_object.files_matched_ratio = 0.0
        result_object.files_different_ratio = 0.0
        result_object.files_no_counterpart_ratio = 0.0

    log.info(
        "Stats: %d files total, %d matching (%.2f%%), %d different (%.2f%%), %d no counterpart (%.2f%%)",
        result_object.files_total,
        result_object.files_matched,
        result_object.files_matched_ratio * 100,
        result_object.files_different,
        result_object.files_different_ratio * 100,
        result_object.files_no_counterpart,
        result_object.files_no_counterpart_ratio * 100,
    )


class RPMSourcepackage:

    RPM_HOME_DIRNAME = "rpm_home"

    def __init__(
        self,
        package_name: str,
        srpm_file: Optional[str] = None,
        install_build_deps: InstallationDecision = InstallationDecision.NO,
    ):
        # note that some fields have "__" suffix, to ignore them in the cached object (as they have
        # temporary directories in their values)
        self.package_name = package_name
        self._storage_dir__: Optional[str] = None  # Temporary storage on disk for this object
        self._srpm_file_path__: Optional[str] = os.path.abspath(srpm_file) if srpm_file else None
        self._srpm_content_dir__: Optional[str] = None
        self._spec: Optional[RPMSpec] = None
        self._rpm_build_home__: Optional[str] = None  # Use this as HOME for rpmbuild commands
        self._package_source_path__: Optional[str] = None  # Stores the source with patches applied
        self._install_build_deps__: InstallationDecision = InstallationDecision(install_build_deps)

        # In case we already have a file, also store the sha256sum of it
        self._srpm_file_path_sha256sum = (
            hash256sum(self._srpm_file_path__) if self._srpm_file_path__ else None
        )

    def _initialize_package(self) -> bool:
        """Initialize this object on disk based on the given package name."""

        # already initialized, no need to continue
        if self._spec:
            return True

        # create temporary directory that is destroyed once this object is over
        self._storage_dir__ = tempfile.TemporaryDirectory(
            prefix="package-validation-tool-rpm-",
            suffix=f"-{save_path(self.package_name)}",
        )

        # download source package, and extract, in content directory
        with pushd(self._storage_dir__.name):
            self._srpm_file_path__, self._srpm_content_dir__ = download_and_extract_source_package(
                self.package_name, srpm_file=self._srpm_file_path__
            )
        if not self._srpm_file_path__ or not self._srpm_content_dir__:
            return False
        self._srpm_file_path_sha256sum = hash256sum(self._srpm_file_path__)

        if self._install_build_deps__ is not InstallationDecision.NO:
            try:
                install_build_dependencies(self._srpm_file_path__)
            except RuntimeError as e:
                log.warning(
                    "Failed to install build dependencies for package %s with %s",
                    self.package_name,
                    e,
                )
                if self._install_build_deps__ is InstallationDecision.ALWAYS:
                    return False
                log.info("Ignoring build dependency installation failure, continuing")

        # prepare package source code
        try:
            with pushd(self._storage_dir__.name):
                self._rpm_build_home__, self._package_source_path__, spec_file = (
                    prepare_rpmbuild_source(
                        src_rpm_file=self._srpm_file_path__,
                        package_rpmbuild_home=RPMSourcepackage.RPM_HOME_DIRNAME,
                    )
                )
                log.debug(
                    "Storing package %s source with applied patches in %s",
                    self.package_name,
                    self._package_source_path__,
                )
        except Exception as e:
            e_first_line = str(e).partition("\n")[0]
            log.warning(
                "Failed to prepare source for package %s: %s", self.package_name, e_first_line
            )
            log.info("Parsing specfile from extracted .src.rpm content directly ...")
            spec_file = get_single_spec_file(self._srpm_content_dir__)

        if not spec_file:
            log.warning("Failed to find spec file for package %s", self.package_name)
            return False

        # setup spec file object for this source package
        try:
            self._spec = RPMSpec(spec_file=spec_file, fallback_plain_rpm=True)
        except RPMSpecError as e:
            log.warning(
                "Failed to parse spec file %s of package %s with %s",
                spec_file,
                self.package_name,
                e,
            )
            self._spec = None
            return False

        return True

    @disk_cached_operation
    def match_remote_archives(
        self,
        suggested_archives: Dict[str, List[RemoteArchiveSuggestion]],
        unused_spec_sources: List[str],
    ) -> PackageRemoteArchivesResult:
        """
        Match the local package archives against suggested remote archives.

        This function compares local archive files from the source package with suggested remote
        archives by downloading the remote archives and running FileMatcher on each pair of
        archives.

        This function always returns a PackageRemoteArchivesResult object. The object has `matching
        = True` if the function finds at least one matching remote archive for each local archive
        (or if the package contains no local archives).

        Args:
            suggested_archives: Dict mapping local archive basenames to lists of
                                RemoteArchiveSuggestion objects.
        """

        if not self._initialize_package():
            log.debug(
                "Failed initialization of SRPM with SRPM %r and spec %r",
                self._srpm_file_path__ is not None,
                self._spec is not None,
            )
            return PackageRemoteArchivesResult(
                source_package_name=self.package_name,
                matching=False,
                results={},
                unused_spec_sources=unused_spec_sources,
                srpm_available=self._srpm_file_path__ is not None,
                spec_valid=self._spec is not None,
                source_extractable=self._package_source_path__ is not None,
            )

        local_archive_files = get_archive_files(self._srpm_content_dir__)

        # no local archives, so no need to download (consider match as true)
        if not local_archive_files:
            return PackageRemoteArchivesResult(
                source_package_name=self.package_name,
                matching=True,
                results={},
                unused_spec_sources=unused_spec_sources,
                srpm_available=self._srpm_file_path__ is not None,
                spec_valid=self._spec is not None,
                source_extractable=self._package_source_path__ is not None,
            )

        matched_archives = {}
        archive_hashes = {}

        # For each local archive, try to match it against suggested remote archives logic: for each
        # local archive and for each suggested remote archive found for this local archive, first
        # download the remote repo in a temp dir, then compare archives (via FileMatcher) in these
        # two temp dirs. If all files match, mark it so; if not, collect all conflicting files. In
        # any case, add this pair (local archive, remote archive) to matched_archives list.
        for local_archive_file in local_archive_files:
            local_archive_basename = os.path.basename(local_archive_file)

            matched_archives[local_archive_basename] = []
            archive_hashes[local_archive_basename] = hash256sum(local_archive_file)

            if local_archive_basename not in suggested_archives:
                log.warning(
                    "No suggested archives found for local archive %s", local_archive_basename
                )
                continue

            # we want to first match remote archives that were suggested with highest confidence
            sorted_suggested_archives = sorted(
                suggested_archives[local_archive_basename], key=lambda x: x.confidence, reverse=True
            )

            log.debug(
                "Matching remote archives (sorted by confidence): %r ...",
                [r.remote_archive for r in sorted_suggested_archives],
            )

            # Helper sets for deduplication
            seen_remote_urls = set()
            seen_remote_hashsums = set()

            for suggested_archive in sorted_suggested_archives:
                if not suggested_archive.remote_archive:
                    continue

                # Skip if we've already processed this remote archive URL
                if suggested_archive.remote_archive in seen_remote_urls:
                    log.debug(
                        "Skipping duplicate remote archive URL: %s",
                        suggested_archive.remote_archive,
                    )
                    continue
                seen_remote_urls.add(suggested_archive.remote_archive)

                # associate the remote archive with local archive; set the defaults
                archive_result = RemoteArchiveResult(
                    remote_archive=suggested_archive.remote_archive,
                    accessible=False,
                    matched=False,
                )
                matched_archives[local_archive_basename].append(archive_result)

                remote_archive_basename = os.path.basename(suggested_archive.remote_archive)
                with tempfile.TemporaryDirectory(
                    prefix="package-validation-tool-suggested-archive-",
                    suffix=f"-{save_path(remote_archive_basename)}",
                    dir=self._storage_dir__.name,
                ) as tmpdirname:
                    log.debug(
                        "Downloading suggested archive %s into %s",
                        suggested_archive.remote_archive,
                        tmpdirname,
                    )
                    with pushd(tmpdirname):
                        downloaded_archive = os.path.join(tmpdirname, remote_archive_basename)

                        if not download_file(suggested_archive.remote_archive, downloaded_archive):
                            log.warning(
                                "Failed to download suggested archive %s, trying next one`",
                                suggested_archive.remote_archive,
                            )
                            continue

                        # we were able to download this archive, mark as accessible
                        archive_result.accessible = True

                        # Calculate hashsum for content-level deduplication
                        remote_archive_hashsum = hash256sum(downloaded_archive)
                        if remote_archive_hashsum in seen_remote_hashsums:
                            log.debug(
                                "Skipping duplicate remote archive content (hashsum: %s): %s",
                                remote_archive_hashsum,
                                suggested_archive.remote_archive,
                            )
                            # Remove the current archive result that was already added
                            matched_archives[local_archive_basename].pop()
                            continue
                        seen_remote_hashsums.add(remote_archive_hashsum)

                        # Extract both archives into temporary directories for comparison
                        local_extract_dir = os.path.join(tmpdirname, "local_archive")
                        remote_extract_dir = os.path.join(tmpdirname, "remote_archive")

                        os.makedirs(local_extract_dir, exist_ok=True)
                        os.makedirs(remote_extract_dir, exist_ok=True)

                        log.info(
                            "Extracting local archive %s and remote archive %s for comparison",
                            local_archive_basename,
                            remote_archive_basename,
                        )

                        try:
                            if not secure_unpack_archive(local_archive_file, local_extract_dir):
                                log.error(
                                    "Failed to securely extract local archive %s",
                                    local_archive_file,
                                )
                                continue

                            if not secure_unpack_archive(downloaded_archive, remote_extract_dir):
                                log.error(
                                    "Failed to securely extract remote archive %s",
                                    downloaded_archive,
                                )
                                continue

                            fm = FileMatcher()
                            log.info(
                                "Matching extracted local archive %s with extracted remote archive %s",
                                local_extract_dir,
                                remote_extract_dir,
                            )
                            fm.match_left(local_extract_dir, remote_extract_dir)
                            _collect_file_match_statistics(
                                archive_result,
                                fm,
                                local_extract_dir,
                                self.package_name,
                                local_archive_basename,
                            )

                            if not fm.left_is_matching():
                                continue
                        except Exception as e:
                            log.info(
                                "Failed to match local archive vs suggested archive with %r", e
                            )
                            continue

                        # we found an archive match
                        archive_result.matched = True

        matching = True
        for archive_name, archives_list in matched_archives.items():
            if not any(archive.matched for archive in archives_list):
                log.debug("Local archive %s does not have any matching archives", archive_name)
                matching = False

        return PackageRemoteArchivesResult(
            source_package_name=self.package_name,
            matching=matching,
            results=matched_archives,
            unused_spec_sources=unused_spec_sources,
            srpm_available=self._srpm_file_path__ is not None,
            spec_valid=self._spec is not None,
            source_extractable=self._package_source_path__ is not None,
            archive_hashes=archive_hashes,
        )

    @disk_cached_operation
    def match_remote_repos(
        self,
        suggested_repos: Dict[str, List[RemoteRepoSuggestion]],
        autotools_dir: Optional[str] = None,
        apply_autotools: bool = True,
    ) -> PackageRemoteReposResult:
        """
        Match the local package archives against remote repositories.

        This function compares local archive files from the source package with suggested remote
        repositories by extracting the local archives and checking out the remote repositories at
        specific commits/tags, then comparing their contents.

        This function always returns a PackageRemoteReposResult object. The object has `matching =
        True` if the function finds at least one matching remote repository for each local archive
        (or if the package contains no local archives).

        Args:
            suggested_repos: Dict mapping local archive basenames to lists of RemoteRepoSuggestions
                             containing repository URLs, commits/tags, and confidence scores.
            autotools_dir: Directory where Autotools tools will be downloaded and installed.
            apply_autotools: Whether to enable Autotools invocations.
        """

        if not self._initialize_package():
            log.debug(
                "Failed initialization of SRPM with SRPM %r and spec %r",
                self._srpm_file_path__ is not None,
                self._spec is not None,
            )
            return PackageRemoteReposResult(
                source_package_name=self.package_name,
                matching=False,
                results={},
                srpm_available=self._srpm_file_path__ is not None,
                spec_valid=self._spec is not None,
                source_extractable=self._package_source_path__ is not None,
            )

        local_archive_files = get_archive_files(self._srpm_content_dir__)

        # no local archives, so no need to git-clone repos (consider match as true)
        if not local_archive_files:
            return PackageRemoteReposResult(
                source_package_name=self.package_name,
                matching=True,
                results={},
                srpm_available=self._srpm_file_path__ is not None,
                spec_valid=self._spec is not None,
                source_extractable=self._package_source_path__ is not None,
            )

        matched_archives = {}
        archive_hashes = {}

        # logic: for each local archive and for each remote repo found for this local archive,
        # first extract the local archive in a temp dir, git-clone and git-checkout the remote repo
        # in a temp dir, then compare files (via FileMatcher) in these two temp dirs. If all files
        # match, mark it so; if not, collect all conflicting files. In any case, add this pair
        # (local archive, remote repo) to matched_archives list.
        for local_archive in local_archive_files:
            local_archive_basename = os.path.basename(local_archive)

            matched_archives[local_archive_basename] = []
            archive_hashes[local_archive_basename] = hash256sum(local_archive)

            if not suggested_repos.get(local_archive_basename):
                log.warning("No repos found for local archive %s", local_archive_basename)
                continue

            # unpack local archive, because we will compare with non-archived git repo checkouts
            with tempfile.TemporaryDirectory(
                prefix="package-validation-tool-archive-to-match-",
                suffix=f"-{save_path(local_archive_basename)}",
                dir=self._storage_dir__.name,
            ) as tmpdir_archive:
                try:
                    log.debug(
                        "Extract archive %s into directory %s ...",
                        local_archive_basename,
                        tmpdir_archive,
                    )
                    if not secure_unpack_archive(local_archive, tmpdir_archive):
                        log.error("Failed to securely extract archive %s", local_archive)
                        continue
                    log.info("Archive extracted to: %s", tmpdir_archive)
                except Exception as e:
                    log.warning(
                        "Extracting archive %s failed with exception %r", local_archive_basename, e
                    )
                    continue

                # frequently, the local archive contains a single dir, and all sources are in this
                # dir, so let's set archive's root to this dir (e.g. `zlib-1.2.11.tar.xz` unpacks to
                # `zlib-1.2.11/zutil.h`, `zlib-1.2.11/zutil.c` ...)
                contents = list(Path(tmpdir_archive).iterdir())
                if len(contents) == 1 and contents[0].is_dir():
                    tmpdir_archive = str(contents[0])

                # we want to first match remote repos that were suggested with highest confidence
                sorted_suggested_repos = sorted(
                    suggested_repos[local_archive_basename],
                    key=lambda x: x.confidence,
                    reverse=True,
                )

                log.debug(
                    "Matching repos (sorted by confidence): %r ...",
                    [r.repo for r in sorted_suggested_repos],
                )

                # Helper set for deduplication
                seen_remote_repos = set()
                seen_repo_tree_hashes = set()

                for suggested_repo in sorted_suggested_repos:
                    if not suggested_repo.tag and not suggested_repo.commit_hash:
                        log.debug(
                            "Repo %s does not have a matching tag/commit", suggested_repo.repo
                        )
                        continue

                    # Skip if we've already processed this remote repository URL
                    if suggested_repo.repo in seen_remote_repos:
                        log.debug(
                            "Skipping duplicate remote repository URL: %s", suggested_repo.repo
                        )
                        continue
                    seen_remote_repos.add(suggested_repo.repo)

                    # associate the repo with local archive; set the defaults
                    repo_result = RemoteRepoResult(
                        remote_repo=suggested_repo.repo,
                        commit_hash=suggested_repo.commit_hash,
                        tag=suggested_repo.tag,
                        accessible=False,
                        matched=False,
                    )
                    matched_archives[local_archive_basename].append(repo_result)

                    with tempfile.TemporaryDirectory(
                        prefix="package-validation-tool-repo-to-match-",
                        suffix=f"-{save_path(local_archive_basename)}",
                        dir=self._storage_dir__.name,
                    ) as tmpdir_repo:
                        log.debug("Cloning repo %s into %s", suggested_repo.repo, tmpdir_repo)

                        success, _ = clone_git_repo(
                            suggested_repo.repo, target_dir=tmpdir_repo, bare=True
                        )
                        if not success:
                            log.warning(
                                "Failed to clone repo %s, ignore for matchability check",
                                suggested_repo.repo,
                            )
                            continue

                        if not checkout_in_git_repo(
                            tmpdir_repo, suggested_repo.tag or suggested_repo.commit_hash
                        ):
                            log.warning(
                                "Failed to checkout commit/tag %s in repo %s, ignore for matchability check",
                                suggested_repo.tag or suggested_repo.commit_hash,
                                suggested_repo.repo,
                            )
                            continue

                        # we were able to git-clone and git-checkout this repo, mark as accessible
                        repo_result.accessible = True

                        # Check for content-level deduplication using git tree hash
                        repo_tree_hash = get_git_tree_hash(
                            tmpdir_repo, suggested_repo.tag or suggested_repo.commit_hash
                        )
                        if repo_tree_hash:
                            if repo_tree_hash in seen_repo_tree_hashes:
                                log.debug(
                                    "Skipping duplicate repository content (tree hash: %s): %s",
                                    repo_tree_hash,
                                    suggested_repo.repo,
                                )
                                # Remove the current repo result that was already added
                                matched_archives[local_archive_basename].pop()
                                continue
                            seen_repo_tree_hashes.add(repo_tree_hash)

                        # If enabled, apply Autotools processing before file matching
                        if apply_autotools and autotools_dir and AutotoolsRunner:
                            log.info("Applying Autotools processing before file matching...")
                            repo_result.autotools_applied = True
                            try:
                                autotools_runner = AutotoolsRunner(
                                    autotools_dir=autotools_dir,
                                    src_repo_dir=tmpdir_repo,
                                    package_archive_dir=tmpdir_archive,
                                )
                                autotools_success = autotools_runner.run_autotools()
                                repo_result.tools_versions = (
                                    autotools_runner.get_detected_versions()
                                )
                                log.info(
                                    "Autotools processing completed (%s)",
                                    (
                                        "files generated"
                                        if autotools_success
                                        else "files not generated"
                                    ),
                                )
                            except Exception as e:
                                log.warning("Autotools processing failed: %r", e)

                        # Apply Changelog processing before file matching
                        log.info("Applying Changelog processing before file matching...")
                        try:
                            changelog_runner = ChangelogRunner(
                                src_repo_dir=tmpdir_repo,
                                package_archive_dir=tmpdir_archive,
                            )
                            changelog_success = changelog_runner.run_changelog_generation()
                            log.info(
                                "Changelog processing completed (%s)",
                                "generated" if changelog_success else "not generated",
                            )
                        except Exception as e:
                            log.warning("Changelog processing failed: %r", e)

                        fm = FileMatcher()
                        log.info(
                            "Matching local archive %s with remote repo %s and commit/tag %s",
                            local_archive_basename,
                            suggested_repo.repo,
                            suggested_repo.tag or suggested_repo.commit_hash,
                        )
                        try:
                            fm.match_left(tmpdir_archive, tmpdir_repo)
                            _collect_file_match_statistics(
                                repo_result,
                                fm,
                                tmpdir_archive,
                                self.package_name,
                                local_archive_basename,
                            )

                            if not fm.left_is_matching():
                                continue
                        except Exception as e:
                            log.info("Failed to match local archive vs remote repo with %r", e)
                            continue

                        # we found a repo match
                        repo_result.matched = True

        matching = True
        for archive_name, repos_list in matched_archives.items():
            if not any(repo.matched for repo in repos_list):
                if repos_list:
                    log.debug(
                        "Local archive %s has %d repo(s) but none matched successfully",
                        archive_name,
                        len(repos_list),
                    )
                else:
                    log.debug("Local archive %s does not have any matching repos", archive_name)
                matching = False

        return PackageRemoteReposResult(
            source_package_name=self.package_name,
            matching=matching,
            results=matched_archives,
            archive_hashes=archive_hashes,
            srpm_available=self._srpm_file_path__ is not None,
            spec_valid=self._spec is not None,
            source_extractable=self._package_source_path__ is not None,
        )

    def store_package_content(self, output_dir: str) -> bool:
        """Store package content, SOURCE and SPEC to given directory."""
        if not self._initialize_package():
            log.warning(
                "Failed initialization of SRPM with SRPM %r and spec %r",
                self._srpm_file_path__ is not None,
                self._spec is not None,
            )

        os.makedirs(output_dir, exist_ok=True)

        expected_copies = 3
        copies = 0
        if self._spec:
            specs_dst_dir = os.path.join(output_dir, "SPECS")
            os.makedirs(specs_dst_dir, exist_ok=True)
            log.debug("Storing spec file %s in %s", self._spec.spec_file_abs__, specs_dst_dir)
            shutil.copy(self._spec.spec_file_abs__, specs_dst_dir)
            copies += 1

        if self._package_source_path__:
            src_dst_dir = os.path.join(output_dir, "SOURCE")
            os.makedirs(src_dst_dir, exist_ok=True)
            shutil.rmtree(src_dst_dir, ignore_errors=True)
            log.debug("Storing package source %s in %s", self._package_source_path__, src_dst_dir)
            shutil.copytree(self._package_source_path__, src_dst_dir)
            copies += 1

        if self._srpm_file_path__:
            srpm_dst_dir = os.path.join(output_dir, "SRPM_CONTENT")
            os.makedirs(srpm_dst_dir, exist_ok=True)
            shutil.rmtree(srpm_dst_dir, ignore_errors=True)
            log.debug("Storing SRPM content %s in %s", self._srpm_file_path__, srpm_dst_dir)
            shutil.copytree(self._srpm_content_dir__, srpm_dst_dir)
            copies += 1

        return copies == expected_copies

    def get_local_and_spec_source_archives(self) -> Tuple[List[str], List[str]]:
        """
        Get two lists: one with local package archives (absolute paths) and another with remote
        package archives (values of the Source stanzas in the package's spec file).
        """

        if not self._initialize_package():
            log.debug("Failed initialization of SRPM %r", self._srpm_file_path__)
            return [], []

        spec_sources = self._spec.source_entries().values()
        spec_source_archives = [ar for ar in spec_sources if ar.endswith(SUPPORTED_ARCHIVE_TYPES)]

        local_archives = get_archive_files(self._srpm_content_dir__)

        return local_archives, spec_source_archives

    def get_repourls(self) -> List[str]:
        """Return all repo-address-looking URLs from the package's spec file."""
        if not self._initialize_package():
            log.debug("Failed initialization of SRPM %r", self._srpm_file_path__)
            return []
        return self._spec.repourl_entries()

    def get_name(self) -> Optional[str]:
        """
        Get name of the source package (value of the "Name" field in the package's spec file).
        """
        if not self._initialize_package():
            log.debug("Failed initialization of SRPM %r", self._srpm_file_path__)
            return None
        return self._spec.package_name()
