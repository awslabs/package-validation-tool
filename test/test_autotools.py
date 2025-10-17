# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# pylint: disable=protected-access

import tempfile
from pathlib import Path
from unittest.mock import patch

from package_validation_tool.matching import AUTOTOOLS_PATCHES_DIR
from package_validation_tool.matching.autotools import (
    DEFAULT_AUTOCONF_VERSION,
    DEFAULT_AUTOMAKE_VERSION,
    DEFAULT_GETTEXT_VERSION,
    DEFAULT_LIBTOOL_VERSION,
    AutotoolsRunner,
)


def test_run_autotools_no_autotools_project():
    """Test run_autotools when project doesn't use Autotools."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories without autotools files
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        # Should return True for non-autotools projects
        assert runner.run_autotools()


def test_run_autotools_download_failure():
    """Test run_autotools when download fails."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories and autotools files
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        # Create configure.ac to indicate autotools usage
        configure_ac = src_repo_dir / "configure.ac"
        configure_ac.write_text("AC_INIT([test], [1.0])\n")

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        with patch.object(
            runner,
            "_detect_autotools_versions",
            return_value={
                "automake": "1.16.5",
                "autoconf": "2.69",
                "gettext": "0.21",
                "libtool": "2.4.7",
            },
        ), patch.object(runner, "_download_autotools_packages", return_value=False), patch.object(
            runner, "_verify_checksum", return_value=True
        ):

            # Call run_autotools to populate the private fields
            assert not runner.run_autotools()

            # Test that the detected versions are stored in private fields
            detected_versions = runner.get_detected_versions()
            expected = {
                "automake": "1.16.5",
                "autoconf": "2.69",
                "gettext": "0.21",
                "libtool": "2.4.7",
            }
            assert detected_versions == expected


def test_run_autotools_default_versions():
    """Test run_autotools uses default versions when detection fails."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories and autotools files
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        # Create configure.ac to indicate autotools usage
        configure_ac = src_repo_dir / "configure.ac"
        configure_ac.write_text("AC_INIT([test], [1.0])\n")

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        with patch.object(
            runner,
            "_detect_autotools_versions",
            return_value={"automake": None, "autoconf": None, "gettext": None, "libtool": None},
        ), patch.object(runner, "_download_autotools_packages", return_value=True), patch.object(
            runner, "_verify_checksum", return_value=True
        ), patch.object(
            runner,
            "_install_autotools_packages",
            return_value={
                "automake": "/path/automake/bin",
                "autoconf": "/path/autoconf/bin",
                "gettext": "/path/gettext/bin",
                "libtool": "/path/libtool/bin",
            },
        ), patch.object(
            runner, "_generate_autotools_files", return_value=True
        ):

            assert runner.run_autotools()

            # Verify paths are set correctly
            assert autotools_dir.exists()
            assert runner.autotools_dir == autotools_dir.resolve()
            assert runner.src_repo_dir == src_repo_dir.resolve()
            assert runner.package_archive_dir == package_archive_dir.resolve()

            # Test that default versions are used when detection returns None
            detected_versions = runner.get_detected_versions()
            expected = {
                "automake": DEFAULT_AUTOMAKE_VERSION,
                "autoconf": DEFAULT_AUTOCONF_VERSION,
                "gettext": DEFAULT_GETTEXT_VERSION,
                "libtool": DEFAULT_LIBTOOL_VERSION,
            }
            assert detected_versions == expected


@patch("package_validation_tool.matching.autotools.is_url_accessible")
def test_run_autotools_url_not_accessible(mock_is_url_accessible):
    """Test run_autotools when package URLs are not accessible."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories and autotools files
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        # Create configure.ac to indicate autotools usage
        configure_ac = src_repo_dir / "configure.ac"
        configure_ac.write_text("AC_INIT([test], [1.0])\n")

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        # Mock URL accessibility to return False
        mock_is_url_accessible.return_value = False

        with patch.object(
            runner,
            "_detect_autotools_versions",
            return_value={
                "automake": "1.16.5",
                "autoconf": "2.69",
                "gettext": "0.21",
                "libtool": "2.4.7",
            },
        ), patch.object(runner, "_verify_checksum", return_value=True):
            assert not runner.run_autotools()


