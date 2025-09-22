# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Module to handle RPM spec files.
"""

import logging
import os
import re
from typing import Dict, List

from package_validation_tool.package.rpm.utils import (
    parse_rpm_spec_file,
    return_source_entries,
    rpmspec_present,
)
from package_validation_tool.utils import lines_starting_with

log = logging.getLogger(__name__)


class RPMSpecError(Exception):
    """Exception to indicate spec file parsing error."""


class RPMSpec:
    """Process an RPM spec file and return properties of that file."""

    def __init__(self, spec_file, fallback_plain_rpm=False):
        # note that some fields have "__" suffix, to ignore them in the cached object (as they have
        # temporary directories in their values)
        self.spec_file_abs__ = os.path.abspath(spec_file)
        self.spec_file = os.path.basename(spec_file)

        if not rpmspec_present():
            if fallback_plain_rpm:
                log.warning(
                    "YOUR RESULTS MIGHT BE WRONG. rpmspec not found in environment, working with the plain RPM specfile."
                )
            else:
                raise RuntimeError("rpmspec not found in environment")

        # parse and normalize spec file: a parsed spec may contain expanded macros with paths
        # containing `tmp/unique-id/` (see parse_rpm_spec_file() for details on how these paths are
        # generated from HOME envvar), replace such paths with a hard-coded dummy
        spec_content = parse_rpm_spec_file(self.spec_file_abs__, fallback_plain_rpm)
        if spec_content is None:
            raise RPMSpecError(f"Failed parsing spec file {self.spec_file_abs__}")
        path_split = self.spec_file_abs__.split(os.sep)
        if len(path_split) >= 3 and path_split[-3] == "rpmbuild" and path_split[-2] == "SPECS":
            path_to_replace = os.path.join(*path_split[:-3])
            spec_content = spec_content.replace(path_to_replace, "dummydir")
        self._spec_content_lines = spec_content.splitlines()
        log.debug("Found %d lines in specfile %s", len(self._spec_content_lines), self.spec_file)

        self._name = None
        self._version = None
        self._source_entries = None
        self._parse_problems = []
        self.package_name()
        self.package_version()

    def package_version(self) -> str:
        """Return version of package"""
        if self._version:
            return self._version
        version_lines = lines_starting_with(self._spec_content_lines, "Version:")
        if not version_lines:
            raise RPMSpecError(f"No version line found in spec file {self.spec_file}")
        extracted_version = ":".join(sorted(version_lines)[0].split(":")[1:]).strip()
        if len(version_lines) != 1:
            warning = f"Failed to detect a single version line in spec file in {self.spec_file} (first version: '{extracted_version}' from {len(version_lines)} lines)"
            self._parse_problems.append(warning)
            log.warning("%s", warning)
        self._version = extracted_version
        log.debug("Extracted version: %s", self._version)
        return self._version

    def package_name(self) -> str:
        """Return name of package"""
        if self._name:
            return self._name
        name_lines = lines_starting_with(self._spec_content_lines, "Name:")
        if not name_lines:
            raise RPMSpecError(f"No name line found in spec file {self.spec_file}")
        if len(name_lines) != 1:
            raise RPMSpecError(f"Several name lines found in spec file {self.spec_file}")
        self._name = name_lines[0].split(":")[1].strip()
        log.debug("Extracted name: %s", self._name)
        return self._name

    def source_entries(self) -> Dict[str, str]:
        """Return all source lines, i.e. Source[0-9]*:"""
        if self._source_entries:
            return self._source_entries
        self._source_entries = return_source_entries(self._spec_content_lines)
        return self._source_entries

    def repourl_entries(self) -> List[str]:
        """Return all repo-address-looking URLs from lines in the RPM spec file."""
        # regex notes: `?:` marks a non-capturing group; git/http/https must be followed by "://"; the
        # URL ends on any of the whitespace chars, angle brackets, question mark, single/double
        # quotes or parentheses (good matches: "https://github.com/repo", "git://source.org/proj")
        url_pattern = re.compile(r'((?:GIT|HTTP|HTTPS)://[^\s<>\?"\'()]+)', re.IGNORECASE)
        extracted_urls = []
        for line in self._spec_content_lines:
            matches = url_pattern.findall(line)
            extracted_urls.extend(matches)
        return extracted_urls
