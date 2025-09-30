# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from package_validation_tool.utils import (
    DEFAULT_REQUEST_HEADERS,
    checkout_in_git_repo,
    clone_git_repo,
    download_file,
    extract_links,
    get_archive_files,
    get_git_tree_hash,
    hash256sum,
    is_url_accessible,
    remove_archive_suffix,
    secure_tar_extractall,
    secure_unpack_archive,
    versions_is_greater,
)

TEST_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
PROJECT_DIR = Path(TEST_DIR_PATH).parent.absolute()

ARTEFACTS_DIR = Path(TEST_DIR_PATH) / "artefacts" / "utils_examples"


def test_remove_archive_suffix():
    """Test the remove_archive_suffix function"""
    file = "test_file.txt"
    assert remove_archive_suffix(file) == "test_file"
    file = "test_file.tar"
    assert remove_archive_suffix(file) == "test_file"
    file = "test_file.tar.gz"
    assert remove_archive_suffix(file) == "test_file"
    file = "test_file.weird.ext"
    assert remove_archive_suffix(file) == "test_file.weird"


@patch("package_validation_tool.utils.requests")
def test_is_url_accessible_success(mock_requests):
    """Test the is_url_accessible function for a successful HTTP download"""
    file_url = "https://example.com/test_file.txt"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.url = file_url
    mock_requests.get.return_value = mock_response

    assert is_url_accessible(file_url)


@patch("package_validation_tool.utils.requests")
def test_is_url_accessible_failure(mock_requests):
    """Test the is_url_accessible function for a failed HTTP download"""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_requests.get.return_value = mock_response

    file_url = "https://example.com/test_file.txt"
    assert not is_url_accessible(file_url)


def test_download_file_http_success():
    """Test the download_file function for a successful HTTP download"""
    file_url = "https://example.com/test_file.txt"
    with tempfile.TemporaryDirectory() as temp_dir:
        local_file_path = Path(temp_dir) / "test_file.txt"

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"Test content"
            assert download_file(file_url, str(local_file_path))


def test_download_file_http_failure():
    """Test the download_file function for a failed HTTP download"""
    file_url = "https://example.com/test_file.txt"
    with tempfile.TemporaryDirectory() as temp_dir:
        local_file_path = Path(temp_dir) / "test_file.txt"

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Network error")
            assert not download_file(file_url, str(local_file_path))


def test_download_file_ftp_success():
    """Test the download_file function for a successful FTP download"""
    file_url = "ftp://example.com/test_file.txt"
    with tempfile.TemporaryDirectory() as temp_dir:
        local_file_path = Path(temp_dir) / "test_file.txt"

        with patch("urllib.request.urlretrieve") as mock_urlretrieve:
            assert download_file(file_url, str(local_file_path))
            mock_urlretrieve.assert_called_once_with(file_url, str(local_file_path))


def test_download_file_ftp_failure():
    """Test the download_file function for a failed FTP download"""
    file_url = "ftp://example.com/test_file.txt"
    with tempfile.TemporaryDirectory() as temp_dir:
        local_file_path = Path(temp_dir) / "test_file.txt"

        with patch("urllib.request.urlretrieve") as mock_urlretrieve:
            mock_urlretrieve.side_effect = Exception("FTP error")
            assert not download_file(file_url, str(local_file_path))


def test_download_file_unsupported_protocol():
    """Test the download_file function for an unsupported protocol"""
    file_url = "file:///test_file.txt"
    with tempfile.TemporaryDirectory() as temp_dir:
        local_file_path = Path(temp_dir) / "test_file.txt"
        assert not download_file(file_url, str(local_file_path))


def test_get_archive_files():
    """Test the get_archive_files function"""
    with tempfile.TemporaryDirectory() as temp_dir:
        directory = Path(temp_dir)
        test_files = [
            "test_file.tar.gz",
            "test_file.tgz",
            "test_file.tar.xz",
            "test_file.txt",  # Non-archive file
        ]

        for filename in test_files:
            (directory / filename).touch()

        archive_files = get_archive_files(str(directory))
        assert len(archive_files) == 3
        for suffix in [".tar.gz", ".tgz", ".tar.xz"]:
            assert any(f.endswith(suffix) for f in archive_files)


