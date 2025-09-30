# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Module to match directories or files.
"""

import logging
import os
import random
import re
import shutil
import tempfile
from enum import Enum
from typing import Dict, List

from package_validation_tool.common import (
    BINARY_FILE_TYPES,
    RANDOM_STRING_BASE_CHARACTERS,
    SUPPORTED_ARCHIVE_TYPES,
)
from package_validation_tool.utils import pushd, read_file_as_utf8, save_path, secure_unpack_archive

log = logging.getLogger(__name__)


def generate_random_string(length: int = 20) -> str:
    """Return a random string of a given length"""
    return "".join(random.choice(RANDOM_STRING_BASE_CHARACTERS) for _ in range(length))


def compare_strings_ignore_date_numbers(left_str: str, right_str: str) -> bool:
    """Return whether strings are equal, if common date formats are ignored."""

    # return fast, if there are no dates
    if left_str == right_str:
        return True

    # define regular expression patterns to match different date formats
    date_patterns = [
        r"\d{1,2}/\d{1,2}/\d{4}",  # MM/DD/YYYY
        r"\d{1,2}-\d{1,2}-\d{4}",  # MM-DD-YYYY
        r"\d{4}/\d{1,2}/\d{1,2}",  # YYYY/MM/DD
        r"\d{4}-\d{1,2}-\d{1,2}",  # YYYY-MM-DD
    ]

    date_replace_pattern = generate_random_string(20)

    # replace all dates and years with placeholders in both strings
    left_nodate = re.sub(r"|".join(date_patterns), date_replace_pattern, left_str)
    right_nodate = re.sub(r"|".join(date_patterns), date_replace_pattern, right_str)

    # compare the cleaned strings
    return left_nodate == right_nodate


class FileMatchState(Enum):
    """State of a file comparison/explanation."""

    MATCHING = 1  # The entity has a matching counterpart
    NO_COUNTERPART = 2  # There is no matching counterpart present
    DIFFERENT = 3  # There is a matching counterpart, but the two differ


class FileMatcher:
    """
    Compare files/directory to another file/directory, and find a matching file recursively.
    Archives will be processed recursively, so that an archive can be matched against a archive
    that contains a superset of the files.
    """

    def __init__(self, cleanup: bool = True):
        self.state_dict: Dict[str, FileMatchState] = {}
        self.temporary_directories: List[str] = []
        self.cleanup: bool = cleanup

    def __del__(self):
        self._cleanup_tmp_directories()

    def _import_from(self, file_matcher):
        """Extend current state from given comparer."""
        self.state_dict = file_matcher.state_dict.copy()
        self.temporary_directories.extend(file_matcher.temporary_directories)

    def _cleanup_tmp_directories(self):
        """Remove the temporary directories we tracked until now."""
        for temporary_item in self.temporary_directories:
            if os.path.exists(temporary_item) and os.path.isdir(temporary_item):
                shutil.rmtree(temporary_item, ignore_errors=True)
        self.temporary_directories = []

    def _extract_archive(self, archive_path: str) -> str:
        """Extract an archive, return the temporary named directory object, and keep track in object for cleanup."""
        temp_dir = tempfile.mkdtemp(
            prefix="package-matcher-",
            suffix=f"-{save_path(os.path.basename(archive_path))}",
        )
        self.temporary_directories.append(temp_dir)

        try:
            log.debug("Extract archive %s into directory %s ...", archive_path, temp_dir)
            if not secure_unpack_archive(archive_path, temp_dir):
                log.error("Failed to securely extract archive %s", archive_path)
                raise RuntimeError(f"Secure extraction failed for {archive_path}")
            log.info("Archive extracted to: %s", temp_dir)
            return temp_dir

        except Exception as e:
            log.debug("Extracting archive %s failed with exception %r", archive_path, e)
            raise e

    def left_is_matching(self) -> bool:
        """Return True, if all files in the left comparisons can be matched by the files in the right"""
        for state in self.state_dict.values():
            if state != FileMatchState.MATCHING:
                return False
        return True

    def print_state(self, non_matching_only: bool = True, prefix: str = ""):
        for file_path, state in self.state_dict.items():
            if non_matching_only and state == FileMatchState.MATCHING:
                continue
            print(f"{prefix}{file_path}: {state.name}")

    def get_unmatching_files(self) -> list:
        unmatching_files = []
        for file_path, state in self.state_dict.items():
            if state != FileMatchState.MATCHING:
                unmatching_files.append(file_path)
        return unmatching_files

    def get_nr_processed_files(self) -> int:
        return len(self.state_dict.keys())

    def _compare_archives(self, left_path: str, right_path: str) -> FileMatchState:
        """Compare whether two archives have the same content."""

        log.debug("Matching archive file %s with %s ...", left_path, right_path)
        fail_extract_left = False
        fail_extract_right = False
        try:
            left_extract_dir = self._extract_archive(left_path)
        except Exception:
            fail_extract_left = True
        try:
            right_extract_dir = self._extract_archive(right_path)
        except Exception:
            fail_extract_right = True

        if fail_extract_left and fail_extract_right:
            log.debug("Both archives failed to extract, compare binary files")
            return self._compare_binary_files(left_path, right_path)
        elif fail_extract_left != fail_extract_right:
            log.debug("One archive failed to extract, mark comparison as different")
            return FileMatchState.DIFFERENT

        # recursively match the content of the archive, allowing for matching subset of files
        file_matcher = FileMatcher(cleanup=self.cleanup)
        log.debug(
            "Match extracted archives %s with %s ...",
            left_extract_dir,
            right_extract_dir,
        )
        file_matcher.match_left(left_extract_dir, right_extract_dir)
        if file_matcher.left_is_matching():
            return FileMatchState.MATCHING
        else:
            return FileMatchState.DIFFERENT

    def _match_left_files(self, left_path: str, right_path: str) -> FileMatchState:
        """Return matching of two given files, check entire content."""

        if not os.path.exists(left_path):
            raise ValueError(f"Specified path does not exist: {left_path}")

        if not os.path.exists(right_path):
            self.state_dict[left_path] = FileMatchState.NO_COUNTERPART
            return self.state_dict[left_path]

        if os.path.isdir(left_path) != os.path.isdir(right_path):
            self.state_dict[left_path] = FileMatchState.DIFFERENT
            return self.state_dict[left_path]

        # handle archives before comparing the files ourselves
        if left_path.endswith(SUPPORTED_ARCHIVE_TYPES):
            bin_result = self._compare_binary_files(left_path=left_path, right_path=right_path)
            if bin_result == FileMatchState.MATCHING:
                self.state_dict[left_path] = bin_result
                return bin_result
            self.state_dict[left_path] = self._compare_archives(left_path, right_path)
            return self.state_dict[left_path]

        # check whether we deal with other known binary files
        if not left_path.endswith(BINARY_FILE_TYPES):
            left_content = read_file_as_utf8(left_path)
            right_content = read_file_as_utf8(right_path)

            if compare_strings_ignore_date_numbers(left_content, right_content):
                self.state_dict[left_path] = FileMatchState.MATCHING
            else:
                self.state_dict[left_path] = FileMatchState.DIFFERENT
            return self.state_dict[left_path]

        return self._compare_binary_files(left_path=left_path, right_path=right_path)

    def _compare_binary_files(self, left_path: str, right_path: str) -> FileMatchState:
        with open(left_path, "rb") as left_file, open(right_path, "rb") as right_file:
            left_content = left_file.read()
            right_content = right_file.read()

        if left_content == right_content:
            self.state_dict[left_path] = FileMatchState.MATCHING
        else:
            self.state_dict[left_path] = FileMatchState.DIFFERENT
        return self.state_dict[left_path]

    def match_left(self, left: str, right: str):
        """Match file/directory left, and try to find matching file in file/directory right."""
        left = os.path.abspath(left)
        right = os.path.abspath(right)

        if not os.path.exists(left):
            raise ValueError(f"Specified path {left} does not exist")

        # is file, just compare files
        if os.path.isfile(left):
            self._match_left_files(left, right)
            return

        # use relative path from left directory, to be able to use relative paths everywhere
        log.debug("Run comparison from directory %s", left)
        with pushd(left):

            for root, _, files in os.walk(left):
                rel_path = os.path.relpath(root, left)
                right_root = os.path.join(right, rel_path)

                for file in files:
                    left_path = os.path.join(root, file)
                    right_path = os.path.join(right_root, file)
                    self._match_left_files(left_path, right_path)


def match_files(left: str, right: str, cleanup=True) -> bool:
    """
    Match files in the left directory/file based on the right directory/file.
    Any file present in left needs to be present in right, recursively for archives as well.
    """
    file_matcher = FileMatcher(cleanup=cleanup)
    file_matcher.match_left(left, right)
    file_matcher.print_state()
    return file_matcher.left_is_matching()
