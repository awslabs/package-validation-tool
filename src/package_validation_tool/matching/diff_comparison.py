# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Module to compare diffs directories from two package validation runs."""

import difflib
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from package_validation_tool.package import JsonSerializableMixin
from package_validation_tool.utils import hash256sum

# Patterns for date normalization
DATE_PATTERNS = [
    # Spelled-out dates: January 02, 2023 / Apr 26, 2023
    re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October"
        r"|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2},?\s*\d{4}\b"
    ),
    # ISO dates: 2024-01-26, 2023-07-19
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    # Year ranges: 2020-2021, 2021-2024
    re.compile(r"\b(19|20)\d{2}-(19|20)\d{2}\b"),
    # Standalone years: 2024, 2023
    re.compile(r"\b(19|20)\d{2}\b"),
]


def _generate_placeholder() -> str:
    """Generate a random placeholder string to avoid injection attacks."""
    return f"__PLACEHOLDER_{secrets.token_hex(16)}__"


def _extract_version_from_path(path: str) -> Optional[str]:
    """Extract version string from a diffs directory path like 'xz-5.4.6.tar.gz'."""
    # Match patterns like package-1.2.3.tar.gz or package-1.2.3
    match = re.search(r"-(\d+\.\d+(?:\.\d+)*)(?:\.tar|\.zip|$)", path)
    return match.group(1) if match else None


log = logging.getLogger(__name__)


@dataclass
class ArchiveDiffComparison:
    """Comparison result for a single archive's diffs."""

    files_only_in_a: List[str] = field(default_factory=list)
    files_only_in_b: List[str] = field(default_factory=list)
    files_with_different_content: List[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        """Return True if no differences found."""
        return not (
            self.files_only_in_a or self.files_only_in_b or self.files_with_different_content
        )


@dataclass
class DiffComparisonResult(JsonSerializableMixin):
    """Result of comparing two diffs directories."""

    identical: bool
    package_name: str
    archives_compared: List[str] = field(default_factory=list)
    differences: Dict[str, ArchiveDiffComparison] = field(default_factory=dict)

    def __post_init__(self):
        """Reconstruct nested dataclass objects from dicts after cache restoration."""
        for archive, diff in list(self.differences.items()):
            if isinstance(diff, dict):
                self.differences[archive] = ArchiveDiffComparison(**diff)


def _get_diff_files(directory: Path) -> Dict[str, str]:
    """
    Get all .arch and .repo files in directory, returning dict of relative path -> absolute path.

    Only returns the base path (without .arch/.repo suffix) as key.
    """
    files = {}
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            if filename.endswith((".arch", ".repo")):
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, directory)
                # Remove .arch/.repo suffix for comparison key
                base_path = rel_path.rsplit(".", 1)[0]
                files[base_path] = abs_path
    return files


def _normalize_dates(content: str, placeholder: str) -> str:
    """Replace date patterns with placeholder for comparison."""
    for pattern in DATE_PATTERNS:
        content = pattern.sub(placeholder, content)
    return content


def _normalize_versions(content: str, versions: List[str], placeholder: str) -> str:
    """Replace version strings with placeholder for comparison."""
    for version in versions:
        if version:
            content = content.replace(version, placeholder)
    return content


