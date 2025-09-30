# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import difflib
import logging
import os
import re
import subprocess
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from package_validation_tool.matching.file_matching import SUPPORTED_ARCHIVE_TYPES

log = logging.getLogger(__name__)

VersionInfo = namedtuple("VersionInfo", ["version", "date", "suffix", "is_commit_hash"])


@dataclass
class TagInfo:
    """Class for storing information about a git tag."""

    original_tag: str  # Original tag from git output (e.g., "v2.3.1")
    commit_hash: str  # Commit hash associated with the tag
    normalized_tag: str  # Lowercase tag with dots replaced by underscores
    release_tag: bool = False  # Whether this is a release tag
    simplified_tag: str = ""  # Normalized tag with all separators removed


# currently considers date_str a valid date only if it is in format "YYYYMMDD"
def is_valid_date_format(date_str: str) -> bool:
    if not (len(date_str) == 8 and date_str.isdigit()):
        return False

    try:
        year, month, day = int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8])
        datetime(year, month, day)  # datetime validates thoroughly (handles leap years, etc.)
        return True
    except ValueError:
        # this catches invalid dates like February 30
        return False


def is_commit_hash(hash_str: str) -> bool:
    if len(hash_str) < 6 or len(hash_str) > 40:
        return False

    # Check if all characters are hexadecimal
    hex_chars_only = all(c in "0123456789abcdef" for c in hash_str)

    # Check if at least one char is a letter (a-f); otherwise it's better classified as a version/tag
    # For example, "sqlite-autoconf-3400000.tar.gz" has a version (without dots), not a commit hash
    has_alpha = any(c in "abcdef" for c in hash_str)

    return hex_chars_only and has_alpha


def is_version(version_str: str) -> bool:
    if not version_str:
        return False

    # Check if string starts with a digit (e.g., 2.3.4)
    if version_str[0].isdigit():
        return True

    # Check if string starts with 'v' or 'r' followed by a digit (e.g., v2.3.4 or r2.3.4)
    if version_str.startswith(("v", "r")) and len(version_str) > 1 and version_str[1].isdigit():
        return True

    # If none of the conditions are met, it's not a version
    return False


# tag must be lower-cased already and contains `_` instead of `.`
def is_release_tag(tag: str) -> bool:
    # pattern below looks for any of the "non-release" keywords, with word boundaries
    if re.search(r"\b(dev|devel|candidate|prerelease|alpha|beta|gamma|delta|pre|docs)\b", tag):
        return False

    # pattern below looks for "rc" or "pre" followed by one or more digits, with word boundaries
    if re.search(r"\b(rc|pre)\d+\b", tag):
        return False

    # pattern below looks for "rc" or "pre" followed by one or more digits, with a digit beforehand
    # (e.g. "v2_1_0rc1")
    if re.search(r"\d+(rc|pre)\d+\b", tag):
        return False

    # glibc tag naming convention, see https://sourceware.org/glibc/wiki/GlibcGit#Tag_Conventions
    if re.search(r"\d+_\d+_\d+_\d{8}\b", tag) or re.search(r"\d+_\d+_9000\b", tag):
        return False

    # If none of the above conditions are met, it's a release tag
    return True


def find_best_matching_tag(archive: str, tags: List[TagInfo]) -> Optional[TagInfo]:
    """
    Find the tag that best matches the archive name.

    Args:
        archive (str): Archive name to match against
        tags (List[TagInfo]): List of TagInfo objects to search through

    Returns:
        Optional[TagInfo]: The best matching TagInfo object, or None if no matches
    """
    if not tags:
        return None

    if len(tags) == 1:
        return tags[0]

    log.warning("Multiple tags found for %s: %r", archive, [tag.original_tag for tag in tags])

    best_score = -1.0
    best_tag = None

    for tag_info in tags:
        similarity = difflib.SequenceMatcher(None, archive, tag_info.normalized_tag).ratio()
        if similarity > best_score:
            best_score = similarity
            best_tag = tag_info

    return best_tag