def test_run_autotools_multiple_autotools_files():
    """Test run_autotools detects autotools when multiple indicator files are present."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories and multiple autotools files
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        # Create both configure.ac and Makefile.am
        configure_ac = src_repo_dir / "configure.ac"
        configure_ac.write_text("AC_INIT([test], [1.0])\n")
        makefile_am = src_repo_dir / "Makefile.am"
        makefile_am.write_text("SUBDIRS = src\n")

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        with patch.object(
            runner,
            "_detect_autotools_versions",
            return_value={
                "automake": "1.16.5",
                "autoconf": "2.69",
                "gettext": "0.21",
                "libtool": "2.4.7",
            },
        ), patch.object(runner, "_download_autotools_packages", return_value=True), patch.object(
            runner, "_verify_checksum", return_value=True
        ), patch.object(
            runner,
            "_install_autotools_packages",
            return_value={
                "automake": "/path/automake/bin",
                "autoconf": "/path/autoconf/bin",
                "gettext": "/path/gettext/bin",
                "libtool": "/path/libtool/bin",
            },
        ), patch.object(
            runner, "_generate_autotools_files", return_value=True
        ):

            assert runner.run_autotools()


def test_run_autotools_existing_archive_files():
    """Test run_autotools when archive files already exist locally."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories and autotools files
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()
        autotools_dir.mkdir(parents=True)

        # Create configure.ac to indicate autotools usage
        configure_ac = src_repo_dir / "configure.ac"
        configure_ac.write_text("AC_INIT([test], [1.0])\n")

        # Create existing archive files
        automake_archive = autotools_dir / "automake-1.16.5.tar.gz"
        autoconf_archive = autotools_dir / "autoconf-2.69.tar.gz"
        gettext_archive = autotools_dir / "gettext-0.21.tar.gz"
        libtool_archive = autotools_dir / "libtool-2.4.7.tar.gz"
        automake_archive.touch()
        autoconf_archive.touch()
        gettext_archive.touch()
        libtool_archive.touch()

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        with patch.object(
            runner,
            "_detect_autotools_versions",
            return_value={
                "automake": "1.16.5",
                "autoconf": "2.69",
                "gettext": "0.21",
                "libtool": "2.4.7",
            },
        ), patch.object(
            runner,
            "_install_autotools_packages",
            return_value={
                "automake": "/path/automake/bin",
                "autoconf": "/path/autoconf/bin",
                "gettext": "/path/gettext/bin",
                "libtool": "/path/libtool/bin",
            },
        ), patch.object(
            runner, "_verify_checksum", return_value=True
        ), patch.object(
            runner, "_generate_autotools_files", return_value=True
        ), patch(
            "package_validation_tool.matching.autotools.is_url_accessible"
        ) as mock_is_url_accessible, patch(
            "package_validation_tool.matching.autotools.download_file"
        ) as mock_download_file:

            assert runner.run_autotools()

            # Verify download functions were not called since files already exist
            mock_is_url_accessible.assert_not_called()
            mock_download_file.assert_not_called()


def test_autoconf_patch_file_exists():
    """Test that the required autoconf patch file exists and contains valid patch content."""
    patch_file = AUTOTOOLS_PATCHES_DIR / "autoconf-2.69-backport-runstatedir-option.patch"

    # Verify the patch file exists
    assert patch_file.is_file(), f"Expected patch file not found at: {patch_file}"

    # Verify the file contains patch content by checking for common patch markers
    with open(patch_file, "r", encoding="utf-8") as f:
        patch_content = f.read()

    # A valid patch file should contain these common patch markers
    patch_indicators = [
        "diff --git",  # Git diff header
        "@@",  # Hunk headers
        "+++",  # New file indicator
        "---",  # Old file indicator
    ]

    for indicator in patch_indicators:
        assert indicator in patch_content, f"Patch file missing expected marker: {indicator}"

    # Additionally verify it's not empty
    assert len(patch_content.strip()) > 0, "Patch file appears to be empty"


def test_verify_checksum_success():
    """Test _verify_checksum method with successful verification."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        # Create a test file with known content
        test_file = autotools_dir / "test-file.tar.gz"
        test_content = b"test content for checksum verification"
        test_file.write_bytes(test_content)

        # Calculate expected checksum
        import hashlib

        expected_checksum = hashlib.sha256(test_content).hexdigest()

        # Mock TOOL_CONFIGS to include our test file
        with patch(
            "package_validation_tool.matching.autotools.TOOL_CONFIGS",
            {"test": {"sha256_hashsums": {"test-file.tar.gz": expected_checksum}}},
        ):
            # Verification should succeed
            result = runner._verify_checksum("test", "test-file.tar.gz", test_file)
            assert result is True


def test_verify_checksum_failure():
    """Test _verify_checksum method with failed verification."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        # Create a test file with known content
        test_file = autotools_dir / "test-file.tar.gz"
        test_content = b"test content for checksum verification"
        test_file.write_bytes(test_content)

        # Mock TOOL_CONFIGS with wrong checksum
        wrong_checksum = "wrong_checksum_value"
        with patch(
            "package_validation_tool.matching.autotools.TOOL_CONFIGS",
            {"test": {"sha256_hashsums": {"test-file.tar.gz": wrong_checksum}}},
        ):
            # Verification should fail
            result = runner._verify_checksum("test", "test-file.tar.gz", test_file)
            assert result is False


