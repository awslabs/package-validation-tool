# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from package_validation_tool.cli import main
from package_validation_tool.package.rpm.source_package import RPMSourcepackage
from package_validation_tool.package.rpm.utils import get_single_spec_file, parse_rpm_spec_file
from package_validation_tool.package.suggesting_archives import RemoteArchiveSuggestion
from package_validation_tool.package.suggesting_repos import (
    PackageRemoteReposSuggestions,
    RemoteRepoSuggestion,
)
from package_validation_tool.package.validation import match_package_archives
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

    # directory to place the srpm files
    srpm_content_path = Path(temp_dir) / "srpm"
    os.mkdir(srpm_content_path)
    shutil.copy(TESTRPM_SPEC_FILE, srpm_content_path / "testrpm.spec")

    # create fake srpm file
    src_rpm_file = Path(temp_dir) / "testrpm.src.rpm"
    src_rpm_file.touch()

    # create file testrpm-0.1.tar.gz
    local_src_path = Path(temp_dir) / "src"
    os.mkdir(local_src_path)
    with open(local_src_path / "testfile", "w") as f:
        f.write("Test file")

    # zip local_src_path into testrpm-0.1.tar.gz and have a copy in the srpm directory
    archive_base_path = Path(temp_dir) / "testrpm-0.1"
    archive_file = shutil.make_archive(archive_base_path, "gztar", local_src_path)
    shutil.copy(archive_file, srpm_content_path)

    return srpm_content_path, src_rpm_file, archive_file


def create_mock_suggested_archives(archive_name: str, spec_source_url: str):
    """Create mock suggested archives for testing."""
    suggestion = RemoteArchiveSuggestion(
        remote_archive=spec_source_url,
        spec_source=spec_source_url,
        suggested_by="test",
        notes="Test suggestion",
        confidence=1.0,
    )

    return {archive_name: [suggestion]}


def create_mock_suggested_repos(archive_name: str, repo_url: str):
    """Create mock suggested repos for testing."""
    suggestion = RemoteRepoSuggestion(
        repo=repo_url,
        commit_hash="abc123def456",
        tag="v0.1",
        suggested_by="test",
        notes="Test repo suggestion",
        confidence=1.0,
    )

    return {archive_name: [suggestion]}


def test_srpm_archive_matching_success():
    """Test srpm package archive matching."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        srpm_content_path, src_rpm_file, archive_file = prepare_srpm_test_environment(temp_dir)

        def move_file_as_download(file_url: str, local_file_path: str):
            """Use the local archive as downloaded file, signal success."""
            shutil.copy(archive_file, local_file_path)
            return True

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
            "package_validation_tool.package.rpm.source_package.download_file",
            move_file_as_download,
        ), patch(
            "package_validation_tool.package.rpm.source_package.prepare_rpmbuild_source",
            patched_prepare_rpmbuild_source,
        ):

            # do not use yumdownloader
            mock_download_extract.return_value = str(src_rpm_file.absolute()), srpm_content_path
            # pretend we have the rpmspec tool available
            rpmspec_present.return_value = True

            srpm = RPMSourcepackage("testrpm")

            # as download, use the same local archive, mock the right namespace
            # Create suggested archives for the test
            suggested_archives = create_mock_suggested_archives(
                "testrpm-0.1.tar.gz", "https://example.com/testrpm-0.1.tar.gz"
            )
            unused_spec_sources = []
            match_result = srpm.match_remote_archives(suggested_archives, unused_spec_sources)

            # Basic result assertions
            assert match_result.matching
            assert match_result.source_package_name == "testrpm"

            # Check package-level metadata fields
            assert match_result.srpm_available is True
            assert match_result.spec_valid is True
            assert match_result.source_extractable is True

            # Check timestamp field exists and is a string
            assert hasattr(match_result, "timestamp")
            assert isinstance(match_result.timestamp, str)
            assert len(match_result.timestamp) > 0

            # Check that archive_hashes field is present and contains our archive
            assert "archive_hashes" in match_result.__dict__
            assert "testrpm-0.1.tar.gz" in match_result.archive_hashes
            # Archive hash should be a valid SHA256 hash (64 characters)
            archive_hash = match_result.archive_hashes["testrpm-0.1.tar.gz"]
            assert isinstance(archive_hash, str)
            assert len(archive_hash) == 64

            # Check results structure
            assert len(match_result.results) > 0
            assert "testrpm-0.1.tar.gz" in match_result.results

            # Check the specific archive result
            archive_results = match_result.results["testrpm-0.1.tar.gz"]
            assert isinstance(archive_results, list)
            assert len(archive_results) == 1

            # Check the individual RemoteArchiveResult
            remote_result = archive_results[0]
            assert remote_result.remote_archive == "https://example.com/testrpm-0.1.tar.gz"
            assert remote_result.accessible is True
            assert remote_result.matched is True
            assert remote_result.files_total == 1
            assert remote_result.files_matched == 1
            assert remote_result.files_different == 0
            assert remote_result.files_no_counterpart == 0
            assert isinstance(remote_result.conflicts, dict)


def test_srpm_archive_matching_failing_offline():
    """Test srpm package archive matching failing if download fails."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        srpm_content_path, src_rpm_file, _ = prepare_srpm_test_environment(temp_dir)

        def move_file_as_download(file_url: str, local_file_path: str):
            """Do not create a file, and signal download failure."""
            return False

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
            "package_validation_tool.package.rpm.source_package.download_file",
            move_file_as_download,
        ), patch(
            "package_validation_tool.package.rpm.source_package.prepare_rpmbuild_source",
            patched_prepare_rpmbuild_source,
        ):

            # do not use yumdownloader
            mock_download_extract.return_value = str(src_rpm_file.absolute()), srpm_content_path
            # pretend we have the rpmspec tool available
            rpmspec_present.return_value = True

            srpm = RPMSourcepackage("testrpm")

            # as download, use the same local archive, mock the right namespace
            # Create suggested archives for the test
            suggested_archives = create_mock_suggested_archives(
                "testrpm-0.1.tar.gz", "https://example.com/testrpm-0.1.tar.gz"
            )
            unused_spec_sources = []
            match_result = srpm.match_remote_archives(suggested_archives, unused_spec_sources)
            assert not match_result.matching
            # Check that we have results with unmatched entries
            assert len(match_result.results) > 0