def extract_version_from_archive_name(source_archive: str) -> VersionInfo:
    """
    Extract and normalize version from archive name.

    Args:
        source_archive: Archive name string (e.g., "acl-2.3.1.tar.gz")

    Returns:
        A VersionInfo namedtuple containing:
            - version: The main version string (normalized, e.g. "2_3_1")
            - date: A date component of the version (if present)
            - suffix: A suffix component of the version (if present)
            - is_commit_hash: True if version is a commit hash instead of a proper version

    Raises:
        ValueError: If no version could be extracted from the archive name
    """
    version = ""
    version_date = ""
    version_suffix = ""
    version_is_commit_hash = False

    # Step 1: Remove archive extension and lower-case
    archive_name = source_archive.lower()
    for ext in SUPPORTED_ARCHIVE_TYPES:
        if archive_name.endswith(ext):
            archive_name = archive_name[: -len(ext)]
            break

    # Step 2: Process the string to find the version
    while True:
        # Step 2.a: Find last '-' symbol
        last_dash_pos = archive_name.rfind("-")

        if last_dash_pos == -1:
            # Step 2.a.i: If no dash, check for underscore
            last_underscore_pos = archive_name.rfind("_")
            if last_underscore_pos != -1:
                # Replace underscore with dash and continue
                archive_name = (
                    archive_name[:last_underscore_pos]
                    + "-"
                    + archive_name[last_underscore_pos + 1 :]
                )
                continue
            else:
                # Step 2.a.ii: Assume the whole string is a version
                version = archive_name
                break
        else:
            # Step 2.b: Process substring after the last dash
            potential_version = archive_name[last_dash_pos + 1 :]

            # Step 2.b.i: Check if it's a date in YYYYMMDD format
            if is_valid_date_format(potential_version):
                version_date = potential_version
                archive_name = archive_name[:last_dash_pos]
                continue

            # Step 2.b.ii: Check if it's a commit hash (hexadecimal with at least 6 symbols)
            if is_commit_hash(potential_version):
                version_is_commit_hash = True
                version = potential_version
                break

            # Step 2.b.iii: Check if it looks like a version
            if is_version(potential_version):
                # It's a version, done
                version = potential_version
                break

            # Step 2.b.iv: Not a version, save as suffix
            version_suffix = potential_version
            archive_name = archive_name[:last_dash_pos]
            continue

    if not version:
        raise ValueError(f"Could not extract version from {source_archive}")

    # Step 3: Normalize version string
    if version.startswith(("v", "r")):
        version = version[1:]
    version = version.replace(".", "_").replace("-", "_")

    # Step 4: Corner case, used in e.g. OpenSSH Portable versioning (e.g. `8.7p1`)
    pattern = r"(.+?)p(\d+)$"  # pattern to match any characters before 'p' followed by digits
    match = re.match(pattern, version)
    if match:
        version = match.group(1)
        version_suffix = match.group(2)

    return VersionInfo(
        version=version,
        date=version_date,
        suffix=version_suffix,
        is_commit_hash=version_is_commit_hash,
    )


def verify_commit_exists(repo_dir: str, commit_hash: str) -> str:
    """
    Verify if a specific commit exists in a git repository.

    Args:
        repo_dir (str): Path to the git repository directory
        commit_hash (str): Commit hash to verify

    Returns:
        str: The full commit hash if it exists, or an empty string if not found
    """
    if not repo_dir or not os.path.exists(repo_dir):
        log.debug("Repository directory %s does not exist", repo_dir)
        return ""

    # Check if the commit exists
    try:
        rev_parse_cmd = ["git", "rev-parse", "--verify", commit_hash]
        result = subprocess.run(
            rev_parse_cmd,
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,  # raise CalledProcessError if command fails (commit hash does not exist)
        )
        # Return the full commit hash
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        log.debug("Commit %s not found in repository directory %s", commit_hash, repo_dir)
        return ""