def test_get_archive_files_with_permanent_artifacts():
    """Test the get_archive_files function with permanent test artifacts"""
    directory = ARTEFACTS_DIR
    archive_files = get_archive_files(str(directory))
    assert len(archive_files) == 0


def test_hash256sum():
    """Test the has256sum function"""

    sum1 = hash256sum(ARTEFACTS_DIR / "test.txt")
    sum2 = hash256sum(ARTEFACTS_DIR / "test.txt")
    assert sum1 == sum2
    assert sum1 == "f2ca1bb6c7e907d06dafe4687e579fce76b37e4e93b7605022da52e6ccc26fd2"


@patch("package_validation_tool.utils.requests.Session")
def test_extract_links_success(mock_session):
    """Test the extract_links function for a successful web page scraping"""
    url = "https://example.com"

    # Create a mock response with HTML content containing links
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = """
    <html>
        <body>
            <a href="https://example.com/page1.html">Page 1</a>
            <a href="/relative/path.html">Relative Path</a>
            <a href="file.tar.gz">Download</a>
            <div>Not a link</div>
        </body>
    </html>
    """

    # Configure the mock session
    mock_session_instance = MagicMock()
    mock_session_instance.get.return_value = mock_response
    mock_session.return_value = mock_session_instance

    # Call the function and verify results
    links = extract_links(url)

    # Verify the function called the right methods
    mock_session_instance.get.assert_called_once_with(url, headers=DEFAULT_REQUEST_HEADERS)

    # Verify the returned links
    assert len(links) == 3
    assert "https://example.com/page1.html" in links
    assert "/relative/path.html" in links
    assert "file.tar.gz" in links


@patch("package_validation_tool.utils.requests.Session")
def test_extract_links_empty_page(mock_session):
    """Test the extract_links function with a page that has no links"""
    url = "https://example.com/empty"

    # Create a mock response with HTML content containing no links
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = """
    <html>
        <body>
            <p>This page has no links</p>
        </body>
    </html>
    """

    # Configure the mock session
    mock_session_instance = MagicMock()
    mock_session_instance.get.return_value = mock_response
    mock_session.return_value = mock_session_instance

    # Call the function and verify results
    links = extract_links(url)

    # Verify the function called the right methods
    mock_session_instance.get.assert_called_once_with(url, headers=DEFAULT_REQUEST_HEADERS)

    # Verify no links were returned
    assert len(links) == 0


@patch("package_validation_tool.utils.requests.Session")
def test_extract_links_http_error(mock_session):
    """Test the extract_links function when an HTTP error occurs"""
    url = "https://example.com/not-found"

    # Configure the mock session to raise an exception
    mock_session_instance = MagicMock()
    mock_session_instance.get.side_effect = requests.exceptions.HTTPError("404 Not Found")
    mock_session.return_value = mock_session_instance

    # Call the function and verify results
    links = extract_links(url)

    # Verify the function called the right methods
    mock_session_instance.get.assert_called_once_with(url, headers=DEFAULT_REQUEST_HEADERS)

    # Verify function returns None due to the error
    assert links is None


@patch("package_validation_tool.utils.requests.Session")
def test_extract_links_connection_error(mock_session):
    """Test the extract_links function when a connection error occurs"""
    url = "https://example.com/timeout"

    # Configure the mock session to raise a connection error
    mock_session_instance = MagicMock()
    mock_session_instance.get.side_effect = requests.exceptions.ConnectionError(
        "Connection refused"
    )
    mock_session.return_value = mock_session_instance

    # Call the function and verify results
    links = extract_links(url)

    # Verify the function called the right methods
    mock_session_instance.get.assert_called_once_with(url, headers=DEFAULT_REQUEST_HEADERS)

    # Verify function returns None due to the error
    assert links is None


