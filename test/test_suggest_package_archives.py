# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# TODOs:
#  - more complex test: with several local archives and invalid Source lines (such that different
#    suggest-archives heuristics are tested), and the test must verify "We suggest ..." lines
#    in the output. No need to test transformations in this test, as this is already tested by the
#    existing tests test_srpm_suggest_package_archives_{function/cli}.

import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

from package_validation_tool.cli import main
from package_validation_tool.package.rpm.source_package import RPMSourcepackage
from package_validation_tool.package.rpm.utils import get_single_spec_file, parse_rpm_spec_file
from package_validation_tool.package.suggesting_archives.core import (
    RemotePackageArchivesSuggester,
    suggest_remote_package_archives,
)
from package_validation_tool.utils import pushd

TEST_DIR_PATH = os.path.dirname(__file__)
TESTRPM_SPEC_FILE = Path(TEST_DIR_PATH) / "artefacts" / "rpm" / "testrpm_for_suggesting.spec"


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
    src_rpm_file = Path(target_dir) / "testrpm_for_suggesting.src.rpm"
    src_rpm_file.touch()

    # create dummy file in a new dir, put it into the inner archive
    files_to_archive_path = Path(target_dir) / "files"
    os.mkdir(files_to_archive_path)

    dummy_file = files_to_archive_path / "plainfile"
    with open(dummy_file, "w", encoding="utf-8") as f:
        f.write("Test file")

    inner_archive_path = Path(target_dir) / "inner_archive"
    inner_archive_file = shutil.make_archive(inner_archive_path, "gztar", files_to_archive_path)
    shutil.copy(inner_archive_file, files_to_archive_path)
    os.remove(dummy_file)

    # create the outer (nested) archive and have a copy in the srpm directory
    outer_archive_path = Path(target_dir) / "testrpm-blob-0.1.tar"  # must correspond to Source0

    # note: cannot use shutil.make_archive here because
    # https://stackoverflow.com/questions/70080766/pythons-shutil-make-archive-creates-dot-directory-on-linux-when-using-tar-or
    with tarfile.open(outer_archive_path, "w") as tar:
        for entry in os.scandir(files_to_archive_path):
            tar.add(entry.path, arcname=entry.name)

    shutil.copy(outer_archive_path, srpm_content_path)

    return srpm_content_path, src_rpm_file, outer_archive_path, inner_archive_file