def _read_and_normalize(
    file_path: str,
    normalize_dates: bool,
    versions: Optional[List[str]] = None,
    placeholder: str = "",
) -> str:
    """Read file content and optionally normalize dates and versions."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    if normalize_dates:
        content = _normalize_dates(content, placeholder)
    if versions:
        content = _normalize_versions(content, versions, placeholder)
    return content


def _compare_files(
    path_a: str,
    path_b: str,
    normalize_dates: bool,
    versions: Optional[List[str]] = None,
) -> bool:
    """Compare two files, return True if identical (after optional normalization)."""
    if not normalize_dates and not versions:
        return hash256sum(path_a) == hash256sum(path_b)
    # Use same random placeholder for both files in this comparison
    placeholder = _generate_placeholder()
    content_a = _read_and_normalize(path_a, normalize_dates, versions, placeholder)
    content_b = _read_and_normalize(path_b, normalize_dates, versions, placeholder)
    return content_a == content_b


def _write_diff(path_a: str, path_b: str, output_path: Path) -> None:
    """Write unified diff between two files to output_path."""
    with open(path_a, "r", encoding="utf-8", errors="replace") as f:
        lines_a = f.readlines()
    with open(path_b, "r", encoding="utf-8", errors="replace") as f:
        lines_b = f.readlines()
    diff = difflib.unified_diff(lines_a, lines_b, fromfile=path_a, tofile=path_b)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(diff)


def compare_diffs_directories(
    dir_a: str,
    dir_b: str,
    package_name: Optional[str] = None,
    output_json_path: Optional[str] = None,
    normalize_dates: bool = False,
    normalize_versions: bool = False,
    output_diffs: Optional[str] = None,
) -> bool:
    """
    Compare two diffs directories to check if package-to-upstream differences are identical.

    Args:
        dir_a: First diffs directory path
        dir_b: Second diffs directory path
        package_name: Optional package name to filter comparison
        output_json_path: Optional path to write JSON output
        normalize_dates: If True, ignore date differences when comparing
        normalize_versions: If True, ignore version string differences when comparing
        output_diffs: Optional directory to write diff-of-diffs for differing files

    Returns:
        True if diffs are identical, False otherwise
    """
    path_a = Path(dir_a)
    path_b = Path(dir_b)

    if not path_a.exists():
        log.error("Directory does not exist: %s", dir_a)
        return False
    if not path_b.exists():
        log.error("Directory does not exist: %s", dir_b)
        return False

    # If package_name specified, narrow to that subdirectory
    if package_name:
        path_a = path_a / package_name
        path_b = path_b / package_name

        if not path_a.exists():
            log.warning("Package directory does not exist in dir_a: %s", path_a)
        if not path_b.exists():
            log.warning("Package directory does not exist in dir_b: %s", path_b)

    # Get all diff files from both directories
    files_a = _get_diff_files(path_a) if path_a.exists() else {}
    files_b = _get_diff_files(path_b) if path_b.exists() else {}

    # Extract versions from directory paths for normalization
    versions: Optional[List[str]] = None
    if normalize_versions:
        version_a = _extract_version_from_path(dir_a)
        version_b = _extract_version_from_path(dir_b)
        versions = [v for v in [version_a, version_b] if v]
        if versions:
            log.info("Normalizing version strings: %s", versions)

    all_files = set(files_a.keys()) | set(files_b.keys())

    # Group files by archive
    archives: Dict[str, ArchiveDiffComparison] = {}

    for file_path in sorted(all_files):
        # Extract archive name from path (first component)
        parts = file_path.split(os.sep)
        archive_name = parts[0] if parts else "unknown"

        if archive_name not in archives:
            archives[archive_name] = ArchiveDiffComparison()

        in_a = file_path in files_a
        in_b = file_path in files_b

        if in_a and not in_b:
            archives[archive_name].files_only_in_a.append(file_path)
        elif in_b and not in_a:
            archives[archive_name].files_only_in_b.append(file_path)
        else:
            # Both exist, compare content
            if not _compare_files(
                files_a[file_path], files_b[file_path], normalize_dates, versions
            ):
                archives[archive_name].files_with_different_content.append(file_path)
                if output_diffs:
                    diff_path = Path(output_diffs) / f"{file_path}.diff"
                    _write_diff(files_a[file_path], files_b[file_path], diff_path)

    identical = all(diff.identical for diff in archives.values())

    result = DiffComparisonResult(
        identical=identical,
        package_name=package_name or "",
        archives_compared=list(archives.keys()),
        differences=archives,
    )

    log.info(
        "Compared %d archives, identical: %s",
        len(archives),
        identical,
    )

    if output_json_path:
        result.write_json_output(output_json_path)

    return identical