@patch("package_validation_tool.utils.requests.Session")
def test_extract_links_malformed_html(mock_session):
    """Test the extract_links function with malformed HTML"""
    url = "https://example.com/malformed"

    # Create a mock response with malformed HTML content
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = """
    <html>
        <body>
            <a href="https://example.com/page1.html">Page 1</a>
            <a href="missing-closing-tag">
            <a href=invalid-quotes>Invalid</a>
        </body>
    </html>
    """

    # Configure the mock session
    mock_session_instance = MagicMock()
    mock_session_instance.get.return_value = mock_response
    mock_session.return_value = mock_session_instance

    # Call the function and verify results
    links = extract_links(url)

    # Verify the function called the right methods
    mock_session_instance.get.assert_called_once_with(url, headers=DEFAULT_REQUEST_HEADERS)

    # BeautifulSoup should still extract valid links from malformed HTML
    assert "https://example.com/page1.html" in links


@pytest.mark.parametrize(
    "left, right, expected",
    [
        # Basic version comparisons
        ("1.0.0", "1.0.1", False),
        ("1.0.1", "1.0.0", True),
        ("1.0.0", "1.0.0", False),
        # Multi-segment versions
        ("1.2.3-4.5.6", "1.2.3-4.5.7", False),
        ("1.2.3-4.5.6", "1.2.3-4.5.5", True),
        # Versions with letters
        ("1.0.0-alpha", "1.0.0-beta", False),
        ("1.0.0-beta", "1.0.0-alpha", True),
        # Complex examples
        ("package-1.0.0+build.1", "package-1.0.0+build.2", False),
        ("package-1.0.0+build.2", "package-1.0.0+build.1", True),
        ("1.0.0:l", "1.0.0:s", False),
        ("1.0.0:s", "1.0.0:l", True),
        ("package-2.3.4-a+build.567", "package-2.3.4-b+build.567", False),
        ("package-2.3.4-b+build.567", "package-2.3.4-a+build.567", True),
        ("1.0.0-rc.1+build.1", "1.0.0-rc.1+build.2", False),
        # Mixed numeric and alphabetic
        ("v1.2.3a", "v1.2.3b", False),
        ("v1.2.3b", "v1.2.3a", True),
        # Different length comparisons
        ("1.0.0", "1.0", True),
        ("1.0", "1.0.0", False),
        # Versions with multiple special characters
        ("1.0.0-alpha+001", "1.0.0-alpha+002", False),
        ("1.0.0-alpha+002", "1.0.0-alpha+001", True),
        ("1.0.0-alpha:001", "1.0.0-alpha:002", False),
        # Additional tests specific to your implementation
        ("1", "a", True),  # Numbers are preferred over strings
        ("a", "1", False),
        ("1.0.0", "1.0.0-alpha", False),  # More segments
        ("1.0.0-alpha", "1.0.0", True),
    ],
)
def test_versions_is_greater(left, right, expected):
    assert versions_is_greater(left, right) == expected, f"Failed for {left} > {right}"