def test_srpm_package_archives_suggester_class():
    """Test RemotePackageArchivesSuggester class."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        found_accessible_url = False
        srpm_content_path, src_rpm_file, _, _ = prepare_srpm_test_environment(temp_dir)

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

            source_package = RPMSourcepackage(package_name="testrpm_for_suggesting")
            source_package_name = source_package.get_name()
            local_archives, spec_sources = source_package.get_local_and_spec_source_archives()

            remote_package_archive_suggester = RemotePackageArchivesSuggester(
                source_package_name=source_package_name,
                local_archives=local_archives,
                spec_sources=spec_sources,
            )
            remote_package_archive_suggester.apply_transformations()
            assert remote_package_archive_suggester.has_local_archives_and_spec_sources()
            remote_package_archive_suggester.find_suggestions()
            remote_package_archive_suggester.determine_unused_spec_sources()

            res = remote_package_archive_suggester.get_suggestion_result()

            text = RemotePackageArchivesSuggester.get_suggestions(res)
            assert len(text) == 10
            assert text[0].strip() == "We suggest to change local archives in package sources:"
            assert text[1].strip() == "- from:"
            assert text[2].strip() == "testrpm-blob-0.1.tar"
            assert text[3].strip() == "- to:"
            assert text[4].strip() == "inner_archive.tar.gz"
            assert text[5].strip() == "We suggest to change Source lines in package spec file:"
            assert text[6].strip() == "- from:"
            assert text[7].strip() == "testrpm-blob-0.1.tar"
            assert text[8].strip() == "- to:"
            # we don't care about actual URL, only care that some URL was proposed
            assert "https://" in text[9] and "inner_archive.tar.gz" in text[9]

            package_stats = RemotePackageArchivesSuggester.get_stats(res)
            assert package_stats.transformations_applied == 1
            assert package_stats.suggested_local_archives == 1
            assert package_stats.total_local_archives == 1
            assert package_stats.unused_spec_sources == 0
            assert package_stats.all_spec_sources == 1

            res.write_json_output(output_json_path)
            with open(output_json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

            assert len(json_data["orig_local_archives"]) == 1
            assert json_data["orig_local_archives"][0] == "testrpm-blob-0.1.tar"
            assert len(json_data["orig_spec_sources"]) == 1
            assert json_data["orig_spec_sources"][0] == "testrpm-blob-0.1.tar"

            assert len(json_data["trans_local_archives"]) == 1
            assert json_data["trans_local_archives"][0] == "inner_archive.tar.gz"
            assert len(json_data["trans_spec_sources"]) == 1
            assert json_data["trans_spec_sources"][0] == "inner_archive.tar.gz"

            assert len(json_data["transformations"]) == 1
            transformation = json_data["transformations"][0]
            assert transformation["name"] == "transform_extract_nested_archives"

            assert len(transformation["input_local_archives"]) == 1
            assert transformation["input_local_archives"][0] == "testrpm-blob-0.1.tar"
            assert len(transformation["input_spec_sources"]) == 1
            assert transformation["input_spec_sources"][0] == "testrpm-blob-0.1.tar"

            assert len(transformation["output_local_archives"]) == 1
            assert transformation["output_local_archives"][0] == "inner_archive.tar.gz"
            assert len(transformation["output_spec_sources"]) == 1
            assert transformation["output_spec_sources"][0] == "inner_archive.tar.gz"

            assert len(json_data["suggestions"]) == 1
            assert "inner_archive.tar.gz" in json_data["suggestions"]

            assert len(json_data["suggestions"]["inner_archive.tar.gz"]) == 1
            assert (
                json_data["suggestions"]["inner_archive.tar.gz"][0]["spec_source"]
                == "inner_archive.tar.gz"
            )

            assert len(json_data["unused_spec_sources"]) == 0


def test_srpm_suggest_package_archives_function():
    """Test srpm suggest-package-archives CLI function."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        found_accessible_url = False
        srpm_content_path, src_rpm_file, _, _ = prepare_srpm_test_environment(temp_dir)

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
            suggest_remote_package_archives(
                package_name="testrpm_for_suggesting",
                output_json_path=output_json_path,
                transform_archives=True,
            )

            with open(output_json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

            assert len(json_data["orig_local_archives"]) == 1
            assert json_data["orig_local_archives"][0] == "testrpm-blob-0.1.tar"
            assert len(json_data["orig_spec_sources"]) == 1
            assert json_data["orig_spec_sources"][0] == "testrpm-blob-0.1.tar"

            assert len(json_data["trans_local_archives"]) == 1
            assert json_data["trans_local_archives"][0] == "inner_archive.tar.gz"
            assert len(json_data["trans_spec_sources"]) == 1
            assert json_data["trans_spec_sources"][0] == "inner_archive.tar.gz"

            assert len(json_data["transformations"]) == 1
            transformation = json_data["transformations"][0]
            assert transformation["name"] == "transform_extract_nested_archives"

            assert len(transformation["input_local_archives"]) == 1
            assert transformation["input_local_archives"][0] == "testrpm-blob-0.1.tar"
            assert len(transformation["input_spec_sources"]) == 1
            assert transformation["input_spec_sources"][0] == "testrpm-blob-0.1.tar"

            assert len(transformation["output_local_archives"]) == 1
            assert transformation["output_local_archives"][0] == "inner_archive.tar.gz"
            assert len(transformation["output_spec_sources"]) == 1
            assert transformation["output_spec_sources"][0] == "inner_archive.tar.gz"

            assert len(json_data["suggestions"]) == 1
            assert "inner_archive.tar.gz" in json_data["suggestions"]

            assert len(json_data["suggestions"]["inner_archive.tar.gz"]) == 1
            assert (
                json_data["suggestions"]["inner_archive.tar.gz"][0]["spec_source"]
                == "inner_archive.tar.gz"
            )

            assert len(json_data["unused_spec_sources"]) == 0


def test_srpm_suggest_package_archives_cli():
    """Test srpm suggest-package-archives CLI."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        found_accessible_url = False
        srpm_content_path, src_rpm_file, _, _ = prepare_srpm_test_environment(temp_dir)

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
                    "testrpm_for_suggesting",
                    "--transform-archives",
                    "-o",
                    str(output_json_path),
                ]
            )

            with open(output_json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

            assert len(json_data["orig_local_archives"]) == 1
            assert json_data["orig_local_archives"][0] == "testrpm-blob-0.1.tar"
            assert len(json_data["orig_spec_sources"]) == 1
            assert json_data["orig_spec_sources"][0] == "testrpm-blob-0.1.tar"

            assert len(json_data["trans_local_archives"]) == 1
            assert json_data["trans_local_archives"][0] == "inner_archive.tar.gz"
            assert len(json_data["trans_spec_sources"]) == 1
            assert json_data["trans_spec_sources"][0] == "inner_archive.tar.gz"

            assert len(json_data["transformations"]) == 1
            transformation = json_data["transformations"][0]
            assert transformation["name"] == "transform_extract_nested_archives"

            assert len(transformation["input_local_archives"]) == 1
            assert transformation["input_local_archives"][0] == "testrpm-blob-0.1.tar"
            assert len(transformation["input_spec_sources"]) == 1
            assert transformation["input_spec_sources"][0] == "testrpm-blob-0.1.tar"

            assert len(transformation["output_local_archives"]) == 1
            assert transformation["output_local_archives"][0] == "inner_archive.tar.gz"
            assert len(transformation["output_spec_sources"]) == 1
            assert transformation["output_spec_sources"][0] == "inner_archive.tar.gz"

            assert len(json_data["suggestions"]) == 1
            assert "inner_archive.tar.gz" in json_data["suggestions"]

            assert len(json_data["suggestions"]["inner_archive.tar.gz"]) == 1
            assert (
                json_data["suggestions"]["inner_archive.tar.gz"][0]["spec_source"]
                == "inner_archive.tar.gz"
            )

            assert len(json_data["unused_spec_sources"]) == 0
