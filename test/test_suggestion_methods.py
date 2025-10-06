# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from package_validation_tool.package.suggesting_archives.suggestion_methods import (
    _suggest_remote_archive_from_spec_sources_exact,
    _suggest_remote_archive_from_spec_sources_ftp_to_https,
    _suggest_remote_archive_from_spec_sources_sep_version,
)


def test_suggest_remote_archive_from_spec_sources_exact():
    def patched_is_url_accessible(url: str) -> bool:
        """Return True only for "http(s)" and "ftp" addresses, instead of accessing internet."""
        return url.startswith(("http://", "https://", "ftp://"))

    local_archive_basename = "archive-0.1.tar.gz"
    good_spec_sources = [
        "http://example.com/download/archive-0.1.tar.gz",
        "https://example.com/another/archive-0.1.tar.gz",
        "ftp://example.com/obsolete/archive-0.1.tar.gz",
    ]
    bad_spec_sources = [
        "not-a-url/archive-0.1.tar.gz",  # no match (not a URL)
        "http://example.com/download/archive-0.2.tar.gz",  # no match (wrong version)
        "https://example.com/another/archive-0.1.zip",  # no match (wrong extension)
        "ftp://example.com/obsolete/whatami-0.1.tar.gz",  # no match (wrong archive name)
    ]
    spec_sources = good_spec_sources + bad_spec_sources

    with patch(
        "package_validation_tool.package.suggesting_archives.suggestion_methods.is_url_accessible",
        patched_is_url_accessible,
    ):
        # Create mock package dictionary
        package = {"source_package_name": "archive"}

        remote_archive_results = _suggest_remote_archive_from_spec_sources_exact(
            package, local_archive_basename, spec_sources
        )

        assert len(remote_archive_results) == 3
        for remote_archive_result in remote_archive_results:
            assert remote_archive_result.remote_archive in good_spec_sources
            assert remote_archive_result.remote_archive not in bad_spec_sources


def test_suggest_remote_archive_from_spec_sources_sep_version():
    def patched_is_url_accessible(url: str) -> bool:
        """Return True only for "http(s)" and "ftp" addresses, instead of accessing internet."""
        return url.startswith(("http://", "https://", "ftp://"))

    local_archive_basename = "archive-0.1.tar.gz"
    good_spec_sources = [
        "http://example.com/download/archive-0.1.tar.gz",
        "https://example.com/fossils/archive/tags/0.1.tar.gz",
        "ftp://example.com/weirdscheme/0.1.tar.gz/archive",
    ]
    bad_spec_sources = [
        "not-a-url/archive-0.1.tar.gz",  # no match (not a URL)
        "http://example.com/download/archive-0.2.tar.gz",  # no match (wrong version)
        "https://example.com/fossils/archive/tags/0.1.zip",  # no match (wrong extension)
        "ftp://example.com/weirdscheme/0.1.tar.gz/whatami",  # no match (wrong archive name)
    ]
    spec_sources = good_spec_sources + bad_spec_sources

    with patch(
        "package_validation_tool.package.suggesting_archives.suggestion_methods.is_url_accessible",
        patched_is_url_accessible,
    ):
        # Create mock package dictionary
        package = {"source_package_name": "archive"}

        remote_archive_results = _suggest_remote_archive_from_spec_sources_sep_version(
            package, local_archive_basename, spec_sources
        )

        assert len(remote_archive_results) == 3
        for remote_archive_result in remote_archive_results:
            assert remote_archive_result.remote_archive in good_spec_sources
            assert remote_archive_result.remote_archive not in bad_spec_sources


def test_suggest_remote_archive_from_spec_sources_ftp_to_https():
    def patched_is_url_accessible(url: str) -> bool:
        """Return True only for "http(s)" addresses, instead of accessing internet."""
        return url.startswith(("http://", "https://"))

    local_archive_basename = "archive-0.1.tar.gz"
    spec_sources = {
        "ftp://example.com/download/archive-0.1.tar.gz": "https://example.com/download/archive-0.1.tar.gz",
        "ftp://ftp.other.com/fossils/archive-0.1.tar.gz": "https://ftp.other.com/fossils/archive-0.1.tar.gz",
    }

    with patch(
        "package_validation_tool.package.suggesting_archives.suggestion_methods.is_url_accessible",
        patched_is_url_accessible,
    ):
        # Create mock package dictionary
        package = {"source_package_name": "archive"}

        remote_archive_results = _suggest_remote_archive_from_spec_sources_ftp_to_https(
            package, local_archive_basename, spec_sources.keys()
        )

        assert len(remote_archive_results) == 2
        for remote_archive_result in remote_archive_results:
            assert remote_archive_result.spec_source in spec_sources.keys()
            assert (
                remote_archive_result.remote_archive
                == spec_sources[remote_archive_result.spec_source]
            )
