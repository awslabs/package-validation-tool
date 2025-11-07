# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Unit test for the suggest-package-repos CLI sub-command. This transitively covers the
# suggest_package_repos() function and the RepoSuggester class.

import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

from package_validation_tool.cli import main
from package_validation_tool.package.rpm.utils import get_single_spec_file, parse_rpm_spec_file
from package_validation_tool.package.suggesting_repos.suggestion_methods import _is_git_repo
from package_validation_tool.utils import pushd

TEST_DIR_PATH = os.path.dirname(__file__)
TESTRPM_SPEC_FILE = Path(TEST_DIR_PATH) / "artefacts" / "rpm" / "testrpm_for_suggesting_repos.spec"


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
    src_rpm_file = Path(target_dir) / "testrpm_for_suggesting_repos.src.rpm"
    src_rpm_file.touch()

    # create dummy file in a new dir, put it into the archive
    files_to_archive_path = Path(target_dir) / "files"
    os.mkdir(files_to_archive_path)

    dummy_file = files_to_archive_path / "plainfile"
    with open(dummy_file, "w", encoding="utf-8") as f:
        f.write("Test file")

    # create the archive and have a copy in the srpm directory
    archive_path = Path(target_dir) / "testrpm-0.1.tar"  # must correspond to Source0

    with tarfile.open(archive_path, "w") as tar:
        for entry in os.scandir(files_to_archive_path):
            tar.add(entry.path, arcname=entry.name)

    shutil.copy(archive_path, srpm_content_path)

    return srpm_content_path, src_rpm_file, archive_path


def mock_requests_get(*args, **kwargs):
    """Mock for requests.get that returns appropriate responses for GitHub API and Repology URLs."""
    url = args[0]  # First argument is the URL
    mock_response = MagicMock()
    mock_response.status_code = 200

    if url == "https://api.github.com/search/repositories":
        # Handle GitHub API requests
        query = kwargs.get("params", {}).get("q", "testrpm")

        # Handle the format "testrpm archived:false" or "testrpm archived:true"
        if " archived:" in query:
            project_name = query.split(" archived:")[0]
            archived_param = query.split(" archived:")[1]
        else:
            project_name = query
            archived_param = "false"  # default

        # Return different results based on archived parameter
        if archived_param == "true":
            # Return archived repository
            mock_data = {
                "items": [
                    {
                        "html_url": f"https://github.com/archived/{project_name}",
                        "name": project_name,
                        "full_name": f"archived/{project_name}",
                        "description": f"Archived test repository for {project_name}",
                    }
                ]
            }
        else:
            # Return non-archived repositories
            mock_data = {
                "items": [
                    {
                        "html_url": f"https://github.com/{project_name}/{project_name}",
                        "name": project_name,
                        "full_name": f"{project_name}/{project_name}",
                        "description": f"Test repository for {project_name}",
                    },
                    {
                        "html_url": f"https://github.com/everything/{project_name}",
                        "name": project_name,
                        "full_name": f"everything/{project_name}",
                        "description": f"Another test repository for {project_name}",
                    },
                ]
            }

        mock_response.json.return_value = mock_data

    elif url.startswith("https://repology.org/project/") and url.endswith("/information"):
        # Handle Repology requests
        # Extract project name from URL: https://repology.org/project/{project_name}/information
        project_name = url.split("/project/")[1].split("/information")[0]

        # Create mock Repology HTML response
        mock_html_content = f"""
        <html>
            <body>
                <h1>Project {project_name}</h1>
                <section id="Repository_links">
                    <h2>Repository links</h2>
                    <ul>
                        <li><a href="https://github.com/{project_name}/{project_name}">GitHub</a></li>
                        <li><a href="https://gitlab.com/{project_name}/{project_name}">GitLab</a></li>
                        <li><a href="https://example.com/git/{project_name}.git">Example Git</a></li>
                        <li><a href="https://nonrepo.example.com/not-a-repo">Not a repo</a></li>
                    </ul>
                </section>
                <section id="Other section">
                    <p>Other content</p>
                </section>
            </body>
        </html>
        """
        mock_response.content = mock_html_content.encode("utf-8")

    else:
        # Fail for unrecognized URLs
        raise ValueError(
            f"mock_requests_get() received unrecognized URL: {url}. "
            f"Expected either 'https://api.github.com/search/repositories' or "
            f"'https://repology.org/project/*/information'"
        )

    return mock_response