def verify_tag_exists(
    archive: str, repo_dir: str, version: str, version_date: str = "", version_suffix: str = ""
) -> Tuple[str, str]:
    """
    Find a git repository tag that corresponds to the given version.

    Args:
        archive (str): basename of source archive; used when multiple matching tags are found
        repo_dir (str): Path to the local git repository directory
        version (str): Version to search for
        version_date (str): Helper date string
        version_suffix (str): Helper suffix string

    Returns:
        Tuple[str, str]: A tuple containing:
            - The git commit hash corresponding to the tag (empty string if not found)
            - The git repository tag that corresponds to the version (empty string if not found)
    """

    # remove extension, otherwise matching algo may be confused by letters and dots in extension
    # (e.g. for `zlib-1.2.7.tar.bz2` algo would choose `1.2.7.1` instead of `1.2.7` because of the
    # matching third dot in `1.2.7.1`)
    for ext in SUPPORTED_ARCHIVE_TYPES:
        if archive.endswith(ext):
            archive = archive[: -len(ext)]
            break

    def _handle_matching_tags(matching_tags: List[TagInfo]) -> Optional[Tuple[str, str]]:
        if not matching_tags:
            return None

        if len(matching_tags) == 1:
            return matching_tags[0].commit_hash, matching_tags[0].original_tag

        best_tag = find_best_matching_tag(archive, matching_tags)
        if best_tag is None:
            return None
        return best_tag.commit_hash, best_tag.original_tag

    # Fetch all tags from the repository
    cmd = ["git", "tag", "--list", "--format=%(objectname) %(refname:short)"]
    try:
        git_tag_list_result = subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=repo_dir
        )
    except subprocess.CalledProcessError as e:
        log.error("Failed to fetch tags from repository directory %s: %s", repo_dir, e)
        return "", ""

    # Split the output into lines
    lines = git_tag_list_result.stdout.strip().split("\n")
    if not lines or lines[0] == "":
        log.warning("No tags found in repository directory %s", repo_dir)
        return "", ""

    # Create TagInfo objects from git output
    tags = []
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue

        commit_hash = parts[0]
        original_tag = parts[1]
        normalized_tag = original_tag.lower().strip().replace(".", "_")

        tag_info = TagInfo(
            original_tag=original_tag,
            commit_hash=commit_hash,
            normalized_tag=normalized_tag,
            release_tag=False,
        )
        tags.append(tag_info)

    # Mark release tags and normalize them further
    for tag in tags:
        if is_release_tag(tag.normalized_tag):
            tag.release_tag = True
            # Replace dashes with underscores after release tag filtering
            # (important because '_' is not considered a word boundary in regex patterns)
            tag.normalized_tag = tag.normalized_tag.replace("-", "_")
            # Create simplified tag (remove all '_' symbols)
            tag.simplified_tag = tag.normalized_tag.replace("_", "")

    # Filter to include only release tags
    release_tags = [tag for tag in tags if tag.release_tag]

    # Try to find a tag corresponding to the version using different matching strategies

    # a. Check for version, version_date, and version_suffix
    if version_date and version_suffix:
        matching_tags = [
            tag
            for tag in release_tags
            if version in tag.normalized_tag
            and version_date in tag.normalized_tag
            and version_suffix in tag.normalized_tag
        ]

        result = _handle_matching_tags(matching_tags)
        if result:
            return result

    # b. Check for version and version_date
    if version_date:
        matching_tags = [
            tag
            for tag in release_tags
            if version in tag.normalized_tag and version_date in tag.normalized_tag
        ]

        result = _handle_matching_tags(matching_tags)
        if result:
            return result

    # c. Check for version and version_suffix
    if version_suffix:
        matching_tags = [
            tag
            for tag in release_tags
            if version in tag.normalized_tag and version_suffix in tag.normalized_tag
        ]

        result = _handle_matching_tags(matching_tags)
        if result:
            return result

    # d. Check for version only
    matching_tags = [tag for tag in release_tags if version in tag.normalized_tag]

    result = _handle_matching_tags(matching_tags)
    if result:
        return result

    # e. Special case for versions without separators (e.g. "sqlite-src-3400000.zip" -> "3.40.0")
    # Remove trailing zeros from version except one
    simplified_version = version
    if version.endswith("0"):
        simplified_version = version[: len(version.rstrip("0")) + 1]

    # Try to find a match with the simplified version
    matching_tags = [tag for tag in release_tags if simplified_version in tag.simplified_tag]

    result = _handle_matching_tags(matching_tags)
    if result:
        return result

    # f. No match found
    log.warning(
        "No matching tags found for %s (%r)", archive, [tag.original_tag for tag in release_tags]
    )
    return "", ""
