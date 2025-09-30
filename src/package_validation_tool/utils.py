# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Collection of basic helper functions
"""

import contextlib
import glob
import hashlib
import logging
import os
import re
import shutil
import socket
import ssl
import subprocess
import tarfile
import tempfile
import urllib.request
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import chardet
import requests
from bs4 import BeautifulSoup

from package_validation_tool.common import SUPPORTED_ARCHIVE_TYPES

log = logging.getLogger(__name__)

# Standard HTTP headers for web requests to avoid being blocked by websites
# that filter requests with default user agents
DEFAULT_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 Firefox/140.0"}


def set_default_python_socket_timeout():
    """Sets timeout (10s by default) for all connections."""
    socket_timeout = float(os.environ.get("PYTHON_SOCKET_TIMEOUT", 10.0))
    socket.setdefaulttimeout(socket_timeout)


def remove_archive_suffix(file: str) -> str:
    """Removes suffix from the file, including two-part suffixes like `.tar.gz`"""
    for archive_type in SUPPORTED_ARCHIVE_TYPES:
        if file.endswith(archive_type):
            return file[: -len(archive_type)]
    return os.path.splitext(file)[0]


def is_url_accessible(url: str) -> bool:
    """Verify that URL is accessible without downloading the file. Return True if accessible."""
    # silence requests/urllib logs like "urllib3.connectionpool Starting new HTTPS connection (1)"
    log_level = max(log.getEffectiveLevel(), logging.INFO)
    logging.getLogger("requests").setLevel(log_level)
    logging.getLogger("urllib3").setLevel(log_level)

    parsed_url = urlparse(url)
    try:
        if parsed_url.scheme == "https" or parsed_url.scheme == "http":
            # requests module doesn't have a connection adapter for FTP, only HTTP(S)
            r = requests.get(url, headers=DEFAULT_REQUEST_HEADERS, stream=True, timeout=3)
            # URL can be redirected to an unrelated URL (like main page), consider it a failure;
            # note that we must correctly handle good but non-trivial redirections like this:
            #   https://github.com/org/proj/archive/name-v0.1.tar.gz ->
            #       https://codeload.github.com/org/proj/tar.gz/refs/tags/name-v0.1
            accessed_url = urlparse(r.url)
            parsed_url_stem = remove_archive_suffix(os.path.basename(parsed_url.path))
            redirected_to_same_file = parsed_url_stem in accessed_url.path
            return r.status_code >= 200 and r.status_code < 400 and redirected_to_same_file
        elif parsed_url.scheme == "ftp":
            # urllib.request module has a connection adapter for FTP, do a dummy read to check URL
            with urllib.request.urlopen(url, timeout=3) as response:
                response.read(32)
            return True
        else:
            return False
    except Exception:
        return False


def download_file(file_url: str, local_file_path: str):
    """Download a file from a given URL and save it to a local file path. Return True on success."""

    # Parse the URL to determine the protocol
    parsed_url = urlparse(file_url)

    if parsed_url.scheme == "https" or parsed_url.scheme == "http":
        try:
            context = ssl.create_default_context()
            # some web sites require valid User-Agent header
            req = urllib.request.Request(file_url, headers=DEFAULT_REQUEST_HEADERS)
            with urllib.request.urlopen(req, context=context) as response, open(
                local_file_path, "wb"
            ) as file:
                file.write(response.read())
            return True
        except Exception as e:
            log.debug("Error downloading file %s: %r", file_url, e)
    elif parsed_url.scheme == "ftp":
        # FTP download
        try:
            urllib.request.urlretrieve(file_url, local_file_path)
            return True
        except Exception as e:
            log.debug("Error downloading file %s: %r", file_url, e)
    else:
        log.debug("Unsupported protocol for downloading: %r from %s", parsed_url.scheme, file_url)
    return False


def extract_links(url: str) -> Optional[List[str]]:
    """
    Scrape all links from the given URL (download and search for <a> HTML tags).
    Returns None in case of any exceptions (e.g., URL is inaccessible).
    """
    session = requests.Session()

    try:
        response = session.get(url, headers=DEFAULT_REQUEST_HEADERS)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")
        links = soup.find_all("a", href=True)
        all_links = [str(link["href"]) for link in links]
        return list(set(all_links))  # Remove duplicates
    except Exception as e:
        log.debug("Error scraping links from the web page %s: %r", url, e)
        return None
    finally:
        session.close()


def get_archive_files(directory: str) -> List[str]:
    """Return all supported archive files that are located directly in the given directory."""
    tar_files = []
    for suffix in SUPPORTED_ARCHIVE_TYPES:
        files = glob.glob(os.path.join(directory, f"*{suffix}"))
        tar_files.extend(files)
    return [os.path.join(directory, x) for x in tar_files]


def lines_starting_with(lines: List[str], pattern: str):
    """Return lines strating with (one of) the given pattern."""
    matching_lines = []
    for line in lines:
        if line.startswith(pattern):
            matching_lines.append(line)
    return matching_lines


@contextlib.contextmanager
def pushd(new_dir: str):
    """Execute the code in context in the given directory."""
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


def read_file_as_utf8(file_path: str) -> str:
    """Read the content of a file and return it as string."""

    # auto-detecting encoding can be very slow, so first try a couple popular encodings
    for encoding in ["utf-8", "utf-16"]:
        try:
            with open(file_path, "r", encoding=encoding) as file:
                content: str = file.read()
            return content.encode("utf-8", errors="replace").decode("utf-8")
        except UnicodeError:
            pass

    # if above fails, then fall back to reading file in binary mode and auto-detecting encoding
    with open(file_path, "rb") as file:
        content_bytes: bytes = file.read()

    # silence the chardet debug logs like "chardet.charsetprober:98 utf-8 confidence = 0.87625"
    chardet_level = max(log.getEffectiveLevel(), logging.INFO)
    logging.getLogger("chardet").setLevel(chardet_level)

    # detect the encoding using chardet
    detected_encoding: Optional[str] = chardet.detect(content_bytes)["encoding"]
    if detected_encoding:
        try:
            content = content_bytes.decode(detected_encoding)
            return content.encode("utf-8", errors="replace").decode("utf-8")
        except UnicodeError:
            pass

    # if everything else fails, return the bytes as a string
    return str(content_bytes)


def save_path(path: str):
    """Return a path name without special characters."""
    return path.replace(":", "-").replace("/", "-")


def hash256sum(filepath: str):
    """Return sha256 sum of the given file"""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            data = f.read(65536)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()


def split_version_in_list(version_string: str) -> list:
    """Parse a version string into a list of integers and strings, keeping separators."""
    if not version_string:
        return []
    # Define the pattern to split the string
    pattern = r"(\d+|[a-zA-Z]+|[.\-:+])"
    # Use regex to split the string
    parts = re.findall(pattern, version_string)
    # Convert numeric strings to integers
    return [int(part) if part.isdigit() else part for part in parts]


def versions_is_greater(left: str, right: str) -> bool:
    """Return true if the given version string in left is greater than right."""
    left_parts = split_version_in_list(left)
    right_parts = split_version_in_list(right)

    for left_item, right_item in zip(left_parts, right_parts):
        # Compare same types, continue if equal
        if isinstance(left_item, type(right_item)):
            if left_item > right_item:
                return True
            if left_item < right_item:
                return False
            continue
        # Prefer numbers over other types
        if isinstance(left_item, int):
            return True
        if isinstance(right_item, int):
            return False
        # Compare string representation
        if str(left_item) > str(right_item):
            return True
        if str(left_item) < str(right_item):
            return False
    return len(left_parts) > len(right_parts)


def clone_git_repo(
    repo: str, target_dir: Optional[str] = None, bare: bool = False
) -> Tuple[bool, str]:
    """
    Clone a git repository to a target directory.

    Args:
        repo (str): URL of the git repository to clone
        target_dir (str): Directory to clone into. If None, a temporary directory is created.
        bare (bool): If True, clone with `--no-checkout --filter=blob:none` for a minimal clone.
                     If False, perform a regular clone.

    Returns:
        Tuple[bool, str]: A tuple containing:
            - Success status (True if clone was successful, False otherwise)
            - Path to the cloned repository (or empty string if failed)
    """

    parsed = urllib.parse.urlparse(repo)
    if parsed.scheme not in ["https", "ssh"]:
        log.error("Failed to clone repository %s: only HTTPS and SSH URLs allowed", repo)
        return False, ""

    temp_dir_created = False
    if target_dir is None:
        target_dir = tempfile.mkdtemp()
        temp_dir_created = True

    if bare:
        # Minimal clone without checking out files (faster, less disk space)
        clone_cmd = ["git", "clone", "--no-checkout", "--filter=blob:none", repo, target_dir]
    else:
        # Regular clone with full checkout
        clone_cmd = ["git", "clone", repo, target_dir]

    try:
        subprocess.run(clone_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True, target_dir
    except subprocess.CalledProcessError as e:
        log.error("Failed to clone repository %s: %s", repo, e)
        if temp_dir_created and os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        return False, ""


def checkout_in_git_repo(repo_dir: str, repo_commit: str) -> bool:
    """
    Checkout a specific commit, tag, or branch in a git repository.

    Args:
        repo_dir (str): Path to the git repository directory
        repo_commit (str): Commit hash, tag, or branch name to checkout

    Returns:
        bool: True if checkout was successful, False otherwise
    """
    if not os.path.exists(repo_dir):
        log.error("Repository directory does not exist: %s", repo_dir)
        return False

    checkout_cmd = ["git", "checkout", repo_commit]

    try:
        subprocess.run(
            checkout_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=repo_dir
        )
        return True
    except subprocess.CalledProcessError as e:
        log.error("Failed to checkout %s in repository %s: %s", repo_commit, repo_dir, e)
        return False


def get_git_tree_hash(repo_dir: str, commit_object: str = "HEAD") -> Optional[str]:
    """
    Get the tree hash for a specific commit object in a git repository.

    The tree hash represents the exact content state of the repository at the given commit,
    ignoring commit metadata like author, date, and message. This is useful for content-level
    deduplication where different commits or repositories may have identical content.

    Args:
        repo_dir (str): Path to the git repository directory
        commit_object (str): Commit hash, tag, branch name, or git reference (default: "HEAD")

    Returns:
        Optional[str]: Tree hash as a string if successful, None if failed
    """
    if not os.path.exists(repo_dir):
        log.error("Repository directory does not exist: %s", repo_dir)
        return None

    tree_hash_cmd = ["git", "rev-parse", f"{commit_object}^{{tree}}"]

    try:
        result = subprocess.run(
            tree_hash_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=repo_dir,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log.error("Failed to get tree hash for %s in repository %s: %s", commit_object, repo_dir, e)
        return None


def secure_tar_extractall(tar_obj: tarfile.TarFile, path: str) -> bool:
    """
    Secure wrapper for tar.extractall() that handles potential security exceptions.

    Args:
        tar_obj: The tarfile object to extract
        path: Path where to extract the archive

    Returns:
        bool: True if extraction was successful, False otherwise
    """
    try:
        tar_obj.extractall(path=path, filter="data")
        return True
    except (
        tarfile.AbsolutePathError,
        tarfile.OutsideDestinationError,
        tarfile.AbsoluteLinkError,
        tarfile.LinkOutsideDestinationError,
        tarfile.SpecialFileError,
    ) as e:
        log.warning("Secure tar extraction failed due to security constraint: %s", e)
        return False
    except Exception as e:
        log.warning("Tar extraction failed with unexpected error: %s", e)
        return False


def secure_unpack_archive(input_file: str, extract_dir: str) -> bool:
    """
    Secure wrapper for shutil.unpack_archive() that handles potential security exceptions.

    Args:
        input_file: Path to the archive file to extract
        extract_dir: Directory where to extract the archive

    Returns:
        bool: True if extraction was successful, False otherwise
    """
    try:
        if input_file.endswith(".zip"):
            shutil.unpack_archive(input_file, extract_dir)
        else:
            shutil.unpack_archive(input_file, extract_dir, filter="data")
        return True
    except (
        tarfile.AbsolutePathError,
        tarfile.OutsideDestinationError,
        tarfile.AbsoluteLinkError,
        tarfile.LinkOutsideDestinationError,
        tarfile.SpecialFileError,
    ) as e:
        log.warning("Secure unpack archive failed due to security constraint: %s", e)
        return False
    except Exception as e:
        log.warning("Unpack archive failed with unexpected error: %s", e)
        return False
