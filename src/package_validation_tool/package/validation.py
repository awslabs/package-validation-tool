# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Module to validate packages
"""

import json
import logging
import multiprocessing as mp
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import Dict, List, Optional

from package_validation_tool.package import (
    SUPPORTED_PACKAGE_TYPES,
    InstallationDecision,
    JsonSerializableMixin,
    RemoteArchiveResult,
    RemoteRepoResult,
)
from package_validation_tool.package.rpm.source_package import RPMSourcepackage
from package_validation_tool.package.rpm.utils import all_system_packages
from package_validation_tool.package.suggesting_archives import RemoteArchiveSuggestion
from package_validation_tool.package.suggesting_archives.core import get_remote_archives_for_package
from package_validation_tool.package.suggesting_repos import RemoteRepoSuggestion
from package_validation_tool.package.suggesting_repos.core import get_repos_for_package

log = logging.getLogger(__name__)


def store_package_content(
    package_name: str,
    output_dir: str,
    package_type: str = "rpm",
) -> bool:
    """Store package's content (SOURCES, SPECS, SRPM_CONTENT) in output_dir."""
    if package_type not in SUPPORTED_PACKAGE_TYPES:
        raise ValueError(f"Unsupported package type: {package_type}")

    if package_type == "rpm":
        source_package = RPMSourcepackage(package_name=package_name)
        return source_package.store_package_content(output_dir=output_dir)

    return False


def match_package_archives(
    package_name: str,
    input_archives_json_path: Optional[str] = None,
    output_json_path: Optional[str] = None,
    package_type: str = "rpm",
) -> bool:
    """
    Match all archives from the source package of a given package against suggested remote archives.
    """

    if package_type not in SUPPORTED_PACKAGE_TYPES:
        raise ValueError(f"Unsupported package type: {package_type}")

    if package_type == "rpm":
        source_package = RPMSourcepackage(package_name)

    if input_archives_json_path is None:
        log.info(
            "No input JSON provided, will automatically generate archive suggestions for package %s",
            package_name,
        )

        suggestion_result = get_remote_archives_for_package(
            package_name=package_name,
            package_type=package_type,
        )

        unused_spec_sources = suggestion_result.unused_spec_sources
        suggested_archives = suggestion_result.suggestions
    else:
        log.info(
            "Loading archive suggestions for package %s from %s",
            package_name,
            input_archives_json_path,
        )

        with open(input_archives_json_path, "r", encoding="utf-8") as f:
            archives_data = json.load(f)

        if "suggestions" not in archives_data:
            raise ValueError(f"{input_archives_json_path} file must contain 'suggestions' key")

        unused_spec_sources = archives_data["unused_spec_sources"]
        suggested_archives = archives_data["suggestions"]
        for sugg_list in suggested_archives.values():
            for idx, sugg in enumerate(sugg_list):
                if isinstance(sugg, dict):
                    sugg_list[idx] = RemoteArchiveSuggestion(**sugg)

    match_result = source_package.match_remote_archives(suggested_archives, unused_spec_sources)
    log.info(
        "Matched package %s with result %r, processing %d archives",
        package_name,
        match_result.matching,
        len(match_result.results),
    )

    if output_json_path:
        match_result.write_json_output(output_json_path)

    return match_result.matching


def match_package_repos(
    package_name: str,
    input_repos_json_path: Optional[str] = None,
    output_json_path: Optional[str] = None,
    package_type: str = "rpm",
    autotools_dir: Optional[str] = None,
    apply_autotools: bool = True,
) -> bool:
    """
    Match all archives from the source package of a given package against suggested remote
    repositories (currently only git repos are supported).
    """

    if package_type not in SUPPORTED_PACKAGE_TYPES:
        raise ValueError(f"Unsupported package type: {package_type}")

    if package_type == "rpm":
        source_package = RPMSourcepackage(package_name)

    if input_repos_json_path is None:
        log.info(
            "No input JSON provided, will automatically generate repo suggestions for package %s",
            package_name,
        )

        suggestion_result = get_repos_for_package(
            package_name=package_name,
            package_type=package_type,
        )

        suggested_repos = suggestion_result.suggestions
    else:
        log.info(
            "Loading repo suggestions for package %s from %s", package_name, input_repos_json_path
        )

        with open(input_repos_json_path, "r", encoding="utf-8") as f:
            repos_data = json.load(f)

        if "suggestions" not in repos_data:
            raise ValueError(f"{input_repos_json_path} file must contain 'suggestions' key")

        suggested_repos = repos_data["suggestions"]
        for sugg_list in suggested_repos.values():
            for idx, sugg in enumerate(sugg_list):
                if isinstance(sugg, dict):
                    sugg_list[idx] = RemoteRepoSuggestion(**sugg)

    match_result = source_package.match_remote_repos(
        suggested_repos,
        autotools_dir=autotools_dir,
        apply_autotools=apply_autotools,
    )

    log.info(
        "Matched repos of package %s with result %r, processing %d archives",
        package_name,
        match_result.matching,
        len(match_result.results),
    )

    if output_json_path:
        match_result.write_json_output(output_json_path)

    return match_result.matching


