# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from package_validation_tool.cli import main
from package_validation_tool.package.rpm.utils import get_single_spec_file, parse_rpm_spec_file
from package_validation_tool.package.validation import match_package_repos
from package_validation_tool.utils import pushd

TEST_DIR_PATH = os.path.dirname(__file__)
TESTRPM_SPEC_FILE = Path(TEST_DIR_PATH) / "artefacts" / "rpm" / "testrpm.spec"


def patched_parse_rpm_spec_file(spec_file: str, fallback_plain_rpm: bool):
    """Override parameter wrt parsing, to not require rpmspec tool."""
    return parse_rpm_spec_file(spec_file, fallback_plain_rpm=True)


def patched_prepare_rpmbuild_source(
    src_rpm_file: str = None, package_rpmbuild_home: str = "rpm_home"
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


def prepare_srpm_test_environment(temp_dir: str):
    """Prepare an environment for srpm testing on disk, using temp_dir as root."""
    archive_file = Path(temp_dir) / "testrpm-0.1"

    local_src_path = Path(temp_dir) / "src"
    os.mkdir(local_src_path)

    # directory to place the srpm files
    srpm_content_path = Path(temp_dir) / "srpm"
    os.mkdir(srpm_content_path)
    shutil.copy(TESTRPM_SPEC_FILE, srpm_content_path / "testrpm.spec")

    # create fake srpm file
    src_rpm_file = Path(temp_dir) / "testrpm.src.rpm"
    src_rpm_file.touch()

    # create file testrpm-0.1/testfile
    with open(local_src_path / "testfile", "w") as f:
        f.write("Test file")
    # zip local_src_path into testrpm-0.1.tar.gz and have a copy in the srpm directory
    archive_file = shutil.make_archive(archive_file, "gztar", local_src_path)
    shutil.copy(archive_file, srpm_content_path)

    return srpm_content_path, src_rpm_file, archive_file


def create_suggested_repos_json(temp_dir: str, archive_file: str):
    """Create a suggested repositories JSON file similar to the openssh example."""
    repos_json_path = Path(temp_dir) / "suggested_repos.json"

    suggested_repos_data = {
        "source_package_name": "testrpm",
        "local_archives": ["testrpm-0.1.tar.gz"],
        "suggestions": {
            "testrpm-0.1.tar.gz": [
                {
                    "repo": "https://github.com/example/testrpm",
                    "commit_hash": "abc123def456",
                    "tag": "v0.1",
                    "confidence": 1.0,
                },
                {
                    "repo": "https://github.com/other/testrpm-mirror",
                    "commit_hash": "def456abc123",
                    "tag": "release-0.1",
                    "confidence": 0.5,
                },
            ]
        },
    }

    with open(repos_json_path, "w", encoding="utf-8") as f:
        json.dump(suggested_repos_data, f, indent=2)

    return repos_json_path


def test_srpm_repo_matching_cli():
    """Test srpm package repository matching via CLI."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        srpm_content_path, src_rpm_file, archive_file = prepare_srpm_test_environment(temp_dir)
        repos_json_path = create_suggested_repos_json(temp_dir, archive_file)
        output_json_path = Path(temp_dir) / "output.json"

        # Mock the clone_git_repo function
        with patch(
            "package_validation_tool.package.rpm.source_package.clone_git_repo"
        ) as mock_clone_git_repo:
            # Configure mock to simulate successful cloning
            def mock_clone_side_effect(repo, target_dir=None, bare=False):
                assert target_dir
                with open(os.path.join(target_dir, "testfile"), "w") as f:
                    if "example/testrpm" in repo:
                        # let's make the first suggested repo NOT match
                        f.write("Not matching contents")
                    elif "other/testrpm-mirror" in repo:
                        # second suggested repo matches: same as in prepare_srpm_test_environment()
                        f.write("Test file")
                    else:
                        assert False, "Unexpected repo"
                return True, target_dir

            mock_clone_git_repo.side_effect = mock_clone_side_effect

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
            ), patch(
                "package_validation_tool.package.rpm.source_package.prepare_rpmbuild_source",
                patched_prepare_rpmbuild_source,
            ), patch(
                "package_validation_tool.package.rpm.source_package.checkout_in_git_repo"
            ) as mock_checkout_in_git_repo, patch(
                "package_validation_tool.package.rpm.source_package.get_git_tree_hash"
            ) as mock_get_git_tree_hash:

                # do not use yumdownloader
                mock_download_extract.return_value = (
                    str(src_rpm_file.absolute()),
                    srpm_content_path,
                )
                # pretend we have the rpmspec tool available
                rpmspec_present.return_value = True
                # git checkout is always successful (we mock checkout in mock_clone_git_repo)
                mock_checkout_in_git_repo.return_value = True
                # simulate failure when getting tree hash: this disables repo-contents caching
                # (we do not care about this part in this test)
                mock_get_git_tree_hash.return_value = None

                # Test via CLI
                cli_result = main(
                    [
                        "match-package-repos",
                        "--package-name",
                        "testrpm",
                        "--input-repos-json-path",
                        str(repos_json_path),
                        "--output-json-path",
                        str(output_json_path),
                        "--package-type",
                        "rpm",
                        "--no-apply-autotools",
                    ]
                )

                assert cli_result == 0
                assert output_json_path.exists()

                with open(output_json_path, "r", encoding="utf-8") as f:
                    output_data = json.load(f)
                assert output_data["matching"] is True

                # Check that archive_hashes field is present
                assert "archive_hashes" in output_data
                assert "testrpm-0.1.tar.gz" in output_data["archive_hashes"]
                # Archive hash should be a valid SHA256 hash (64 characters)
                archive_hash = output_data["archive_hashes"]["testrpm-0.1.tar.gz"]
                assert isinstance(archive_hash, str)
                assert len(archive_hash) == 64

                assert "results" in output_data
                assert len(output_data["results"]) == 1
                assert "testrpm-0.1.tar.gz" in output_data["results"]

                archive_matched_repos = output_data["results"]["testrpm-0.1.tar.gz"]
                for repo in archive_matched_repos:
                    if repo["remote_repo"] == "https://github.com/example/testrpm":
                        assert repo["commit_hash"] == "abc123def456"
                        assert repo["tag"] == "v0.1"
                        assert repo["accessible"] is True
                        assert repo["matched"] is False
                        assert repo["autotools_applied"] is False
                        assert len(repo["conflicts"]) == 1
                        assert "testfile" in repo["conflicts"]
                        # Check new file statistics fields
                        assert repo["files_total"] == 1
                        assert repo["files_matched"] == 0
                        assert repo["files_different"] == 1
                        assert repo["files_no_counterpart"] == 0
                        assert repo["conflicts"]["testfile"] == "DIFFERENT"
                        assert repo["files_matched_ratio"] == 0.0
                        assert repo["files_different_ratio"] == 1.0
                        assert repo["files_no_counterpart_ratio"] == 0.0
                    elif repo["remote_repo"] == "https://github.com/other/testrpm-mirror":
                        assert repo["commit_hash"] == "def456abc123"
                        assert repo["tag"] == "release-0.1"
                        assert repo["accessible"] is True
                        assert repo["matched"] is True
                        assert len(repo["conflicts"]) == 0
                        # Check new file statistics fields for matching repo
                        assert repo["files_total"] == 1
                        assert repo["files_matched"] == 1
                        assert repo["files_different"] == 0
                        assert repo["files_no_counterpart"] == 0
                        assert repo["files_matched_ratio"] == 1.0
                        assert repo["files_different_ratio"] == 0.0
                        assert repo["files_no_counterpart_ratio"] == 0.0
                    else:
                        assert False, "Unexpected matched repo in the result"


def test_invalid_json_file():
    """Test that function raises error when JSON file doesn't have 'suggestions' key."""
    with tempfile.TemporaryDirectory() as temp_dir:
        invalid_json_path = Path(temp_dir) / "invalid.json"
        invalid_data = {
            "source_package_name": "testrpm",
            "local_archives": ["testrpm-0.1.tar.gz"],
            # Missing 'suggestions' key
        }

        with open(invalid_json_path, "w", encoding="utf-8") as f:
            json.dump(invalid_data, f)

        with pytest.raises(ValueError, match="file must contain 'suggestions' key"):
            match_package_repos(
                package_name="testrpm",
                input_repos_json_path=str(invalid_json_path),
                package_type="rpm",
            )


def test_nonexistent_json_file():
    """Test that function raises error when JSON file doesn't exist."""
    nonexistent_path = "/nonexistent/path/repos.json"

    with pytest.raises(FileNotFoundError):
        match_package_repos(
            package_name="testrpm", input_repos_json_path=nonexistent_path, package_type="rpm"
        )
