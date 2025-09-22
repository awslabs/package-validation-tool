# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from package_validation_tool.package.rpm.spec import RPMSpec
from package_validation_tool.package.rpm.utils import (
    get_single_spec_file,
    parse_rpm_spec_file,
    rpmspec_present,
)

TEST_DIR_PATH = os.path.dirname(__file__)
TESTRPM_SPEC_FILE = Path(TEST_DIR_PATH) / "artefacts" / "rpm" / "testrpm.spec"
TESTRPM_WITH_URLS_SPEC_FILE = Path(TEST_DIR_PATH) / "artefacts" / "rpm" / "testrpm_with_urls.spec"


def test_rpmspec_present():
    """Test the rpmspec_present function."""
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/rpmspec"
        assert rpmspec_present()


def test_parse_rpm_spec_file_name():
    """Test whether we can parse the name from the spec file without macros."""
    rpm_spec = RPMSpec(spec_file=TESTRPM_SPEC_FILE, fallback_plain_rpm=True)
    assert rpm_spec.package_name() == "testrpm"


def test_parse_rpm_spec_file_version():
    """Test whether we can parse the version from the spec file without macros."""
    rpm_spec = RPMSpec(spec_file=TESTRPM_SPEC_FILE, fallback_plain_rpm=True)
    assert rpm_spec.package_version() == "0.1"


def test_parse_rpm_spec_file_failure():
    """Test the parse_rpm_spec_file function with an rpmspec failure."""
    spec_file = TESTRPM_SPEC_FILE
    with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "rpmspec")):
        assert parse_rpm_spec_file(spec_file, fallback_plain_rpm=True) is not None
        assert parse_rpm_spec_file(spec_file, fallback_plain_rpm=False) is None


def test_rpmspec_source_entries():
    """Test whether we managed to parse the source entries."""
    rpm_spec = RPMSpec(TESTRPM_SPEC_FILE, fallback_plain_rpm=True)
    assert len(rpm_spec.source_entries()) == 2


def test_get_single_spec_file():
    """Test the get_single_spec_file function."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        spec_file = temp_dir_path / "test.spec"
        shutil.copy(TESTRPM_SPEC_FILE, spec_file)

        assert get_single_spec_file(str(temp_dir_path)) == str(spec_file)


def test_get_single_spec_file_success():
    """Test the get_single_spec_file function with a single spec file"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        spec_file = temp_dir_path / "test.spec"
        spec_file.touch()

        assert get_single_spec_file(str(temp_dir_path)) == str(spec_file)


def test_get_single_spec_file_multiple_spec_files():
    """Test the get_single_spec_file function with multiple spec files"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        spec_file1 = temp_dir_path / "test1.spec"
        spec_file1.touch()
        spec_file2 = temp_dir_path / "test2.spec"
        spec_file2.touch()

        with pytest.raises(ValueError) as excinfo:
            get_single_spec_file(str(temp_dir_path))
        assert "Multiple spec files found in" in str(excinfo.value)


def test_get_single_spec_file_no_spec_files():
    """Test the get_single_spec_file function with no spec files"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)

        with pytest.raises(ValueError) as excinfo:
            get_single_spec_file(str(temp_dir_path))
        assert "No spec file found in" in str(excinfo.value)


def test_repourl_entries_basic():
    """Test the repourl_entries function with a spec file containing URLs."""
    rpm_spec = RPMSpec(TESTRPM_WITH_URLS_SPEC_FILE, fallback_plain_rpm=True)
    urls = rpm_spec.repourl_entries()

    # Check that we found the expected number of URLs
    assert len(urls) >= 10, f"Expected at least 10 URLs, found {len(urls)}"

    # Check for specific URLs from the spec file
    assert "GIT://github.com/example/testrpm.git" in urls
    assert "git://gitlab.com/example/testrpm.git" in urls
    assert "HTTPS://secure.example.com/downloads/testrpm" in urls
    assert "HTTP://downloads.example.com/packages/testrpm/testrpm-0.1.tar.gz" in urls
    assert "HTTP://downloads.example.com/packages/testrpm/testrpm-0.1.tar.gz.sig" in urls


def test_repourl_entries_url_in_comments():
    """Test that repourl_entries finds URLs in comments."""
    rpm_spec = RPMSpec(TESTRPM_WITH_URLS_SPEC_FILE, fallback_plain_rpm=True)
    urls = rpm_spec.repourl_entries()

    # Check for URLs that appear in comments
    assert "https://example.com/docs" in urls
    assert "http://example.org/help" in urls


def test_repourl_entries_url_in_description():
    """Test that repourl_entries finds URLs in the %description section."""
    rpm_spec = RPMSpec(TESTRPM_WITH_URLS_SPEC_FILE, fallback_plain_rpm=True)
    urls = rpm_spec.repourl_entries()

    # Check for URLs that appear in the description
    # Including URLs from global variables that are used in the description
    assert "git://example.com/repo" in urls
    assert "https://example.com/documentation" in urls
    assert "GIT://github.com/example/testrpm.git" in urls
    assert "git://gitlab.com/example/testrpm.git" in urls


def test_repourl_entries_url_in_sections():
    """Test that repourl_entries finds URLs in various RPM spec sections."""
    rpm_spec = RPMSpec(TESTRPM_WITH_URLS_SPEC_FILE, fallback_plain_rpm=True)
    urls = rpm_spec.repourl_entries()

    # Check for URLs in different sections
    # Including URLs from global variables that are used in git clone commands
    assert "GIT://github.com/example/testrpm.git" in urls
    assert "git://gitlab.com/example/testrpm.git" in urls
    assert "HTTPS://build-resources.example.com/tools" in urls
    assert "https://feature.example.com" in urls


def test_repourl_entries_with_query_params():
    """Test that repourl_entries correctly handles URLs with query parameters."""
    rpm_spec = RPMSpec(TESTRPM_WITH_URLS_SPEC_FILE, fallback_plain_rpm=True)
    urls = rpm_spec.repourl_entries()

    # The regex should stop at the question mark, so we won't see the query params
    assert "http://configs.example.com/testrpm" in urls
    assert "http://configs.example.com/testrpm?version=0.1" not in urls


def test_repourl_entries_standard_spec():
    """Test the repourl_entries function with a standard spec file."""
    rpm_spec = RPMSpec(TESTRPM_SPEC_FILE, fallback_plain_rpm=True)
    urls = rpm_spec.repourl_entries()

    # Check that we found the expected URLs from the standard spec file
    assert len(urls) == 3
    assert "https://testrpmexample.com/testrpm" in urls
    assert "https://testrpmexample.com/testrpm-0.1.tar.gz" in urls
    assert "https://testrpmexample.com/testrpm-0.1.tar.gz.sig" in urls
