import tempfile
from pathlib import Path
from unittest.mock import mock_open, patch

from package_validation_tool.matching.changelog import ChangelogGenerator, ChangelogRunner


def test_run_changelog_generation_already_exists():
    """Test run_changelog_generation when changelog already exists in source repo."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        # Create changelog in source repo
        src_changelog = src_repo_dir / "ChangeLog"
        src_changelog.write_text("existing changelog content")

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        # Should return True when changelog already exists
        assert runner.run_changelog_generation()


def test_run_changelog_generation_no_archive_changelog():
    """Test run_changelog_generation when no changelog exists in package archive."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories without changelog files
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        # Should return True when no archive changelog exists
        assert runner.run_changelog_generation()


def test_run_changelog_generation_format_detection_failure():
    """Test run_changelog_generation when format detection fails (Unknown generator)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create directories
        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        # Create changelog in archive only
        archive_changelog = package_archive_dir / "ChangeLog"
        archive_changelog.write_text("some content without detectable format")

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        # Should return False when format detection fails (returns Unknown generator)
        assert not runner.run_changelog_generation()


def test_analyze_changelog_format_oneline():
    """Test _analyze_changelog_format detecting oneline format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        oneline_content = "abcd123456789012345678901234567890123456 Initial commit\nabcd123456789012345678901234567890123457 Fix bug\n"

        with patch(
            "package_validation_tool.matching.changelog.open", mock_open(read_data=oneline_content)
        ):
            generator, args = runner._analyze_changelog_format(Path("test.log"))
            assert generator == ChangelogGenerator.GitLog
            assert args == "--pretty=oneline"


def test_analyze_changelog_format_full():
    """Test _analyze_changelog_format detecting full format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        full_content = """commit abcd123456789012345678901234567890123456
Author: Test User <test@example.com>
Commit: Test User <test@example.com>

    Initial commit
"""

        with patch(
            "package_validation_tool.matching.changelog.open", mock_open(read_data=full_content)
        ):
            generator, args = runner._analyze_changelog_format(Path("test.log"))
            assert generator == ChangelogGenerator.GitLog
            assert args == "--pretty=full"


def test_analyze_changelog_format_medium():
    """Test _analyze_changelog_format detecting medium format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        medium_content = """commit abcd123456789012345678901234567890123456
Author: Test User <test@example.com>
Date:   Mon Jan 1 12:00:00 2024 +0000

    Initial commit
"""

        with patch(
            "package_validation_tool.matching.changelog.open", mock_open(read_data=medium_content)
        ):
            generator, args = runner._analyze_changelog_format(Path("test.log"))
            assert generator == ChangelogGenerator.GitLog
            assert args == "--pretty=medium"


def test_analyze_changelog_format_short():
    """Test _analyze_changelog_format detecting short format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        short_content = """commit abcd123456789012345678901234567890123456
Author: Test User <test@example.com>

    Initial commit
"""

        with patch(
            "package_validation_tool.matching.changelog.open", mock_open(read_data=short_content)
        ):
            generator, args = runner._analyze_changelog_format(Path("test.log"))
            assert generator == ChangelogGenerator.GitLog
            assert args == "--pretty=short"


def test_analyze_changelog_format_abbreviated_hash():
    """Test _analyze_changelog_format detecting abbreviated hash format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        abbreviated_content = "abcd123 Initial commit\nef456789 Fix bug\n"

        with patch(
            "package_validation_tool.matching.changelog.open",
            mock_open(read_data=abbreviated_content),
        ):
            generator, args = runner._analyze_changelog_format(Path("test.log"))
            assert generator == ChangelogGenerator.GitLog
            assert args == "--pretty=format:%h %s"


def test_analyze_changelog_format_unknown():
    """Test _analyze_changelog_format returning Unknown for unrecognized format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        no_hash_content = "Some changelog content without git hashes\nAnother line\n"

        with patch(
            "package_validation_tool.matching.changelog.open", mock_open(read_data=no_hash_content)
        ):
            generator, args = runner._analyze_changelog_format(Path("test.log"))
            assert generator == ChangelogGenerator.Unknown
            assert args is None


def test_analyze_changelog_format_file_error():
    """Test _analyze_changelog_format when file reading fails."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        with patch(
            "package_validation_tool.matching.changelog.open",
            side_effect=IOError("File read error"),
        ):
            generator, args = runner._analyze_changelog_format(Path("test.log"))
            assert generator == ChangelogGenerator.Unknown
            assert args is None


def test_truncate_changelog_file_success():
    """Test successful _truncate_changelog_file."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        # Create source directory and changelog file
        src_repo_dir.mkdir()
        target_path = src_repo_dir / "ChangeLog"
        target_path.write_text("This is a long changelog content that needs to be truncated")

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        # Truncate to 20 bytes
        result = runner._truncate_changelog_file(target_path, 20)
        assert result is True

        # Verify file was truncated
        assert target_path.stat().st_size == 20


def test_initialization():
    """Test ChangelogRunner initialization."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        src_repo_dir = temp_path / "src"
        package_archive_dir = temp_path / "archive"

        src_repo_dir.mkdir()
        package_archive_dir.mkdir()

        runner = ChangelogRunner(str(src_repo_dir), str(package_archive_dir))

        # Verify paths are resolved correctly
        assert runner.src_repo_dir == src_repo_dir.resolve()
        assert runner.package_archive_dir == package_archive_dir.resolve()


def test_changelog_generator_enum():
    """Test ChangelogGenerator enum values."""
    assert ChangelogGenerator.Unknown.value == "unknown"
    assert ChangelogGenerator.GitLog.value == "git_log"

    # Test that we have exactly the expected enum values
    assert len(ChangelogGenerator) == 2
    assert set(ChangelogGenerator) == {ChangelogGenerator.Unknown, ChangelogGenerator.GitLog}
