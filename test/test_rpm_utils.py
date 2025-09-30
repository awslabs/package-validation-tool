# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from package_validation_tool.package.rpm.utils import (
    download_and_extract_source_package,
    get_env_with_home,
    get_package_basename,
)

TEST_DIR_PATH = os.path.dirname(__file__)
ARTEFACTS_DIR = Path(TEST_DIR_PATH) / "artefacts" / "utils_examples"


def test_get_package_basename():
    """Test the get_package_basename function"""
    assert get_package_basename("gawk-5.1.0-3.0.3.aarch64.rpm") == "gawk-5.1.0-3.0.3"
    assert get_package_basename("gawk-5.1.0-3.0.3.x86_64.rpm") == "gawk-5.1.0-3.0.3"
    assert get_package_basename("gawk-5.1.0-3.0.3.noarch.rpm") == "gawk-5.1.0-3.0.3"
    assert get_package_basename("gawk-5.1.0-3.0.3") == "gawk-5.1.0-3.0.3"


def test_download_and_extract_source_package_failure():
    """Test the download_and_extract_source_package function with a failed download or extraction"""
    package_name = "gawk-5.1.0-3.0.3.x86_64.rpm"
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("subprocess.run") as mock_run, patch(
            "package_validation_tool.package.rpm.utils.get_system_install_tool"
        ) as get_system_install_tool:
            mock_run.side_effect = subprocess.CalledProcessError(1, "yumdownloader")
            # test may execute on non-Fedora-family OS distro, pretend the system has dnf
            get_system_install_tool.return_value = "dnf"
            srpm, content_dir = download_and_extract_source_package(package_name, temp_dir)
            assert srpm is None
            assert content_dir is None


def test_get_env_with_home_dict_modification():
    """Check whether environ dict modifications work."""
    original_home = os.environ.get("HOME")
    new_home = "/new/home/path"
    modified_env = get_env_with_home(new_home)

    assert "HOME" in modified_env
    assert modified_env["HOME"] == new_home
    assert modified_env != os.environ  # Ensure it's a copy, not the original
    assert all(key in modified_env for key in os.environ)  # All original keys are present

    for key, value in os.environ.items():
        if key != "HOME":
            assert modified_env[key] == value

    assert os.environ.get("HOME") == original_home