def test_version_detection_and_post_processing():
    """Test complex version detection with new regex patterns and post-processing logic."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        # Test cases: (filename, file_content, expected_cleaned_version)
        test_cases = [
            # automake - test complex versions with post-processing
            ("aclocal.m4", "generated automatically by aclocal 1.16.5", "1.16.5"),
            (
                "aclocal.m4",
                "generated automatically by aclocal 2.4.6.42-b88ce-dirty",
                "2.4.6.42-b88ce",
            ),
            ("aclocal.m4", "generated automatically by aclocal 1.16.5-beta-dirty", "1.16.5-beta"),
            ("aclocal.m4", "generated automatically by aclocal 2.69a.", "2.69a"),  # trailing dot
            (
                "aclocal.m4",
                "generated automatically by aclocal 1.16.5-amzn,",
                "1.16.5-amzn",
            ),  # trailing comma
            # autoconf - test complex versions with post-processing
            ("configure", "Generated by GNU Autoconf 2.69", "2.69"),
            ("configure", "Generated by GNU Autoconf 2.4.6.42-b88ce-dirty", "2.4.6.42-b88ce"),
            ("configure", "Generated by GNU Autoconf 2.72-beta]", "2.72-beta"),  # trailing bracket
            ("configure", "Generated by GNU Autoconf 2.69-dirty", "2.69"),
            # gettext - test complex versions with post-processing
            ("gettext.m4", "gettext-0.21", "0.21"),
            ("gettext.m4", "gettext-0.22.5-patched-dirty", "0.22.5-patched"),
            ("gettext.m4", "gettext-0.21.1-rc1...", "0.21.1-rc1"),  # multiple trailing dots
            # libtool - test complex versions with post-processing
            ("ltmain.sh", "libtool (GNU libtool) 2.4.7", "2.4.7"),
            ("ltmain.sh", "libtool (GNU libtool) 2.4.7-rc1-dirty", "2.4.7-rc1"),
            ("ltmain.sh", "libtool (GNU libtool) 2.5.3-git-123abc-dirty", "2.5.3-git-123abc"),
            (
                "ltmain.sh",
                "libtool (GNU libtool) 2.4.6.42-b88ce.",
                "2.4.6.42-b88ce",
            ),  # trailing dot
        ]

        for filename, file_content, expected_version in test_cases:
            # Create the test file
            test_file = package_archive_dir / filename
            test_file.write_text(file_content + "\n")

            # Run full version detection which includes post-processing
            versions = runner._detect_autotools_versions()

            # Determine which tool this file corresponds to
            if filename == "aclocal.m4":
                tool = "automake"
            elif filename == "configure":
                tool = "autoconf"
            elif filename == "gettext.m4":
                tool = "gettext"
            elif filename == "ltmain.sh":
                tool = "libtool"
            else:
                continue

            detected_version = versions.get(tool)
            assert detected_version == expected_version, (
                f"Tool {tool}, file {filename}: "
                f"Content '{file_content}' -> "
                f"Expected '{expected_version}', got '{detected_version}'"
            )

            # Clean up for next test
            test_file.unlink()

        # Test all tools together with complex versions
        test_files = {
            "aclocal.m4": "generated automatically by aclocal 1.16i",
            "configure": "Generated by GNU Autoconf 2.69.",
            "gettext.m4": "gettext-0.18.2)",
            "ltmain.sh": "libtool (GNU libtool) 2.4.6.42-b88ce-dirty",
        }

        expected_versions = {
            "automake": "1.16i",  # letters are not removed
            "autoconf": "2.69",  # dots are removed
            "gettext": "0.18.2",  # brackets are removed
            "libtool": "2.4.6.42-b88ce",  # -dirty removed, git-based version recognized
        }

        # Create all test files
        for filename, content in test_files.items():
            test_file = package_archive_dir / filename
            test_file.write_text(content + "\n")

        # Run detection on all files
        versions = runner._detect_autotools_versions()

        # Verify all versions were detected and cleaned correctly
        for tool, expected_version in expected_versions.items():
            detected_version = versions[tool]
            assert detected_version == expected_version, (
                f"Multi-tool test - Tool {tool}: "
                f"expected '{expected_version}', got '{detected_version}'"
            )


def test_verify_checksum_no_expected_checksum():
    """Test _verify_checksum method when no expected checksum is available."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        autotools_dir = temp_path / "autotools"
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = AutotoolsRunner(str(autotools_dir), str(src_repo_dir), str(package_archive_dir))

        # Create a test file
        test_file = autotools_dir / "test-file.tar.gz"
        test_file.write_bytes(b"test content")

        # Mock TOOL_CONFIGS without checksum for this file
        with patch(
            "package_validation_tool.matching.autotools.TOOL_CONFIGS",
            {"test": {"sha256_hashsums": {}}},  # No checksum available
        ):
            # Should return False when no checksum is available
            result = runner._verify_checksum("test", "test-file.tar.gz", test_file)
            assert result is False
