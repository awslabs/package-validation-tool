# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
List of methods to suggest (git) repos' URLs for local archives.

Each function in this module has the following function signature:

  def _suggest_*(local_archive_basename: str, spec_sources: list[str]) -> list[RemoteRepoSuggestion]

Each function takes a locally extracted-from-srpm archive and the list of all URLs in the spec file
and tries one specific heuristic to find accessible repo URLs that match the local archive.

Each function returns a list of RemoteRepoSuggestion objects (with the most important field being
`repo` full URL). Typically, the returned list contains only one such object. If no accessible repo
URLs are found for the local archive, then the returned list is empty. In rare cases, the local
archive can be matched to multiple repo URLs, then the returned list contains all these URLs.
"""

import functools
import inspect
import logging
import os
import re
import subprocess
from typing import List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from package_validation_tool.package.suggesting_repos import RemoteRepoSuggestion
from package_validation_tool.utils import (
    DEFAULT_REQUEST_HEADERS,
    extract_links,
    is_url_accessible,
    remove_archive_suffix,
)

MAX_RETURNED_GITHUB_API_REPOS = 3
GIT_LS_REMOTE_TIMEOUT_SECONDS = 1
RATE_LIMIT_REMAINING_GITHUB_API_WARNING = 5

log = logging.getLogger(__name__)

# silence the chardet debug logs like "chardet.charsetprober:98 utf-8 confidence = 0.87625"
chardet_level = max(log.getEffectiveLevel(), logging.INFO)
logging.getLogger("chardet").setLevel(chardet_level)


@functools.lru_cache(maxsize=512)
def _is_git_repo(repo: str) -> bool:
    """
    Check if this is an accessible git repo, without downloading it.

    First validates that the URL looks like it could be a git repository by filtering out
    URLs that definitely don't look like git repository URLs.
    """
    try:
        parsed = urlparse(repo)
    except Exception:
        log.debug("Failed to parse URL: %s", repo)
        return False

    if parsed.query or parsed.fragment:
        log.debug("Ignoring URL with non-empty query/fragment: %s", repo)
        return False

    if not parsed.path or parsed.path == "/":
        log.debug("Ignoring URL with no path: %s", repo)
        return False

    path_components = [
        component.lower() for component in parsed.path.strip("/").split("/") if component
    ]

    not_git_repo_hints = {
        "archive",
        "archives",
        "blob",
        "branch",
        "branches",
        "bug",
        "bugs",
        "commit",
        "commits",
        "pull",
        "pulls",
        "dist",
        "doc",
        "docs",
        "download",
        "issue",
        "issues",
        "raw",
        "release",
        "releases",
        "search",
        "tag",
        "tags",
        "ticket",
        "tickets",
        "tracker",
        "tree",
        "w",
        "wiki",
    }
    if any(component in not_git_repo_hints for component in path_components):
        log.debug("Ignoring URL with not-looking-like-git-repo component: %s", repo)
        return False

    if path_components:
        last_component = path_components[-1].lower()
        problematic_extensions = {
            ".asc",
            ".deb",
            ".exe",
            ".gz",
            ".htm",
            ".html",
            ".md",
            ".pdf",
            ".php",
            ".rpm",
            ".sig",
            ".sign",
            ".tar",
            ".txt",
            ".xz",
            ".zip",
        }
        if any(last_component.endswith(ext) for ext in problematic_extensions):
            log.debug("Ignoring URL with not-looking-like-git-repo extension: %s", repo)
            return False

    log.debug("Checking if URL %s is a git repository", repo)

    modified_env = os.environ.copy()
    modified_env["GIT_TERMINAL_PROMPT"] = "0"  # disable interactive credential prompting

    try:
        result = subprocess.run(
            ["git", "ls-remote", repo],
            timeout=GIT_LS_REMOTE_TIMEOUT_SECONDS,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            env=modified_env,
            text=True,
        )
        # Check that the command succeeded AND returned at least one line of output
        return bool(result.stdout.strip())

    except Exception:
        return False


def _get_project_name(archive_name: str) -> str:
    """
    Get project base name from the local archive filename (without extention and without version).

    This poor-man's logic assumes that the version starts after the last "-" symbol. It also removes
    any trailing digits (and a potential dot), e.g. `python3.9` -> `python` or `redis6` -> `redis`.
    """
    return remove_archive_suffix(archive_name).rsplit("-", 1)[0].rstrip("0123456789.")


def _suggest_repo_from_spec_sources(
    local_archive_basename: str, spec_sources: List[str]
) -> List[RemoteRepoSuggestion]:
    """
    Find repo-looking URLs in spec_sources (i.e. from the package spec file) that match the basename
    of the local archive and return the list of corresponding RemoteRepoSuggestion objects. Only
    return those URLs that are accessible repos (currently only git repos supported).
    """
    repo_results = []
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name

    project_name = _get_project_name(local_archive_basename)

    # keep only those URLs that are accessible repos (currently only git repos are supported)
    repos = [x for x in spec_sources if project_name.lower() in x.lower() and _is_git_repo(x)]

    for repo in repos:
        repo_results.append(
            RemoteRepoSuggestion(
                repo=repo,
                spec_source=repo,
                suggested_by=suggestion_name,
                notes=f"URL from spec file: matched {project_name}",
                confidence=1.0,
            )
        )

    return repo_results


def _suggest_repo_from_extracted_links(
    local_archive_basename: str, spec_sources: List[str]
) -> List[RemoteRepoSuggestion]:
    """
    Download web pages with URLs in spec_sources (i.e. from the package spec file), and then scrape
    all links in these web pages. Return only those links that (1) seem related to the local archive
    and (2) are accessible code repos (currently only git repos supported).
    """
    repo_results = []
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name

    project_name = _get_project_name(local_archive_basename)

    for spec_source in spec_sources:
        if not project_name.lower() in spec_source.lower():
            # URL from spec not related to local archive
            continue
        if not is_url_accessible(spec_source):
            continue

        extracted_links = extract_links(spec_source)
        if extracted_links is None:
            continue
        for extracted_link in extracted_links:
            if not project_name.lower() in extracted_link.lower():
                # link not related to local archive
                continue
            if not bool(re.match(r"(?i)^(git|http|https)://", extracted_link)):
                continue
            if not _is_git_repo(extracted_link):
                continue

            repo_results.append(
                RemoteRepoSuggestion(
                    repo=extracted_link,
                    spec_source=spec_source,
                    suggested_by=suggestion_name,
                    notes=f"Linked repo {extracted_link} found in URL {spec_source} from spec file",
                    confidence=1.0,
                )
            )

    return repo_results


def _suggest_repo_from_known_hostings(local_archive_basename: str, _) -> List[RemoteRepoSuggestion]:
    """
    Guess repo URL based on the basename of the local archive, trying several well-known repo
    hosting platforms (like GitLab and GitHub). Note that spec_sources are ignored here.
    """
    repo_results = []
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name

    project_name = _get_project_name(local_archive_basename)

    repos_to_try = {
        "GitHub": f"https://github.com/{project_name}/{project_name}",
        "GitLab": f"https://gitlab.com/{project_name}/{project_name}",
        "SourceForge": f"git://git.code.sf.net/p/{project_name}/{project_name}",
        "Savannah": f"https://git.savannah.gnu.org/git/{project_name}.git",
    }

    for hosting, repo in repos_to_try.items():
        if not _is_git_repo(repo):
            continue

        repo_results.append(
            RemoteRepoSuggestion(
                repo=repo,
                spec_source=None,
                suggested_by=suggestion_name,
                notes=f"Repo found on a known hosting platform {hosting}",
                confidence=1.0,
            )
        )

    return repo_results


def _suggest_repo_from_github_api(local_archive_basename: str, _) -> List[RemoteRepoSuggestion]:
    """
    Find repo URLs based on the basename of the local archive, by querying GitHub's public API.
    Limit returned repos to MAX_RETURNED_GITHUB_API_REPOS. Note that spec_sources are ignored here.

    Uses a personal GitHub token from the GITHUB_TOKEN environment variable if available, which
    provides higher rate limits than anonymous requests.
    """
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name

    # get project base name from the local archive filename (without extention and without version);
    # this poor-man's logic assumes that the version starts after the last "-" symbol
    project_name = remove_archive_suffix(local_archive_basename).rsplit("-", 1)[0]

    # Prepare headers with authentication if token is available
    headers = DEFAULT_REQUEST_HEADERS.copy()
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
        log.debug("Using authenticated GitHub API request")
    else:
        log.debug("Using anonymous GitHub API request (rate limited)")

    # GitHub API endpoint for searching repositories
    github_search_url = "https://api.github.com/search/repositories"

    log.debug("Querying GitHub for a repository called %s ...", project_name)
    params = {"q": project_name}

    try:
        response = requests.get(github_search_url, headers=headers, params=params, timeout=5)
    except Exception as e:
        log.debug("Exception when querying GitHub API: %r", e)
        return []

    # Check and report rate limiting information
    rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")

    if rate_limit_remaining is not None:
        log.debug("GitHub API rate limit remaining: %s", rate_limit_remaining)
        if int(rate_limit_remaining) <= RATE_LIMIT_REMAINING_GITHUB_API_WARNING:
            log.warning(
                "GitHub API rate limit nearly exhausted! Remaining: %s", rate_limit_remaining
            )

    if response.status_code != 200:
        if response.status_code == 403:
            if "rate limit exceeded" in response.text.lower():
                log.warning(
                    "GitHub API rate limit exceeded (HTTP 403). Consider using GITHUB_TOKEN environment variable for higher limits."
                )
            else:
                log.warning(
                    "GitHub API access forbidden (HTTP 403). Check your GITHUB_TOKEN if using authentication."
                )
        else:
            log.warning(
                "Error when querying GitHub API: HTTP %s - %s",
                response.status_code,
                response.text[:200].replace("\n", " "),
            )
        return []

    data = response.json()
    repositories = data.get("items", [])
    if not repositories:
        log.debug("No repositories found for GitHub query")
        return []

    repo_results = []

    for repo in repositories[:MAX_RETURNED_GITHUB_API_REPOS]:
        if not project_name.lower() in repo["html_url"].lower():
            # repo obtained from GitHub query is not related to the local archive
            continue

        repo_results.append(
            RemoteRepoSuggestion(
                repo=repo["html_url"],
                spec_source=None,
                suggested_by=suggestion_name,
                notes=f"Repo found on GitHub (searched for {project_name})",
                confidence=1.0,
            )
        )

    return repo_results


def _suggest_repo_from_repology_website(
    local_archive_basename: str, _
) -> List[RemoteRepoSuggestion]:
    """
    Find repo URLs based on the basename of the local archive, by querying Repology website.
    We cannot use the Repology web API (https://repology.org/api/v1) since it doesn't return the
    repo URLs. Note that spec_sources are ignored here.
    """
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name

    project_name = _get_project_name(local_archive_basename)

    # Repology endpoint for project information: automatically redirects "similar" package names,
    # e.g. if project_name == "python39-cryptography" it redirects to "python-cryptography"
    repology_url = f"https://repology.org/project/{project_name}/information"

    log.debug("Querying Repology for project %s ...", project_name)

    try:
        response = requests.get(repology_url, headers=DEFAULT_REQUEST_HEADERS, timeout=5)
        if response.status_code != 200:
            if response.status_code == 403:
                log.debug(
                    "Error when querying Repology (HTTP 403 Forbidden): %s. "
                    "This may indicate rate limiting or access restrictions. "
                    "Response headers: %s. Response text (first 200 chars): %s",
                    repology_url,
                    dict(response.headers),
                    response.text[:200] if response.text else "No response text",
                )
            else:
                log.debug(
                    "Error when querying Repology (HTTP %s): %s", response.status_code, repology_url
                )
            return []
    except Exception as e:
        log.debug("Exception when querying Repology: %r", e)
        return []

    repo_results = []
    seen_repos = set()  # Track normalized URLs to avoid duplicates
    try:
        soup = BeautifulSoup(response.content, "html.parser")

        # Find the "Repository_links" section
        repo_links_section = soup.find(id="Repository_links")
        if not repo_links_section:
            log.debug("No 'Repository_links' section found on Repology page")
            return []

        # Find the <ul> list within that section
        ul_element = repo_links_section.find_next("ul")
        if not ul_element:
            log.debug("No <ul> element found after 'Repository_links' section")
            return []

        # Extract repo URLs from <li><a href="..."> elements
        for li_element in ul_element.find_all("li"):
            a_element = li_element.find("a", href=True)
            if a_element:
                repo_url = a_element["href"]
                normalized_url = repo_url.lower().rstrip("/").removesuffix(".git")
                if normalized_url in seen_repos:
                    continue
                seen_repos.add(normalized_url)
                if _is_git_repo(repo_url):
                    log.debug("Repo found on Repology: %s", repo_url)
                    repo_results.append(
                        RemoteRepoSuggestion(
                            repo=repo_url,
                            spec_source=None,
                            suggested_by=suggestion_name,
                            notes=f"Repo found on Repology (searched for {project_name})",
                            confidence=1.0,
                        )
                    )

    except Exception as e:
        log.debug("Exception when parsing Repology HTML: %r", e)
        return []

    return repo_results


SUGGESTION_METHODS = [
    _suggest_repo_from_spec_sources,
    _suggest_repo_from_extracted_links,
    _suggest_repo_from_known_hostings,
    _suggest_repo_from_github_api,
    _suggest_repo_from_repology_website,
]
