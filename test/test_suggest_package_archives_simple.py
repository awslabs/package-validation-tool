# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Split from the main test_suggest_package_archives.py. Tests a simple package, i.e. a
# package that contains one archive and one corresponding Source line in the spec.
# See also testrpm_for_suggesting_simple.spec.

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from package_validation_tool.cli import main
from package_validation_tool.package.rpm.utils import get_single_spec_file, parse_rpm_spec_file
from package_validation_tool.utils import pushd

TEST_DIR_PATH = os.path.dirname(__file__)
TESTRPM_SPEC_FILE = Path(TEST_DIR_PATH) / "artefacts" / "rpm" / "testrpm_for_suggesting_simple.spec"


def patched_parse_rpm_spec_file(spec_file: str, _fallback_plain_rpm: bool):
    """Override parameter wrt parsing, to not require rpmspec tool."""
    return parse_rpm_spec_file(spec_file, fallback_plain_rpm=True)


def patched_prepare_rpmbuild_source(
    src_rpm_file: str = None,  # pylint: disable=unused-argument
    package_rpmbuild_home: str = "rpm_home",
):
    """Perform the most basic operations to fake an rpmbuild directory."""
    os.mkdir(os.path.basename(package_rpmbuild_home))
    abs_package_rpmbuild_home = os.path.abspath(package_rpmbuild_home)

    with pushd(abs_package_rpmbuild_home):
        os.mkdir("rpmbuild")
        with pushd("rpmbuild"):
            os.mkdir("SOURCES")
            abs_source_path = os.path.abspath("SOURCES")
            os.mkdir("SPECS")
            shutil.copy(TESTRPM_SPEC_FILE, "SPECS")
            abs_spec_file_path = os.path.abspath(get_single_spec_file("SPECS"))

    return abs_package_rpmbuild_home, abs_source_path, abs_spec_file_path


def prepare_srpm_test_environment(target_dir: str):
    """Prepare an environment for srpm testing on disk, using target_dir as root."""
    # directory to place the srpm files
    srpm_content_path = Path(target_dir) / "srpm"
    os.mkdir(srpm_content_path)
    shutil.copy(TESTRPM_SPEC_FILE, srpm_content_path)

    # create fake srpm file (not needed for our testing, so can be empty)
    src_rpm_file = Path(target_dir) / "testrpm_for_suggesting_simple.src.rpm"
    src_rpm_file.touch()

    # create dummy file in a new dir, put it into the inner archive
    files_to_archive_path = Path(target_dir) / "files"
    os.mkdir(files_to_archive_path)

    dummy_file = files_to_archive_path / "plainfile"
    with open(dummy_file, "w", encoding="utf-8") as f:
        f.write("Test file")
    shutil.copy(dummy_file, srpm_content_path)

    archive_path = Path(target_dir) / "archive-0.1"
    archive_file = shutil.make_archive(archive_path, "gztar", files_to_archive_path)
    shutil.copy(archive_file, srpm_content_path)
    os.remove(dummy_file)

    archive_file_path = Path(srpm_content_path) / os.path.basename(archive_file)
    return srpm_content_path, src_rpm_file, archive_file_path


def test_srpm_suggest_package_archives_simple_cli():
    """Test srpm suggest-package-archives CLI on a simple package."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        found_accessible_url = False
        srpm_content_path, src_rpm_file, _ = prepare_srpm_test_environment(temp_dir)

        def patched_is_url_accessible(url: str) -> bool:
            """Return True only once for an "http(s)" address, instead of accessing internet."""
            nonlocal found_accessible_url
            if not url.startswith("http") or found_accessible_url:
                return False
            found_accessible_url = True
            return True

        # - mock accessing remote SRPM and point to local files instead
        # - pretend we have the rpmspec tool available to start the parsing
        # - mock accessing URLs with following logic: return True only for the first http(s) URL
        # - mock accessing remote archives and point to local files instead
        # - tiny wrapper around parse_rpm_spec_file() to always fall back to plain spec file
        # - fake an rpmbuild/ directory
        with patch(
            "package_validation_tool.package.rpm.source_package.download_and_extract_source_package"
        ) as mock_download_extract, patch(
            "package_validation_tool.package.rpm.spec.rpmspec_present"
        ) as rpmspec_present, patch(
            "package_validation_tool.package.suggesting_archives.suggestion_methods.is_url_accessible",
            patched_is_url_accessible,
        ), patch(
            "package_validation_tool.package.rpm.spec.parse_rpm_spec_file",
            patched_parse_rpm_spec_file,
        ), patch(
            "package_validation_tool.package.rpm.source_package.prepare_rpmbuild_source",
            patched_prepare_rpmbuild_source,
        ):

            # do not use yumdownloader
            mock_download_extract.return_value = str(src_rpm_file.absolute()), srpm_content_path
            # pretend we have the rpmspec tool available
            rpmspec_present.return_value = True

            output_json_path = Path(temp_dir) / "output.json"

            assert 0 == main(
                [
                    "suggest-package-archives",
                    "-p",
                    "testrpm_for_suggesting_simple",
                    "--transform-archives",
                    "-o",
                    str(output_json_path),
                ]
            )

            with open(output_json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

            assert len(json_data["orig_local_archives"]) == 1
            assert json_data["orig_local_archives"][0] == "archive-0.1.tar.gz"
            assert len(json_data["orig_spec_sources"]) == 1
            assert (
                json_data["orig_spec_sources"][0]
                == "http://example.com/path/to/archive/version/0.1.tar.gz#/archive-0.1.tar.gz"
            )

            assert len(json_data["trans_local_archives"]) == 1
            assert json_data["trans_local_archives"][0] == "archive-0.1.tar.gz"
            assert len(json_data["trans_spec_sources"]) == 1
            assert (
                json_data["trans_spec_sources"][0]
                == "http://example.com/path/to/archive/version/0.1.tar.gz"
            )

            assert len(json_data["transformations"]) == 1
            transformation = json_data["transformations"][0]
            assert transformation["name"] == "transform_remove_url_fragment_from_spec_sources"

            assert len(transformation["input_local_archives"]) == 1
            assert transformation["input_local_archives"][0] == "archive-0.1.tar.gz"
            assert len(transformation["input_spec_sources"]) == 1
            assert (
                transformation["input_spec_sources"][0]
                == "http://example.com/path/to/archive/version/0.1.tar.gz#/archive-0.1.tar.gz"
            )

            assert len(transformation["output_local_archives"]) == 1
            assert transformation["output_local_archives"][0] == "archive-0.1.tar.gz"
            assert len(transformation["output_spec_sources"]) == 1
            assert (
                transformation["output_spec_sources"][0]
                == "http://example.com/path/to/archive/version/0.1.tar.gz"
            )

            assert len(json_data["suggestions"]) == 1
            assert "archive-0.1.tar.gz" in json_data["suggestions"]

            assert len(json_data["suggestions"]["archive-0.1.tar.gz"]) == 1
            assert (
                json_data["suggestions"]["archive-0.1.tar.gz"][0]["spec_source"]
                == "http://example.com/path/to/archive/version/0.1.tar.gz"
            )
            assert (
                json_data["suggestions"]["archive-0.1.tar.gz"][0]["remote_archive"]
                == "http://example.com/path/to/archive/version/0.1.tar.gz"
            )