@dataclass
class PackageValidationResult(JsonSerializableMixin):
    """Result of validating a single package."""

    package_name: str
    source_package_name: str
    package_details: Optional[Dict[str, str]]

    archive_hashes: Dict[str, str]

    suggested_remote_archives: Dict[str, List[RemoteArchiveSuggestion]]
    suggested_remote_repos: Dict[str, List[RemoteRepoSuggestion]]
    matched_remote_archives: Dict[str, List[RemoteArchiveResult]]
    matched_remote_repos: Dict[str, List[RemoteRepoResult]]

    upstream_code_repos: Dict[str, Optional[str]]
    upstream_archives: Dict[str, Optional[str]]

    srpm_available: bool
    spec_valid: bool
    source_extractable: bool

    valid_archives: bool
    valid_repos: bool
    valid: bool

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SystemValidationResult(JsonSerializableMixin):
    """Result of analyzing all system packages."""

    report: Dict[str, PackageValidationResult]
    version: str = "2025-09-22"


def validate_single_package(
    package_name: str,
    srpm_file: Optional[str] = None,
    package_type: str = "rpm",
    install_build_deps: InstallationDecision = InstallationDecision.NO,
    autotools_dir: Optional[str] = None,
    apply_autotools: bool = True,
) -> PackageValidationResult:
    """Analyze a single package and return the PackageValidationResult."""

    assert package_type in SUPPORTED_PACKAGE_TYPES

    if package_type == "rpm":
        source_package = RPMSourcepackage(
            package_name, srpm_file=srpm_file, install_build_deps=install_build_deps
        )
    else:
        raise ValueError(f"Unsupported package type: {package_type}")

    source_package_name = source_package.get_name()
    if source_package_name is None:
        raise ValueError("Unable to determine source package name")

    log.debug("Processing package %s", package_name)

    # find and match remote archives (tarballs)
    suggested_remote_archives = get_remote_archives_for_package(
        package_name=package_name,
        package_type=package_type,
    )

    matched_remote_archives = source_package.match_remote_archives(
        suggested_remote_archives.suggestions, suggested_remote_archives.unused_spec_sources
    )

    # find and match remote code repositories
    suggested_remote_repos = get_repos_for_package(
        package_name=package_name,
        package_type=package_type,
    )

    matched_remote_repos = source_package.match_remote_repos(
        suggested_remote_repos.suggestions,
        autotools_dir=autotools_dir,
        apply_autotools=apply_autotools,
    )

    # choose highest-confidence, file-matching remote archive for each archive in the package
    upstream_archives = {}
    for archive in matched_remote_archives.archive_hashes:
        archive_results = matched_remote_archives.results[archive]
        matching_archives = [result.remote_archive for result in archive_results if result.matched]

        suggested_archives = suggested_remote_archives.suggestions[archive]
        filtered_suggestions = [
            suggestion
            for suggestion in suggested_archives
            if suggestion.remote_archive in matching_archives
        ]

        found_archive = None
        if filtered_suggestions:
            filtered_suggestions.sort(key=lambda x: x.confidence, reverse=True)
            found_archive = filtered_suggestions[0].remote_archive

        upstream_archives[archive] = found_archive

    # choose highest-confidence, file-matching code repo for each archive in the package
    upstream_code_repos = {}
    for archive in matched_remote_repos.archive_hashes:
        repo_results = matched_remote_repos.results[archive]
        matching_repos = [result.remote_repo for result in repo_results if result.matched]

        suggested_repos = suggested_remote_repos.suggestions[archive]
        filtered_suggestions = [
            suggestion for suggestion in suggested_repos if suggestion.repo in matching_repos
        ]

        found_repo = None
        if filtered_suggestions:
            filtered_suggestions.sort(key=lambda x: x.confidence, reverse=True)
            found_repo = filtered_suggestions[0].repo

        upstream_code_repos[archive] = found_repo

    # report both results (matching archives and matching repos) in a single JSON object
    return PackageValidationResult(
        package_name=package_name,
        source_package_name=source_package_name,
        archive_hashes=matched_remote_repos.archive_hashes,
        suggested_remote_archives=suggested_remote_archives.suggestions,
        suggested_remote_repos=suggested_remote_repos.suggestions,
        matched_remote_archives=matched_remote_archives.results,
        matched_remote_repos=matched_remote_repos.results,
        upstream_code_repos=upstream_code_repos,
        upstream_archives=upstream_archives,
        package_details=None,
        srpm_available=matched_remote_repos.srpm_available,
        spec_valid=matched_remote_repos.spec_valid,
        source_extractable=matched_remote_repos.source_extractable,
        valid_archives=matched_remote_archives.matching,
        valid_repos=matched_remote_repos.matching,
        valid=matched_remote_archives.matching and matched_remote_repos.matching,
    )


