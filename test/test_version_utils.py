# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
from unittest.mock import MagicMock, patch

from package_validation_tool.package.suggesting_repos.version_utils import (
    extract_version_from_archive_name,
    verify_commit_exists,
    verify_tag_exists,
)
from package_validation_tool.utils import clone_git_repo


def test_extract_version_from_archive_name():
    """Test extract_version_from_archive_name with various archive names."""
    test_cases = [
        # archive_name, expected_version, expected_date, expected_suffix, expected_is_commit_hash
        ("acl-2.3.1.tar.gz", "2_3_1", "", "", False),
        ("bash-5.2.tar.gz", "5_2", "", "", False),
        ("json-c-0.14-20200419.tar.gz", "0_14", "20200419", "", False),
        ("openssh-8.7p1.tar.gz", "8_7", "", "1", False),
        ("cups-2.4.11-source.tar.gz", "2_4_11", "", "source", False),
        ("libevent-2.1.12-stable.tar.gz", "2_1_12", "", "stable", False),
        ("sqlite-autoconf-3400000.tar.gz", "3400000", "", "", False),
        ("v2.2.0.tar.gz", "2_2_0", "", "", False),
        # Add a test case with a commit hash
        ("example-abcdef123456.tar.gz", "abcdef123456", "", "", True),
        # Add a test case with a g-prefixed commit hash (from git-describe)
        ("glibc-2.42-21-g7a8f3c6ee4.tar.xz", "7a8f3c6ee4", "", "", True),
    ]

    for (
        archive_name,
        expected_version,
        expected_date,
        expected_suffix,
        expected_is_commit_hash,
    ) in test_cases:
        version_info = extract_version_from_archive_name(archive_name)
        assert version_info.version == expected_version
        assert version_info.date == expected_date
        assert version_info.suffix == expected_suffix
        assert version_info.is_commit_hash == expected_is_commit_hash


def test_combined_workflow():
    """
    Test the combined workflow of extract_version_from_archive_name + verify_commit_exists +
    verify_tag_exists.
    """
    test_cases = [
        # archive_name, repo_url, expected_tag, expected_commit_hash
        # Standard version format
        (
            "acl-2.3.1.tar.gz",
            "https://git.savannah.gnu.org/git/acl.git",
            "v2.3.1",
            "abcdef1234567890",
        ),
        # Version with date component
        (
            "json-c-0.14-20200419.tar.gz",
            "https://github.com/json-c/json-c",
            "json-c-0.14-20200419",
            "abcdef1234567891",
        ),
        # Version with source suffix
        (
            "cups-2.4.11-source.tar.gz",
            "https://github.com/OpenPrinting/cups",
            "v2.4.11",
            "abcdef1234567892",
        ),
        # Version with stable suffix
        (
            "libevent-2.1.12-stable.tar.gz",
            "https://github.com/libevent/libevent",
            "release-2.1.12-stable",
            "abcdef1234567893",
        ),
        # Version starting with v
        ("v2.2.0.tar.gz", "https://github.com/aws/amazon-ec2-utils", "v2.2.0", "abcdef1234567894"),
        # Version with p suffix (OpenSSH style)
        (
            "openssh-8.7p1.tar.gz",
            "https://github.com/openssh/openssh-portable",
            "V_8_7_P1",
            "abcdef1234567895",
        ),
        # Version with numeric version only (SQLite style)
        (
            "sqlite-autoconf-3400000.tar.gz",
            "https://github.com/sqlite/sqlite",
            "version-3.40.0",
            "abcdef1234567896",
        ),
        # Version with hobbled suffix
        (
            "nettle-3.10.1-hobbled.tar.xz",
            "https://github.com/gnutls/nettle",
            "nettle_3.10.1_release_20241230",
            "abcdef1234567897",
        ),
        # Version with multiple sub-versions
        (
            "amazon-corretto-source-23.0.2.7.1.tar.gz",
            "https://github.com/corretto/corretto-23.git",
            "23.0.2.7.1",
            "abcdef1234567898",
        ),
        # Version with multiple components
        (
            "gcc-11.5.0-20240719.tar.xz",
            "https://github.com/gcc-mirror/gcc",
            "releases/gcc-11.5.0",
            "abcdef1234567899",
        ),
        # Version with commit hash
        (
            "clknetsim-f00531.tar.gz",
            "https://gitlab.com/chrony/clknetsim",
            "f00531bc9f652a6eb6ecfe0ad73da511c08c9936",
            "f00531bc9f652a6eb6ecfe0ad73da511c08c9936",
        ),
        # Version with g-prefixed commit hash (from git-describe)
        (
            "example-gf00531.tar.gz",
            "https://github.com/example/example",
            "f00531bc9f652a6eb6ecfe0ad73da511c08c9936",
            "f00531bc9f652a6eb6ecfe0ad73da511c08c9936",
        ),
    ]

    # Create a temporary directory to simulate a git repo
    with tempfile.TemporaryDirectory() as temp_dir:
        # Mock the clone_git_repo function
        with patch("package_validation_tool.utils.clone_git_repo") as mock_clone_git_repo:
            # Configure mock to simulate successful cloning
            def mock_clone_side_effect(repo, _target_dir=None, _bare=False):
                # Create a unique directory for each repo URL
                repo_hash = str(hash(repo))
                repo_dir = os.path.join(temp_dir, repo_hash)
                os.makedirs(repo_dir, exist_ok=True)
                return True, repo_dir

            mock_clone_git_repo.side_effect = mock_clone_side_effect

            # Mock subprocess.run for git commands
            with patch("subprocess.run") as mock_run:
                # Configure mock to simulate successful tag/commit verification
                def mock_run_side_effect(*args, **_kwargs):
                    mock_result = MagicMock()
                    mock_result.returncode = 0

                    # Handle git tag command for local repo
                    if args[0][0:3] == ["git", "tag", "--list"]:
                        mock_result.stdout = """
                        abcdef1234567890 v2.3.1
                        abcdef1234567891 json-c-0.14-20200419
                        abcdef1234567892 v2.4.11
                        abcdef1234567893 release-2.1.12-stable
                        abcdef1234567894 v2.2.0
                        abcdef1234567895 V_8_7_P1
                        abcdef1234567896 version-3.40.0
                        abcdef1234567897 nettle_3.10.1_release_20241230
                        abcdef1234567898 23.0.2.7.1
                        abcdef1234567899 releases/gcc-11.5.0
                        """
                    # Handle git rev-parse for commit verification
                    elif args[0][0:2] == ["git", "rev-parse"]:
                        if args[0][3] == "f00531":
                            mock_result.stdout = "f00531bc9f652a6eb6ecfe0ad73da511c08c9936"
                        else:
                            # For any other commit hash, return empty (not found)
                            mock_result.stdout = ""

                    return mock_result

                mock_run.side_effect = mock_run_side_effect

                for archive, repo, expected_tag, expected_commit_hash in test_cases:
                    version_info = extract_version_from_archive_name(archive)

                    success, repo_dir = clone_git_repo(repo, bare=True)
                    assert success is True

                    if version_info.is_commit_hash:
                        commit_hash = verify_commit_exists(repo_dir, version_info.version)
                        assert commit_hash == expected_commit_hash
                    else:
                        commit_hash, tag = verify_tag_exists(
                            archive,
                            repo_dir,
                            version_info.version,
                            version_info.date,
                            version_info.suffix,
                        )
                        assert commit_hash == expected_commit_hash
                        assert tag == expected_tag
