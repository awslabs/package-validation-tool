# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from package_validation_tool.package.rpm.source_package import RPMSourcepackage
from package_validation_tool.package.rpm.utils import parse_rpm_spec_file
from package_validation_tool.utils import pushd

TEST_DIR_PATH = os.path.dirname(__file__)
TESTRPM_SPEC_FILE = Path(TEST_DIR_PATH) / "artefacts" / "rpm" / "testrpm.spec"


def test_srpm_object_creation():
    """Test srpm creation."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):

        # directory to place the srpm files
        srpm_content_path = Path(temp_dir) / "srpm"
        os.mkdir(srpm_content_path)
        shutil.copy(TESTRPM_SPEC_FILE, srpm_content_path / "testrpm.spec")

        # create fake srpm file
        src_rpm_file = Path(temp_dir) / "testrpm.src.rpm"
        src_rpm_file.touch()

        def patched_parse_rpm_spec_file(spec_file: str, fallback_plain_rpm: bool):
            """Override parameter wrt parsing, to not require rpmspec tool."""
            return parse_rpm_spec_file(spec_file, fallback_plain_rpm=True)

        # mock accessing remote content and point to local files instead
        # pretend we have the rpmspec tool available to start the parsing
        # allow to fall back to plain spec file
        # Note: mock with the namespace of where the function is actually called from
        with patch(
            "package_validation_tool.package.rpm.source_package.download_and_extract_source_package"
        ) as mock_download_extract, patch(
            "package_validation_tool.package.rpm.spec.rpmspec_present"
        ) as rpmspec_present, patch(
            "package_validation_tool.package.rpm.spec.parse_rpm_spec_file",
            patched_parse_rpm_spec_file,
        ):

            # do not use yumdownloader
            mock_download_extract.return_value = str(src_rpm_file.absolute()), srpm_content_path
            # pretend we have the rpmspec tool available
            rpmspec_present.return_value = True

            srpm = RPMSourcepackage("testrpm")
            srpm._initialize_package()
            assert srpm._spec.package_version() == "0.1"

            with tempfile.TemporaryDirectory() as package_store_dir:
                srpm.store_package_content(package_store_dir)

                stored_files = os.listdir(package_store_dir)

                assert "SPECS" in stored_files
                assert "SRPM_CONTENT" in stored_files
                assert os.path.exists(
                    os.path.join(package_store_dir, "SRPM_CONTENT", "testrpm.spec")
                )