def validate_package(
    package: str,
    srpm_file: Optional[str] = None,
    package_type: str = "rpm",
    output_json_path: Optional[str] = None,
    install_build_deps: InstallationDecision = InstallationDecision.NO,
    autotools_dir: Optional[str] = None,
    apply_autotools: bool = True,
) -> bool:
    """Run analysis on a single package, and write report."""

    if package_type not in SUPPORTED_PACKAGE_TYPES:
        raise ValueError(f"Unsupported package type: {package_type}")

    package_validation_result = validate_single_package(
        package,
        srpm_file=srpm_file,
        install_build_deps=install_build_deps,
        autotools_dir=autotools_dir,
        apply_autotools=apply_autotools,
    )

    if output_json_path:
        log.info("Writing package validation report to %s", output_json_path)
        package_validation_result.write_json_output(output_json_path)

    return package_validation_result.valid


def validate_system_packages(
    package_type: str = "rpm",
    nr_packages_to_check: Optional[int] = None,
    output_json_path: Optional[str] = None,
    nr_processes: Optional[int] = None,
    extra_packages: Optional[List[str]] = None,
    autotools_dir: Optional[str] = None,
    apply_autotools: bool = True,
) -> bool:
    """Run analysis on all (latest) packages on system, and write report."""

    if package_type not in SUPPORTED_PACKAGE_TYPES:
        raise ValueError(f"Unsupported package type: {package_type}")

    system_packages = all_system_packages()
    extra_set = set()
    # prepend extra packages and remove duplicates
    if extra_packages:
        extra_set = set(extra_packages)
        combined_packages = list(extra_set.union(set(system_packages)))
        # ensure extra packages are at the beginning of the list
        combined_packages.sort(key=lambda x: x not in extra_set)
    else:
        combined_packages = system_packages
    combined_packages[len(extra_set) :] = random.sample(
        combined_packages[len(extra_set) :], len(combined_packages) - len(extra_set)
    )

    if nr_packages_to_check is not None:
        log.info(
            "Limiting analysis to %d packages (before: %d)",
            nr_packages_to_check,
            len(combined_packages),
        )
        combined_packages = combined_packages[:nr_packages_to_check]

    if nr_processes is None:
        nr_processes = os.cpu_count() or 1
    cpu_count = os.cpu_count() or 1
    nr_processes = max(1, min(nr_processes, cpu_count))
    log.info("Run validation with %d processes", nr_processes)

    package_data: Dict[str, PackageValidationResult] = {}
    package_stats: Dict[str, int] = {
        "total": 0,
        "valid": 0,
        "invalid": 0,
        "unavailable_srpm": 0,
        "spec_invalid": 0,
    }

    all_packages_valid = True
    try:
        with mp.Pool(processes=nr_processes) as pool:
            # Create a partial function with the additional parameters
            validate_func = partial(
                validate_single_package,
                autotools_dir=autotools_dir,
                apply_autotools=apply_autotools,
            )
            results = pool.map(validate_func, combined_packages)

            log.debug("Obtained %d results", len(results))
            for package_validation_result in results:
                package_name = package_validation_result.package_name
                package_data[package_name] = package_validation_result

                package_stats["total"] += 1
                package_stats["valid"] += 1 if package_validation_result.valid else 0
                package_stats["invalid"] += 0 if package_validation_result.valid else 1
                if not package_validation_result.srpm_available:
                    package_stats["unavailable_srpm"] += 1
                if not package_validation_result.spec_valid:
                    package_stats["spec_invalid"] += 1

                if package_stats["total"] % 100 == 0:
                    log.info(
                        "Processed %d packages (%d valid, %d invalid)",
                        package_stats["total"],
                        package_stats["valid"],
                        package_stats["invalid"],
                    )

            all_packages_valid = all(result.valid for result in package_data.values())
    except Exception:
        log.exception("Received an error, aborting")
        all_packages_valid = False

    log.info("Package analysis results: %s", package_stats)

    system_report = SystemValidationResult(report=package_data)

    if output_json_path:
        log.info("Writing system validation report to %s", output_json_path)
        system_report.write_json_output(output_json_path)

    return all_packages_valid