def mock_subprocess_run_git_commands(*args, **_kwargs):
    mock_result = MagicMock()
    mock_result.returncode = 0

    # Handle git tag command for local repo
    if args[0][0:3] == ["git", "tag", "--list"]:
        mock_result.stdout = """
        abcdef1234567892 v2.4.11
        abcdef1234567894 v2.2.0
        abcdef1234567890 v0.1
        """
    # Handle git rev-parse for commit verification
    elif args[0][0:2] == ["git", "rev-parse"]:
        # Current test does not use commit hashes, so return empty (not found)
        mock_result.stdout = ""
    # Handle git clone (just return success)
    elif args[0][0:2] == ["git", "clone"]:
        mock_result.stdout = ""
    else:
        raise RuntimeError("Non-git subprocess.run commands are disallowed")

    return mock_result


def test_suggest_package_repos_cli():
    """Test suggest-package-repos CLI command."""
    with tempfile.TemporaryDirectory() as temp_dir, pushd(temp_dir):
        srpm_content_path, src_rpm_file, _ = prepare_srpm_test_environment(temp_dir)

        def patched_is_git_repo(repo: str) -> bool:
            """Return True for specific test URLs."""
            return repo in [
                # GitHub URLs (from spec sources, known hostings, github api, repology)
                "https://github.com/testrpm/testrpm",
                "https://github.com/everything/testrpm",  # from GitHub API
                "https://github.com/archived/testrpm",  # from GitHub API archived search
                # Other git repos
                "git://sourceware.org/git/testrpm.git",  # from Sourceware
                "https://example.com/git/testrpm.git",
                "https://gitlab.com/testrpm/testrpm",  # from Repology
            ]

        def patched_is_url_accessible(_url: str) -> bool:
            """Always return True for URL accessibility."""
            return True

        def patched_extract_links(url: str) -> List[str]:
            """Mock for extract_links that returns predefined links based on the URL."""
            if "github.com/testrpm/testrpm" in url:
                return [
                    "https://github.com/testrpm/testrpm/blob/main/README.md",
                    "https://example.com/git/testrpm/docs/index.html",
                ]
            return []

        # - mock accessing remote SRPM and point to local files instead
        # - pretend we have the rpmspec tool available to start the parsing
        # - mock git repo checking to return True for specific test URLs
        # - mock URL accessibility to always return True
        # - mock parse_rpm_spec_file to use our patched version that doesn't require rpmspec tool
        # - mock prepare_rpmbuild_source to fake an rpmbuild directory
        # - mock requests.get to return successful GitHub API responses
        # - mock extract_links to return predefined links based on URL
        with patch(
            "package_validation_tool.package.rpm.source_package.download_and_extract_source_package"
        ) as mock_download_extract, patch(
            "subprocess.run",
            mock_subprocess_run_git_commands,
        ), patch(
            "package_validation_tool.package.rpm.spec.rpmspec_present"
        ) as rpmspec_present, patch(
            "package_validation_tool.package.suggesting_repos.suggestion_methods._is_git_repo",
            patched_is_git_repo,
        ), patch(
            "package_validation_tool.package.suggesting_repos.suggestion_methods.is_url_accessible",
            patched_is_url_accessible,
        ), patch(
            "package_validation_tool.package.rpm.spec.parse_rpm_spec_file",
            patched_parse_rpm_spec_file,
        ), patch(
            "package_validation_tool.package.rpm.source_package.prepare_rpmbuild_source",
            patched_prepare_rpmbuild_source,
        ), patch(
            "requests.get", mock_requests_get
        ), patch(
            "package_validation_tool.package.suggesting_repos.suggestion_methods.extract_links",
            patched_extract_links,
        ):
            mock_download_extract.return_value = str(src_rpm_file.absolute()), srpm_content_path
            rpmspec_present.return_value = True

            output_json_path = Path(temp_dir) / "output.json"

            exit_code = main(
                [
                    "suggest-package-repos",
                    "-p",
                    "testrpm_for_suggesting_repos",
                    "-o",
                    str(output_json_path),
                ]
            )
            assert exit_code == 0

            with open(output_json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

            # Verify all expected fields in the output
            assert "timestamp" in json_data
            assert json_data["source_package_name"] == "testrpm"
            assert len(json_data["local_archives"]) == 1
            assert json_data["local_archives"][0] == "testrpm-0.1.tar"

            # Verify the suggestions for testrpm-0.1.tar
            assert "testrpm-0.1.tar" in json_data["suggestions"]
            suggestions = json_data["suggestions"]["testrpm-0.1.tar"]

            assert len(suggestions) == 11

            for suggestion in suggestions:
                # The mock_subprocess_run_git_commands function returns "abcdef1234567890" for tag "v0.1"
                assert suggestion["commit_hash"] == "abcdef1234567890"
                assert suggestion["tag"] == "v0.1"
                if suggestion["repo"] == "https://github.com/testrpm/testrpm":
                    assert suggestion["suggested_by"] in [
                        "suggest_repo_from_spec_sources",
                        "suggest_repo_from_known_hostings",
                        "suggest_repo_from_github_api",
                        "suggest_repo_from_repology_website",
                    ]
                elif suggestion["repo"] == "https://github.com/everything/testrpm":
                    assert suggestion["suggested_by"] in ["suggest_repo_from_github_api"]
                elif suggestion["repo"] == "https://github.com/archived/testrpm":
                    assert suggestion["suggested_by"] in ["suggest_repo_from_github_api"]
                elif suggestion["repo"] == "https://gitlab.com/testrpm/testrpm":
                    assert suggestion["suggested_by"] in [
                        "suggest_repo_from_known_hostings",
                        "suggest_repo_from_repology_website",
                    ]
                elif suggestion["repo"] == "https://example.com/git/testrpm.git":
                    assert suggestion["suggested_by"] in [
                        "suggest_repo_from_spec_sources",
                        "suggest_repo_from_repology_website",
                    ]
                elif suggestion["repo"] == "git://sourceware.org/git/testrpm.git":
                    assert suggestion["suggested_by"] in ["suggest_repo_from_known_hostings"]
                else:
                    # Print the unexpected repo for debugging
                    assert False, f"Unexpected repo URL: {suggestion['repo']}"
                assert suggestion["confidence"] == 1.0  # different confidences not yet implemented


def test_is_git_repo_url_validation():
    """Test that _is_git_repo correctly filters out URLs that don't look like git repositories."""

    invalid_urls = [
        # URLs with query strings
        "https://github.com/owner/repo?tab=readme",
        "https://github.com/owner/repo?action=download",
        # URLs with fragments
        "https://github.com/owner/repo#installation",
        "https://github.com/owner/repo#section-1",
        # URLs with no meaningful path
        "https://github.com/",
        "https://github.com",
        "https://example.com/",
        # URLs with documentation-related path components
        "https://github.com/owner/repo/doc/guide",
        "https://github.com/owner/repo/docs/api",
        "https://github.com/owner/repo/wiki/Installation",
        "https://github.com/owner/repo/w/MainPage",
        # URLs with web interface path components
        "https://github.com/owner/repo/issues/123",
        "https://github.com/owner/repo/blob/main/file.py",
        "https://github.com/owner/repo/tree/main/src",
        "https://github.com/owner/repo/releases/tag/v1.0",
        "https://github.com/owner/repo/commit/abc123",
        "https://github.com/owner/repo/branches",
        "https://github.com/owner/repo/tags",
        "https://example.com/project/archive/master.zip",
        "https://example.com/project/download/file.tar.gz",
        "https://example.com/api/v1/repos",
        "https://example.com/search?q=project",
        # URLs with problematic file extensions
        "https://example.com/project/README.html",
        "https://example.com/project/file.pdf",
        "https://example.com/project/archive.tar.gz",
        "https://example.com/project/package.deb",
        "https://example.com/project/installer.exe",
        "https://example.com/project/signature.sig",
        "https://example.com/project/document.md",
        "https://example.com/project/script.php",
        "https://example.com/project/data.txt",
        "https://example.com/project/compressed.xz",
        "https://example.com/project/bundle.zip",
        "https://example.com/project/package.rpm",
        "https://example.com/project/image.iso",
    ]

    for url in invalid_urls:
        result = _is_git_repo(url)
        assert result is False, f"Expected URL to be filtered out by validation: {url}"


def test_get_project_name_version_only_archive():
    """Test that _get_project_name returns source package name for version-only archives."""
    from package_validation_tool.package.suggesting_repos.suggestion_methods import (
        _get_project_name,
    )

    # Test case 1: Version-only archive should use package name
    package = {"source_package_name": "ec2-utils"}
    result = _get_project_name(package, "v2.2.0.tar.gz")
    assert result == "ec2-utils"

    # Test case 2: Another version-only archive (kpatch example)
    package = {"source_package_name": "kpatch"}
    result = _get_project_name(package, "v0.9.10.tar.gz")
    assert result == "kpatch"

    # Test case 3: Normal archive should use original logic
    package = {"source_package_name": "sourceofzlib"}
    result = _get_project_name(package, "zlib-1.2.11.tar.gz")
    assert result == "zlib"

    # Test case 4: Package name with trailing digits should be stripped
    package = {"source_package_name": "python39-cryptography"}
    result = _get_project_name(package, "v1.2.3.tar.gz")
    assert result == "python39-cryptography"  # Only trailing digits are stripped, not middle digits

    # Test case 5: Package name with trailing dots should be stripped
    package = {"source_package_name": "python3.9"}
    result = _get_project_name(package, "v1.0.0.tar.gz")
    assert result == "python"

    # Test case 6: Missing source_package_name should fall back to original logic
    package = {}
    result = _get_project_name(package, "v1.2.3.tar.gz")
    assert result == "v"  # Original logic: remove extension, split on "-", strip digits

    # Test case 7: Normal archive with complex versioning
    package = {"source_package_name": "sourceofopenssh"}
    result = _get_project_name(package, "openssh-8.7p1.tar.gz")
    assert result == "openssh"

    # Test case 8: Archive that starts with 'r' (also considered a version)
    package = {"source_package_name": "redis"}
    result = _get_project_name(package, "r6.2.1.tar.gz")
    assert result == "redis"

    # Test case 9: Archive with digits but not a version
    package = {"source_package_name": "test-package"}
    result = _get_project_name(package, "something123-1.0.tar.gz")
    assert result == "something"  # Original logic applied

    # Test case 10: Commit hash only archive should use source package name
    package = {"source_package_name": "example-project"}
    result = _get_project_name(package, "abcdef123456.tar.gz")
    assert result == "example-project"

    # Test case 11: G-prefixed commit hash only archive should use source package name
    package = {"source_package_name": "example-project"}
    result = _get_project_name(package, "gabcdef123456.tar.gz")
    assert result == "example-project"

    # Test case 12: Complex archive with version and date - should extract project name
    package = {"source_package_name": "sourceofjsonc"}
    result = _get_project_name(package, "json-c-0.18-20240915.tar.gz")
    assert result == "json-c"

    # Test case 13: Complex archive with version and suffix - should extract project name
    package = {"source_package_name": "sourceoflibevent"}
    result = _get_project_name(package, "libevent-2.1.12-stable.tar.gz")
    assert result == "libevent"

    # Test case 14: Complex archive with version and g-prefixed commit - should extract project name
    package = {"source_package_name": "sourceofglibc"}
    result = _get_project_name(package, "glibc-2.42-21-g7a8f3c6ee4.tar.xz")
    assert result == "glibc"

    # Test case 15: Archive with multiple version components
    package = {"source_package_name": "sourceofgcc"}
    result = _get_project_name(package, "gcc-11.5.0-20240719.tar.xz")
    assert result == "gcc"

    # Test case 16: Archive with g-prefixed commit hash and suffix
    package = {"source_package_name": "sourceoffoobar"}
    result = _get_project_name(package, "foo-bar-g7a8f3c6ee4-stable.tar.xz")
    assert result == "foo-bar"