@patch("subprocess.run")
def test_clone_git_repo_success(mock_run):
    """Test the clone_git_repo function for a successful clone"""
    repo_url = "https://github.com/example/repo.git"

    # Configure the mock to simulate a successful git clone
    mock_run.return_value = MagicMock(returncode=0)

    with tempfile.TemporaryDirectory() as temp_dir:
        # Test with bare=False
        success, repo_path = clone_git_repo(repo_url, temp_dir)

        mock_run.assert_called_with(
            ["git", "clone", repo_url, temp_dir],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert success is True
        assert repo_path == temp_dir

        # Test with bare=True (must reset the mock for this new test)
        mock_run.reset_mock()
        success, repo_path = clone_git_repo(repo_url, temp_dir, bare=True)

        mock_run.assert_called_with(
            ["git", "clone", "--no-checkout", "--filter=blob:none", repo_url, temp_dir],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert success is True
        assert repo_path == temp_dir


@patch("subprocess.run")
def test_clone_git_repo_failure(mock_run):
    """Test the clone_git_repo function when git clone fails"""
    repo_url = "https://github.com/example/nonexistent-repo.git"

    # Configure the mock to simulate a failed git clone
    mock_run.side_effect = subprocess.CalledProcessError(
        cmd=["git", "clone", repo_url, "/tmp/test-dir"],
        returncode=128,
        output=b"fatal: repository not found",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        success, repo_path = clone_git_repo(repo_url, temp_dir)
        mock_run.assert_called_once()
        assert success is False
        assert repo_path == ""


@patch("subprocess.run")
def test_checkout_in_git_repo_success_with_commit(mock_run):
    """Test the checkout_in_git_repo function for a successful checkout with commit hash"""
    repo_dir = "/path/to/repo"
    commit_hash = "abc123def456"

    # Configure the mock to simulate a successful git checkout
    mock_run.return_value = MagicMock(returncode=0)

    with patch("os.path.exists", return_value=True):
        success = checkout_in_git_repo(repo_dir, commit_hash)

        mock_run.assert_called_once_with(
            ["git", "checkout", commit_hash],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=repo_dir,
        )

        assert success is True


@patch("subprocess.run")
def test_checkout_in_git_repo_success_with_tag(mock_run):
    """Test the checkout_in_git_repo function for a successful checkout with tag"""
    repo_dir = "/path/to/repo"
    tag_name = "v1.2.3"

    # Configure the mock to simulate a successful git checkout
    mock_run.return_value = MagicMock(returncode=0)

    with patch("os.path.exists", return_value=True):
        success = checkout_in_git_repo(repo_dir, tag_name)

        mock_run.assert_called_once_with(
            ["git", "checkout", tag_name],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=repo_dir,
        )

        assert success is True


@patch("subprocess.run")
def test_checkout_in_git_repo_failure_nonexistent_commit(mock_run):
    """Test the checkout_in_git_repo function when git checkout fails due to nonexistent commit"""
    repo_dir = "/path/to/repo"
    commit_hash = "nonexistent123"

    # Configure the mock to simulate a failed git checkout
    mock_run.side_effect = subprocess.CalledProcessError(
        cmd=["git", "checkout", commit_hash],
        returncode=1,
        output=b"error: pathspec 'nonexistent123' did not match any file(s) known to git",
    )

    with patch("os.path.exists", return_value=True):
        success = checkout_in_git_repo(repo_dir, commit_hash)
        mock_run.assert_called_once()
        assert success is False


def test_checkout_in_git_repo_failure_nonexistent_directory():
    """Test the checkout_in_git_repo function when repository directory does not exist"""
    repo_dir = "/nonexistent/repo"
    commit_hash = "abc123def456"

    with patch("os.path.exists", return_value=False):
        success = checkout_in_git_repo(repo_dir, commit_hash)
        assert success is False


@patch("subprocess.run")
def test_get_git_tree_hash_success(mock_run):
    """Test the get_git_tree_hash function for a successful tree hash retrieval"""
    repo_dir = "/path/to/repo"
    commit_object = "v1.2.3"
    expected_tree_hash = "abc123def456789tree"

    # Configure the mock to simulate a successful git rev-parse
    mock_run.return_value = MagicMock(returncode=0, stdout=f"{expected_tree_hash}\n")

    with patch("os.path.exists", return_value=True):
        tree_hash = get_git_tree_hash(repo_dir, commit_object)

        mock_run.assert_called_once_with(
            ["git", "rev-parse", f"{commit_object}^{{tree}}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=repo_dir,
            text=True,
        )

        assert tree_hash == expected_tree_hash


@patch("subprocess.run")
def test_get_git_tree_hash_failure_nonexistent_directory(mock_run):
    """Test the get_git_tree_hash function when repository directory does not exist"""
    repo_dir = "/nonexistent/repo"
    commit_object = "HEAD"

    with patch("os.path.exists", return_value=False):
        tree_hash = get_git_tree_hash(repo_dir, commit_object)

        # subprocess.run should not be called when directory doesn't exist
        mock_run.assert_not_called()
        assert tree_hash is None


def test_secure_tar_extractall_benign_archive():
    """Test secure_tar_extractall with a benign archive containing normal files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create a benign tar archive with normal files
        archive_path = temp_path / "benign.tar"
        extract_path = temp_path / "extract"
        extract_path.mkdir()

        # Create test files to add to archive
        test_files = {
            "file1.txt": "Content of file1",
            "subdir/file2.txt": "Content of file2",
            "another.py": "print('Hello World')",
        }

        # Create the archive
        with tarfile.open(archive_path, "w") as tar:
            for file_path, content in test_files.items():
                # Create a temporary file to add to archive
                temp_file = temp_path / file_path
                temp_file.parent.mkdir(parents=True, exist_ok=True)
                temp_file.write_text(content)
                tar.add(str(temp_file), arcname=file_path)

        # Test secure extraction
        with tarfile.open(archive_path, "r") as tar:
            result = secure_tar_extractall(tar, str(extract_path))

        # Verify extraction was successful
        assert result is True

        # Verify files were extracted correctly
        for file_path, expected_content in test_files.items():
            extracted_file = extract_path / file_path
            assert extracted_file.exists(), f"File {file_path} was not extracted"
            assert extracted_file.read_text() == expected_content


def test_secure_tar_extractall_absolute_path_attack():
    """Test secure_tar_extractall blocks archive with absolute paths (zip bomb protection)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "malicious_absolute.tar"
        extract_path = temp_path / "extract"
        extract_path.mkdir()

        # Create a malicious archive with absolute paths
        with tarfile.open(archive_path, "w") as tar:
            # Create a temporary file to add with absolute path
            temp_file = temp_path / "malicious.txt"
            temp_file.write_text("Absolute path attack")

            # Add with absolute path (this should be blocked)
            tar.add(str(temp_file), arcname="/tmp/malicious_file")

        # Test secure extraction should fail
        with tarfile.open(archive_path, "r") as tar:
            result = secure_tar_extractall(tar, str(extract_path))

        # Verify extraction succeeded, but abspath file became relpath
        assert result is True
        extracted_file = extract_path / "tmp/malicious_file"
        assert extracted_file.exists(), f"File {extracted_file} was not extracted"
        assert extracted_file.read_text() == "Absolute path attack"

        # Verify no malicious file was created
        malicious_file = Path("/tmp/malicious_file")
        assert (
            not malicious_file.exists()
            or "Absolute path attack" not in malicious_file.read_text(encoding="utf-8")
        )


def test_secure_tar_extractall_directory_traversal_attack():
    """Test secure_tar_extractall blocks directory traversal attacks."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "malicious_traversal.tar"
        extract_path = temp_path / "extract"
        extract_path.mkdir()

        # Create a malicious archive with directory traversal
        with tarfile.open(archive_path, "w") as tar:
            # Create a temporary file
            temp_file = temp_path / "malicious.txt"
            temp_file.write_text("Directory traversal attack")

            # Add with directory traversal path
            tar.add(str(temp_file), arcname="../../../etc/malicious")

        # Test secure extraction should fail
        with tarfile.open(archive_path, "r") as tar:
            result = secure_tar_extractall(tar, str(extract_path))

        # Verify extraction was blocked
        assert result is False

        # Verify no file was created outside the extraction directory
        malicious_file = temp_path.parent.parent.parent / "etc" / "malicious"
        assert not malicious_file.exists()


def test_secure_tar_extractall_symlink_attack():
    """Test secure_tar_extractall blocks symlink attacks."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "malicious_symlink.tar"
        extract_path = temp_path / "extract"
        extract_path.mkdir()

        # Create files for the archive
        temp_file = temp_path / "normal.txt"
        temp_file.write_text("Normal content")

        # Create a symlink pointing outside extraction directory
        symlink_source = temp_path / "symlink"
        symlink_source.symlink_to("/etc/passwd")

        # Create archive with symlink attack
        with tarfile.open(archive_path, "w") as tar:
            tar.add(str(temp_file), arcname="normal.txt")
            tar.add(str(symlink_source), arcname="malicious_symlink")

        # Test secure extraction should fail
        with tarfile.open(archive_path, "r") as tar:
            result = secure_tar_extractall(tar, str(extract_path))

        # Verify extraction was blocked
        assert result is False


def test_secure_unpack_archive_benign_tar():
    """Test secure_unpack_archive with a benign tar.gz archive."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "benign.tar.gz"
        extract_path = temp_path / "extract"
        extract_path.mkdir()

        # Create test files
        test_files = {
            "readme.txt": "This is a readme file",
            "src/main.py": "def main():\n    print('Hello')",
            "config.json": '{"version": "1.0"}',
        }

        # Create the tar.gz archive
        with tarfile.open(archive_path, "w:gz") as tar:
            for file_path, content in test_files.items():
                temp_file = temp_path / file_path
                temp_file.parent.mkdir(parents=True, exist_ok=True)
                temp_file.write_text(content)
                tar.add(str(temp_file), arcname=file_path)

        # Test secure extraction
        result = secure_unpack_archive(str(archive_path), str(extract_path))

        # Verify extraction was successful
        assert result is True

        # Verify files were extracted correctly
        for file_path, expected_content in test_files.items():
            extracted_file = extract_path / file_path
            assert extracted_file.exists(), f"File {file_path} was not extracted"
            assert extracted_file.read_text() == expected_content


def test_secure_unpack_archive_benign_zip():
    """Test secure_unpack_archive with a benign ZIP archive."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "benign.zip"
        extract_path = temp_path / "extract"
        extract_path.mkdir()

        # Create test files and a ZIP archive
        test_files = {
            "document.txt": "Important document content",
            "images/photo.txt": "Fake photo content",  # Using .txt for simplicity
        }

        # Create files first
        files_to_zip = []
        for file_path, content in test_files.items():
            temp_file = temp_path / file_path
            temp_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file.write_text(content)
            files_to_zip.append(temp_file)

        # Create ZIP archive using shutil
        archive_base = str(archive_path).replace(".zip", "")
        shutil.make_archive(archive_base, "zip", temp_path, base_dir=".")

        # Test secure extraction
        result = secure_unpack_archive(str(archive_path), str(extract_path))

        # Verify extraction was successful
        assert result is True

        # Verify files were extracted correctly
        for file_path, expected_content in test_files.items():
            extracted_file = extract_path / file_path
            assert extracted_file.exists(), f"File {file_path} was not extracted"
            assert extracted_file.read_text() == expected_content


def test_secure_unpack_archive_absolute_path_attack():
    """Test secure_unpack_archive blocks archive with absolute paths."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "malicious_absolute.tar.gz"
        extract_path = temp_path / "extract"
        extract_path.mkdir()

        # Create a malicious archive with absolute paths
        with tarfile.open(archive_path, "w:gz") as tar:
            # Create a temporary file
            temp_file = temp_path / "malicious.txt"
            temp_file.write_text("Absolute path attack")

            # Add with absolute path
            tar.add(str(temp_file), arcname="/tmp/malicious_file")

        # Test secure extraction should fail
        result = secure_unpack_archive(str(archive_path), str(extract_path))

        # Verify extraction succeeded, but abspath file became relpath
        assert result is True
        extracted_file = extract_path / "tmp/malicious_file"
        assert extracted_file.exists(), f"File {extracted_file} was not extracted"
        assert extracted_file.read_text() == "Absolute path attack"

        # Verify no malicious file was created
        malicious_file = Path("/tmp/malicious_file")
        assert (
            not malicious_file.exists()
            or "Absolute path attack" not in malicious_file.read_text(encoding="utf-8")
        )


def test_secure_unpack_archive_malicious_directory_traversal():
    """Test secure_unpack_archive blocks directory traversal attacks."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "malicious_traversal.tar.gz"
        extract_path = temp_path / "extract"
        extract_path.mkdir()

        # Create a malicious archive with directory traversal
        with tarfile.open(archive_path, "w:gz") as tar:
            # Create a temporary file
            temp_file = temp_path / "malicious.txt"
            temp_file.write_text("Traversal attack content")

            # Add with directory traversal
            tar.add(str(temp_file), arcname="../../malicious_escape")

        # Test secure extraction should fail
        result = secure_unpack_archive(str(archive_path), str(extract_path))

        # Verify extraction was blocked
        assert result is False

        # Verify no file was created outside extraction directory
        malicious_file = temp_path / "malicious_escape"
        assert not malicious_file.exists()


def test_secure_unpack_archive_nonexistent_file():
    """Test secure_unpack_archive handles nonexistent archive files gracefully."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        nonexistent_archive = temp_path / "does_not_exist.tar.gz"
        extract_path = temp_path / "extract"
        extract_path.mkdir()

        # Test extraction of nonexistent file should fail
        result = secure_unpack_archive(str(nonexistent_archive), str(extract_path))

        # Verify extraction failed gracefully
        assert result is False
