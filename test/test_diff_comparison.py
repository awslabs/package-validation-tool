# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for diff comparison functionality."""

import json
import tempfile
from pathlib import Path

from package_validation_tool.matching.diff_comparison import (
    ArchiveDiffComparison,
    DiffComparisonResult,
    compare_diffs_directories,
)


def test_identical_diffs():
    """Test that identical diffs directories are detected as identical."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_a = Path(tmpdir) / "a" / "pkg" / "pkg-1.0.tar.gz"
        dir_b = Path(tmpdir) / "b" / "pkg" / "pkg-1.0.tar.gz"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        # Create identical diff files
        (dir_a / "file.txt.arch").write_text("content")
        (dir_a / "file.txt.repo").write_text("other")
        (dir_b / "file.txt.arch").write_text("content")
        (dir_b / "file.txt.repo").write_text("other")

        result = compare_diffs_directories(
            str(Path(tmpdir) / "a"),
            str(Path(tmpdir) / "b"),
            package_name="pkg",
        )
        assert result is True


def test_different_content():
    """Test that different file content is detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_a = Path(tmpdir) / "a" / "pkg" / "pkg-1.0.tar.gz"
        dir_b = Path(tmpdir) / "b" / "pkg" / "pkg-1.0.tar.gz"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        # Create diff files with different content
        (dir_a / "file.txt.arch").write_text("content_a")
        (dir_b / "file.txt.arch").write_text("content_b")

        result = compare_diffs_directories(
            str(Path(tmpdir) / "a"),
            str(Path(tmpdir) / "b"),
            package_name="pkg",
        )
        assert result is False


def test_file_only_in_one_dir():
    """Test that files present in only one directory are detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_a = Path(tmpdir) / "a" / "pkg" / "pkg-1.0.tar.gz"
        dir_b = Path(tmpdir) / "b" / "pkg" / "pkg-1.0.tar.gz"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        # File only in dir_a
        (dir_a / "file.txt.arch").write_text("content")

        result = compare_diffs_directories(
            str(Path(tmpdir) / "a"),
            str(Path(tmpdir) / "b"),
            package_name="pkg",
        )
        assert result is False


def test_json_output():
    """Test that JSON output is written correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_a = Path(tmpdir) / "a" / "pkg" / "pkg-1.0.tar.gz"
        dir_b = Path(tmpdir) / "b" / "pkg" / "pkg-1.0.tar.gz"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        (dir_a / "file.txt.arch").write_text("a")
        (dir_b / "file.txt.arch").write_text("b")

        output_path = Path(tmpdir) / "result.json"
        compare_diffs_directories(
            str(Path(tmpdir) / "a"),
            str(Path(tmpdir) / "b"),
            package_name="pkg",
            output_json_path=str(output_path),
        )

        assert output_path.exists()
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["identical"] is False
        assert "pkg-1.0.tar.gz" in data["archives_compared"]


def test_nonexistent_directory():
    """Test handling of nonexistent directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = compare_diffs_directories(
            str(Path(tmpdir) / "nonexistent_a"),
            str(Path(tmpdir) / "nonexistent_b"),
        )
        assert result is False


def test_empty_directories():
    """Test comparison of empty directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_a = Path(tmpdir) / "a"
        dir_b = Path(tmpdir) / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        result = compare_diffs_directories(str(dir_a), str(dir_b))
        assert result is True


def test_archive_diff_comparison_identical():
    """Test ArchiveDiffComparison.identical property."""
    diff = ArchiveDiffComparison()
    assert diff.identical is True

    diff.files_only_in_a = ["file.txt"]
    assert diff.identical is False


def test_diff_comparison_result_post_init():
    """Test DiffComparisonResult reconstructs nested objects from dicts."""
    result = DiffComparisonResult(
        identical=False,
        package_name="pkg",
        archives_compared=["archive.tar.gz"],
        differences={"archive.tar.gz": {"files_only_in_a": ["test.txt"]}},
    )
    assert isinstance(result.differences["archive.tar.gz"], ArchiveDiffComparison)
    assert result.differences["archive.tar.gz"].files_only_in_a == ["test.txt"]
