# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import tarfile
import tempfile
from pathlib import Path

from package_validation_tool.cli import main

TEST_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
PROJECT_DIR = Path(TEST_DIR_PATH).parent.absolute()

MATCH_ARTEFACTS_DIR = Path(TEST_DIR_PATH) / "artefacts" / "match_examples"


def test_match_files_matching():
    """Test full app for matching plain files"""
    plain_file = str(MATCH_ARTEFACTS_DIR / "plain.txt")
    date_file = str(MATCH_ARTEFACTS_DIR / "plain_with_dates.txt")
    other_date_file = str(MATCH_ARTEFACTS_DIR / "plain_with_other_dates.txt")

    # matching the same file works as expected
    assert 0 == main(["match-files", "--left", plain_file, "--right", plain_file])
    assert 0 == main(["match-files", "--left", date_file, "--right", date_file])
    assert 0 == main(["match-files", "--left", date_file, "--right", other_date_file])

    # match entire directory with files
    assert 0 == main(
        ["match-files", "--left", str(MATCH_ARTEFACTS_DIR), "--right", str(MATCH_ARTEFACTS_DIR)]
    )


def test_match_files_non_matching():
    """Test full app for matching plain files"""
    plain_file = str(MATCH_ARTEFACTS_DIR / "plain.txt")
    date_file = str(MATCH_ARTEFACTS_DIR / "plain_with_dates.txt")

    # different files should not match
    assert 0 != main(["match-files", "--left", plain_file, "--right", date_file])

    # file and directory should not match
    assert 0 != main(["match-files", "--left", plain_file, "--right", str(MATCH_ARTEFACTS_DIR)])


def test_match_files_match_tars():
    """Test full app for matching archive files"""
    plain_file = MATCH_ARTEFACTS_DIR / "plain.txt"
    date_file = MATCH_ARTEFACTS_DIR / "plain_with_dates.txt"

    # create a temporary directory, automatically delete it once we are done
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)

        # create the first tar.gz archive with only plain_file
        plain_archive_path = temp_dir_path.resolve() / "plain.tar.gz"
        with tarfile.open(str(plain_archive_path), "w:gz") as tar:
            tar.add(str(plain_file), arcname=plain_file.name)

        # create the second tar.gz archive with both plain_file and date_file
        combined_archive_path = temp_dir_path.resolve() / "combined.tar.gz"
        with tarfile.open(str(combined_archive_path), "w:gz") as tar:
            tar.add(str(plain_file), arcname=plain_file.name)
            tar.add(str(date_file), arcname=date_file.name)

        # same files match
        assert 0 == main(
            [
                "match-files",
                "--left",
                str(combined_archive_path),
                "--right",
                str(combined_archive_path),
            ]
        )
        # archives with a subset can be matched with an archive that has the superset
        assert 0 == main(
            [
                "match-files",
                "--left",
                str(plain_archive_path),
                "--right",
                str(combined_archive_path),
            ]
        )

        # supersets in archives cannot be matched by subset archives
        assert 0 != main(
            [
                "match-files",
                "--left",
                str(combined_archive_path),
                "--right",
                str(plain_archive_path),
            ]
        )