def test_srpm_archive_matching_function():
    """Test srpm package archive matching CLI function."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        srpm_content_path, src_rpm_file, archive_file = prepare_srpm_test_environment(temp_dir)

        def move_file_as_download(file_url: str, local_file_path: str):
            """Use the local archive as downloaded file, signal success."""
            shutil.copy(archive_file, local_file_path)
            return True

        # mock accessing remote content and point to local files instead
        # mock the suggestion system
        def mock_get_archives_for_package(package_name: str, **kwargs):
            """Mock the get_archives_for_package function to return test suggestions."""
            from package_validation_tool.package.suggesting_archives import (
                PackageRemoteArchivesSuggestions,
            )

            result = PackageRemoteArchivesSuggestions()
            result.source_package_name = package_name
            result.unused_spec_sources = []
            result.suggestions = create_mock_suggested_archives(
                "testrpm-0.1.tar.gz", "https://example.com/testrpm-0.1.tar.gz"
            )
            return result

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
            "package_validation_tool.package.rpm.source_package.download_file",
            move_file_as_download,
        ), patch(
            "package_validation_tool.package.rpm.source_package.prepare_rpmbuild_source",
            patched_prepare_rpmbuild_source,
        ), patch(
            "package_validation_tool.package.validation.get_remote_archives_for_package",
            mock_get_archives_for_package,
        ):

            # do not use yumdownloader
            mock_download_extract.return_value = str(src_rpm_file.absolute()), srpm_content_path
            # pretend we have the rpmspec tool available
            rpmspec_present.return_value = True

            output_json_path = Path(temp_dir) / "output.json"
            match_package_archives(package_name="testrpm", output_json_path=output_json_path)

            with open(output_json_path, "r") as f:
                json_data = json.load(f)

            assert json_data["matching"]


def test_validate_system_packages_cli():
    """Test srpm package archive matching."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        srpm_content_path, src_rpm_file, archive_file = prepare_srpm_test_environment(temp_dir)

        def move_file_as_download(file_url: str, local_file_path: str):
            """Use the local archive as downloaded file, signal success."""
            shutil.copy(archive_file, local_file_path)
            return True

        # mock accessing remote content and point to local files instead
        # mock the suggestion system
        def mock_get_archives_for_package(package_name: str, **kwargs):
            """Mock the get_archives_for_package function to return test suggestions."""
            from package_validation_tool.package.suggesting_archives import (
                PackageRemoteArchivesSuggestions,
            )

            result = PackageRemoteArchivesSuggestions()
            result.source_package_name = package_name
            result.unused_spec_sources = []
            result.suggestions = create_mock_suggested_archives(
                "testrpm-0.1.tar.gz", "https://example.com/testrpm-0.1.tar.gz"
            )
            return result

        def mock_get_repos_for_package(package_name: str, **kwargs):
            """Mock the get_archives_for_package function to return test suggestions."""
            result = PackageRemoteReposSuggestions()
            result.source_package_name = package_name
            result.suggestions = create_mock_suggested_repos(
                "testrpm-0.1.tar.gz", "https://github.com/example/testrpm"
            )
            return result

        def mock_clone_side_effect(repo, target_dir=None, bare=False):
            assert target_dir
            # Create the target directory and test file to simulate cloned repo
            os.makedirs(target_dir, exist_ok=True)
            with open(os.path.join(target_dir, "testfile"), "w") as f:
                f.write("Test file")  # Same content as in the archive
            return True, target_dir

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
            "package_validation_tool.package.rpm.source_package.download_file",
            move_file_as_download,
        ), patch(
            "package_validation_tool.package.validation.all_system_packages"
        ) as mock_all_system_packages, patch(
            "package_validation_tool.package.rpm.source_package.prepare_rpmbuild_source",
            patched_prepare_rpmbuild_source,
        ), patch(
            "package_validation_tool.package.validation.get_remote_archives_for_package",
            mock_get_archives_for_package,
        ), patch(
            "package_validation_tool.package.validation.get_repos_for_package",
            mock_get_repos_for_package,
        ), patch(
            "package_validation_tool.package.rpm.source_package.clone_git_repo"
        ) as mock_clone_git_repo, patch(
            "package_validation_tool.package.rpm.source_package.checkout_in_git_repo"
        ) as mock_checkout_in_git_repo, patch(
            "package_validation_tool.package.rpm.source_package.get_git_tree_hash"
        ) as mock_get_git_tree_hash:

            mock_clone_git_repo.side_effect = mock_clone_side_effect
            mock_checkout_in_git_repo.return_value = True
            # simulate failure when getting tree hash: this disables repo-contents caching
            # (we do not care about this part in this test)
            mock_get_git_tree_hash.return_value = None

            # do not use yumdownloader
            mock_download_extract.return_value = str(src_rpm_file.absolute()), srpm_content_path
            # pretend we have the rpmspec tool available
            rpmspec_present.return_value = True
            # do not use repoquery, but pretend we have a package testrpm
            mock_all_system_packages.return_value = ["testrpm"]

            # matching the same file works as expected
            output_json_path_system = Path(temp_dir) / "output_system.json"
            assert 0 == main(
                [
                    "validate-system-packages",
                    "-N",
                    "2",
                    "--output-json-path",
                    str(output_json_path_system),
                ]
            )

            # Verify the output JSON file for validate-system-packages
            assert output_json_path_system.exists()
            with open(output_json_path_system, "r", encoding="utf-8") as f:
                system_output_data = json.load(f)

            # Check basic structure - SystemValidationResult format
            assert isinstance(system_output_data, dict)
            assert "report" in system_output_data
            assert "version" in system_output_data
            assert system_output_data["version"] == "2025-09-22"
            assert isinstance(system_output_data["report"], dict)
            assert len(system_output_data["report"]) > 0

            # Check the first package result
            package_result = system_output_data["report"]["testrpm"]
            assert package_result["package_name"] == "testrpm"
            assert package_result["valid"] is True
            assert "upstream_code_repos" in package_result
            assert "suggested_remote_repos" in package_result
            assert "matched_remote_archives" in package_result
            assert "matched_remote_repos" in package_result

            # Check upstream_code_repos mapping
            upstream_repos = package_result["upstream_code_repos"]
            assert isinstance(upstream_repos, dict)
            assert "testrpm-0.1.tar.gz" in upstream_repos
            assert upstream_repos["testrpm-0.1.tar.gz"] == "https://github.com/example/testrpm"

            # Check upstream_archives mapping
            assert "upstream_archives" in package_result
            upstream_archives = package_result["upstream_archives"]
            assert isinstance(upstream_archives, dict)
            assert "testrpm-0.1.tar.gz" in upstream_archives
            assert (
                upstream_archives["testrpm-0.1.tar.gz"] == "https://example.com/testrpm-0.1.tar.gz"
            )

            # Check archive_hashes
            assert "archive_hashes" in package_result
            archive_hashes = package_result["archive_hashes"]
            assert isinstance(archive_hashes, dict)
            assert "testrpm-0.1.tar.gz" in archive_hashes
            archive_hash = archive_hashes["testrpm-0.1.tar.gz"]
            assert isinstance(archive_hash, str)
            assert len(archive_hash) == 64  # SHA256 hash

            # Check suggested_remote_archives structure and content
            suggested_archives = package_result["suggested_remote_archives"]
            assert isinstance(suggested_archives, dict)
            assert "testrpm-0.1.tar.gz" in suggested_archives
            archive_suggestions = suggested_archives["testrpm-0.1.tar.gz"]
            assert isinstance(archive_suggestions, list)
            assert len(archive_suggestions) == 1
            suggestion = archive_suggestions[0]
            assert suggestion["remote_archive"] == "https://example.com/testrpm-0.1.tar.gz"
            assert suggestion["spec_source"] == "https://example.com/testrpm-0.1.tar.gz"
            assert suggestion["suggested_by"] == "test"
            assert suggestion["confidence"] == 1.0

            # Check suggested_remote_repos structure and content
            suggested_repos = package_result["suggested_remote_repos"]
            assert isinstance(suggested_repos, dict)
            assert "testrpm-0.1.tar.gz" in suggested_repos
            repo_suggestions = suggested_repos["testrpm-0.1.tar.gz"]
            assert isinstance(repo_suggestions, list)
            assert len(repo_suggestions) == 1
            repo_suggestion = repo_suggestions[0]
            assert repo_suggestion["repo"] == "https://github.com/example/testrpm"
            assert repo_suggestion["commit_hash"] == "abc123def456"
            assert repo_suggestion["tag"] == "v0.1"
            assert repo_suggestion["suggested_by"] == "test"
            assert repo_suggestion["confidence"] == 1.0

            # Check matched_remote_archives structure and content
            matched_archives = package_result["matched_remote_archives"]
            assert isinstance(matched_archives, dict)
            assert "testrpm-0.1.tar.gz" in matched_archives
            archive_matches = matched_archives["testrpm-0.1.tar.gz"]
            assert isinstance(archive_matches, list)
            assert len(archive_matches) == 1
            archive_match = archive_matches[0]
            assert archive_match["remote_archive"] == "https://example.com/testrpm-0.1.tar.gz"
            assert archive_match["accessible"] is True
            assert archive_match["matched"] is True
            assert archive_match["files_total"] == 1
            assert archive_match["files_matched"] == 1

            # Check matched_remote_repos structure and content
            matched_repos = package_result["matched_remote_repos"]
            assert isinstance(matched_repos, dict)
            assert "testrpm-0.1.tar.gz" in matched_repos
            repo_matches = matched_repos["testrpm-0.1.tar.gz"]
            assert isinstance(repo_matches, list)
            assert len(repo_matches) == 1
            repo_match = repo_matches[0]
            assert repo_match["remote_repo"] == "https://github.com/example/testrpm"
            assert repo_match["commit_hash"] == "abc123def456"
            assert repo_match["tag"] == "v0.1"
            assert repo_match["accessible"] is True

            # Test without output file
            assert 0 == main(["validate-system-packages", "-N", "-1"])

            # test validate-package command with the same mocked environment
            assert 0 == main(["validate-package", "-p", "testrpm"])
            assert 0 == main(
                [
                    "validate-package",
                    "-p",
                    "testrpm",
                    "--autotools-dir",
                    "./autotools-cache",
                    "--apply-autotools",
                ]
            )
            assert 0 == main(
                [
                    "validate-package",
                    "-p",
                    "testrpm",
                    "--autotools-dir",
                    "./autotools-cache",
                    "--no-apply-autotools",
                ]
            )

            # Test validate-package with output JSON
            output_json_path_package = Path(temp_dir) / "output_package.json"
            assert 0 == main(
                [
                    "validate-package",
                    "-p",
                    "testrpm",
                    "--output-json-path",
                    str(output_json_path_package),
                ]
            )

            # Verify the output JSON file for validate-package
            assert output_json_path_package.exists()
            with open(output_json_path_package, "r", encoding="utf-8") as f:
                package_output_data = json.load(f)

            # Check basic structure - validate-package returns a single object, not a list
            assert isinstance(package_output_data, dict)
            assert package_output_data["package_name"] == "testrpm"
            assert package_output_data["valid"] is True
            assert "upstream_code_repos" in package_output_data
            assert "suggested_remote_repos" in package_output_data
            assert "matched_remote_archives" in package_output_data
            assert "matched_remote_repos" in package_output_data

            # Check upstream_code_repos mapping
            upstream_repos = package_output_data["upstream_code_repos"]
            assert isinstance(upstream_repos, dict)
            assert "testrpm-0.1.tar.gz" in upstream_repos
            assert upstream_repos["testrpm-0.1.tar.gz"] == "https://github.com/example/testrpm"

            # Check upstream_archives mapping
            assert "upstream_archives" in package_output_data
            upstream_archives = package_output_data["upstream_archives"]
            assert isinstance(upstream_archives, dict)
            assert "testrpm-0.1.tar.gz" in upstream_archives
            assert (
                upstream_archives["testrpm-0.1.tar.gz"] == "https://example.com/testrpm-0.1.tar.gz"
            )

            # Check archive_hashes
            assert "archive_hashes" in package_output_data
            archive_hashes = package_output_data["archive_hashes"]
            assert isinstance(archive_hashes, dict)
            assert "testrpm-0.1.tar.gz" in archive_hashes
            archive_hash = archive_hashes["testrpm-0.1.tar.gz"]
            assert isinstance(archive_hash, str)
            assert len(archive_hash) == 64  # SHA256 hash

            # Check suggested_remote_archives structure and content
            suggested_archives = package_output_data["suggested_remote_archives"]
            assert isinstance(suggested_archives, dict)
            assert "testrpm-0.1.tar.gz" in suggested_archives
            archive_suggestions = suggested_archives["testrpm-0.1.tar.gz"]
            assert isinstance(archive_suggestions, list)
            assert len(archive_suggestions) == 1
            suggestion = archive_suggestions[0]
            assert suggestion["remote_archive"] == "https://example.com/testrpm-0.1.tar.gz"
            assert suggestion["spec_source"] == "https://example.com/testrpm-0.1.tar.gz"
            assert suggestion["suggested_by"] == "test"
            assert suggestion["confidence"] == 1.0

            # Check suggested_remote_repos structure and content
            suggested_repos = package_output_data["suggested_remote_repos"]
            assert isinstance(suggested_repos, dict)
            assert "testrpm-0.1.tar.gz" in suggested_repos
            repo_suggestions = suggested_repos["testrpm-0.1.tar.gz"]
            assert isinstance(repo_suggestions, list)
            assert len(repo_suggestions) == 1
            repo_suggestion = repo_suggestions[0]
            assert repo_suggestion["repo"] == "https://github.com/example/testrpm"
            assert repo_suggestion["commit_hash"] == "abc123def456"
            assert repo_suggestion["tag"] == "v0.1"
            assert repo_suggestion["suggested_by"] == "test"
            assert repo_suggestion["confidence"] == 1.0

            # Check matched_remote_archives structure and content
            matched_archives = package_output_data["matched_remote_archives"]
            assert isinstance(matched_archives, dict)
            assert "testrpm-0.1.tar.gz" in matched_archives
            archive_matches = matched_archives["testrpm-0.1.tar.gz"]
            assert isinstance(archive_matches, list)
            assert len(archive_matches) == 1
            archive_match = archive_matches[0]
            assert archive_match["remote_archive"] == "https://example.com/testrpm-0.1.tar.gz"
            assert archive_match["accessible"] is True
            assert archive_match["matched"] is True
            assert archive_match["files_total"] == 1
            assert archive_match["files_matched"] == 1

            # Check matched_remote_repos structure and content
            matched_repos = package_output_data["matched_remote_repos"]
            assert isinstance(matched_repos, dict)
            assert "testrpm-0.1.tar.gz" in matched_repos
            repo_matches = matched_repos["testrpm-0.1.tar.gz"]
            assert isinstance(repo_matches, list)
            assert len(repo_matches) == 1
            repo_match = repo_matches[0]
            assert repo_match["remote_repo"] == "https://github.com/example/testrpm"
            assert repo_match["commit_hash"] == "abc123def456"
            assert repo_match["tag"] == "v0.1"
            assert repo_match["accessible"] is True
