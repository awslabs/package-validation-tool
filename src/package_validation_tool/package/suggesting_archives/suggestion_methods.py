# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
List of methods to suggest remote archives' URLs for local archives.

Each function in this module has the following function signature:

  def _suggest_*(local_archive_basename: str, spec_sources: list[str]) -> list[RemoteArchiveSuggestion]

Each function takes a locally extracted-from-srpm archive and the corresponding list of this
archive's URLs from Source stanzas in the spec file and tries one specific heuristic to find
accessible URLs with matching remote archives.

Each function returns a list of RemoteArchiveSuggestion objects (with the most important field being
`remote_archive` full URL). Typically, the returned list contains only one such object. If no
accessible URLs are found for the local archive, then the returned list is empty. In rare cases, the
local archive can be matched to multiple URLs, then the returned list contains all these URLs.
"""

# due to Config.get_suggestions_config(), see https://github.com/pylint-dev/pylint/issues/1498
# pylint: disable=unsubscriptable-object

import inspect
import logging
import os
from typing import List
from urllib.parse import urlparse, urlunparse

from package_validation_tool.common import SUPPORTED_ARCHIVE_TYPES
from package_validation_tool.package.suggesting_archives import Config, RemoteArchiveSuggestion
from package_validation_tool.utils import is_url_accessible

log = logging.getLogger(__name__)


def _suggest_remote_archive_from_spec_sources_exact(
    local_archive_basename: str, spec_sources: List[str]
) -> List[RemoteArchiveSuggestion]:
    """
    Find the Source stanza(s) in spec_sources that match the basename of the local_archive and
    return the list of corresponding RemoteArchiveSuggestion objects. Only return those Source
    stanzas that are accessible URLs.
    """
    remote_archive_results = []
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name

    matching_spec_sources = [x for x in spec_sources if local_archive_basename in x]
    for matching_spec_source in matching_spec_sources:
        if is_url_accessible(matching_spec_source):
            remote_archive_results.append(
                RemoteArchiveSuggestion(
                    remote_archive=matching_spec_source,
                    spec_source=matching_spec_source,
                    suggested_by=suggestion_name,
                    notes="from Source stanza of spec file, exact match (no guessing)",
                    confidence=1.00,
                )
            )

    return remote_archive_results


def _suggest_remote_archive_from_spec_sources_sep_version(
    local_archive_basename: str, spec_sources: List[str]
) -> List[RemoteArchiveSuggestion]:
    """
    Find the Source stanza(s) in spec_sources that match the name + version of the local_archive and
    return the list of corresponding RemoteArchiveSuggestion objects. Only return those Source
    stanzas that are accessible URLs.

    In contrast to _suggest_remote_archive_from_spec_sources_exact(), this heuristic splits the
    basename of the local archive into a tuple (name, version_extension) and returns only those
    Source stanzas that contain both items of the tuple. Example:
        bottle-0.1.tar.gz -> https://github.com/bottlepy/bottle/archive/0.1.tar.gz
        (here name="bottle" and version_extension="0.1.tar.gz")
    """
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name

    # this poor-man's logic assumes that the version starts after the last "-" symbol
    name_and_version_extension = local_archive_basename.rsplit("-", 1)
    if len(name_and_version_extension) != 2:
        return []

    name, version_extension = name_and_version_extension

    remote_archive_results = []
    matching_spec_sources = [x for x in spec_sources if name in x and version_extension in x]
    for matching_spec_source in matching_spec_sources:
        if is_url_accessible(matching_spec_source):
            remote_archive_results.append(
                RemoteArchiveSuggestion(
                    remote_archive=matching_spec_source,
                    spec_source=matching_spec_source,
                    suggested_by=suggestion_name,
                    notes="from Source stanza of spec file, split name and version (no guessing)",
                    confidence=1.00,
                )
            )

    return remote_archive_results


def _suggest_remote_archive_from_spec_sources_ftp_to_https(
    local_archive_basename: str, spec_sources: List[str]
) -> List[RemoteArchiveSuggestion]:
    """
    Find FTP-based Source stanza(s) in spec_sources that match the basename of the local_archive,
    replace FTP with HTTPS and return the list of corresponding RemoteArchiveSuggestion objects.

    E.g. ftp://ftp.openbsd.org/pub/OpenBSD/OpenSSH/portable/openssh-7.4p1.tar.gz ->
             https://ftp.openbsd.org/pub/OpenBSD/OpenSSH/portable/openssh-7.4p1.tar.gz
    """
    remote_archive_results = []
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name

    matching_spec_sources = [x for x in spec_sources if local_archive_basename in x]
    for matching_spec_source in matching_spec_sources:
        o = urlparse(matching_spec_source)
        if o.scheme != "ftp":
            continue

        fixed_spec_source = urlunparse(("https", o.netloc, o.path, o.params, o.query, o.fragment))

        if is_url_accessible(fixed_spec_source):
            remote_archive_results.append(
                RemoteArchiveSuggestion(
                    remote_archive=fixed_spec_source,
                    spec_source=matching_spec_source,
                    suggested_by=suggestion_name,
                    notes="from Source stanza of spec file, ftp:// replaced with https://",
                    confidence=1.00,
                )
            )

    return remote_archive_results


def _suggest_remote_archive_from_known_urls_exact(
    local_archive_basename: str, spec_sources: List[str]
) -> List[RemoteArchiveSuggestion]:
    """
    Find the archive among known URLs and return the list of corresponding RemoteArchiveSuggestion
    objects. The remote archive must have the same basename as the local archive's basename.
    """
    remote_archive_results = []

    # read from configuration/suggestions_*.json files, see also ./__init__.py
    suggestions_config = Config.get_suggestions_config()
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name
    known_urls = suggestions_config[suggestion_name]["known_urls"]
    known_urls = [x["url"] for x in known_urls]

    for url_dir in known_urls:
        remote_archive_path = os.path.join(url_dir, local_archive_basename)
        if not is_url_accessible(remote_archive_path):
            continue
        matching_spec_sources = [x for x in spec_sources if local_archive_basename in x]
        remote_archive_results.append(
            RemoteArchiveSuggestion(
                remote_archive=remote_archive_path,
                spec_source=" ".join(matching_spec_sources) if matching_spec_sources else None,
                suggested_by=suggestion_name,
                notes="from the list of known URLs, exact match (no guessing)",
                confidence=1.00,
            )
        )

    return remote_archive_results


def _suggest_remote_archive_that_was_moved_and_recompressed(
    local_archive_basename: str, spec_sources: List[str]
) -> List[RemoteArchiveSuggestion]:
    """
    Find the archive that has a valid-looking but inaccessible Source stanza, by assuming that the
    archive was moved to another directory under the same URL domain and possibly recompressed.

    Example: zlib package, see https://github.com/madler/zlib/issues/649. E.g., Source0 contains
    "https://www.zlib.net/zlib-1.2.11.tar.xz" but it is moved under fossils/ and recompressed:
    "https://www.zlib.net/fossils/zlib-1.2.11.tar.gz".
    """
    remote_archive_results = []

    # read from configuration/suggestions_*.json files, see also ./__init__.py
    suggestions_config = Config.get_suggestions_config()
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name
    config = suggestions_config[suggestion_name]

    for replacement in config.get("replacements", list()):
        local_archive_type = next(
            t for t in SUPPORTED_ARCHIVE_TYPES if local_archive_basename.endswith(t)
        )
        assert local_archive_type

        rfrom = replacement["from"].replace("<archive_basename>", local_archive_basename)
        rto = replacement["to"].replace("<archive_basename>", local_archive_basename)

        matching_spec_sources = [x for x in spec_sources if local_archive_basename in x]
        for url_from_spec in matching_spec_sources:
            # file was moved
            url_moved = url_from_spec.replace(rfrom, rto)
            for arch_type in SUPPORTED_ARCHIVE_TYPES:
                # file was recompressed (search includes original arch type)
                url_recompressed = url_moved.replace(local_archive_type, arch_type)
                if is_url_accessible(url_recompressed):
                    remote_archive_results.append(
                        RemoteArchiveSuggestion(
                            remote_archive=url_recompressed,
                            spec_source=" ".join(matching_spec_sources),
                            suggested_by=suggestion_name,
                            notes="archive moved under same URL domain and possibly recompressed",
                            confidence=1.00,
                        )
                    )
                    # no need to check other archive types, report only the first found one
                    break

    return remote_archive_results


def _suggest_remote_archive_from_another_subdomain_url(
    local_archive_basename: str, spec_sources: List[str]
) -> List[RemoteArchiveSuggestion]:
    """
    Find the archive that has a valid-looking but inaccessible Source stanza, by assuming that the
    archive was moved to a URL with the same domain but a different subdomain.

    Example: Apache web server (httpd) package. E.g., Source0 contains
    "https://www.apache.org/dist/httpd/httpd-2.4.62.tar.bz2" but it is moved to:
    "https://archive.apache.org/dist/httpd/httpd-2.4.62.tar.bz2".
    """

    def replace_subdomain(url, new_subdomain):
        o = urlparse(url)
        parts = o.netloc.split(".")
        if len(parts) > 2:
            new_netloc = new_subdomain + "." + ".".join(parts[1:])
        else:
            new_netloc = new_subdomain + "." + o.netloc
        return urlunparse((o.scheme, new_netloc, o.path, o.params, o.query, o.fragment))

    remote_archive_results = []

    # read from configuration/suggestions_*.json files, see also ./__init__.py
    suggestions_config = Config.get_suggestions_config()
    suggestion_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name
    subdomains = suggestions_config[suggestion_name]["subdomains"]

    matching_spec_sources = [x for x in spec_sources if local_archive_basename in x]
    for matching_spec_source in matching_spec_sources:
        if bool(urlparse(matching_spec_source).scheme) is False:
            # invalid URL, skip it
            continue
        for subdomain in subdomains:
            new_url = replace_subdomain(matching_spec_source, subdomain)
            if is_url_accessible(new_url):
                remote_archive_results.append(
                    RemoteArchiveSuggestion(
                        remote_archive=new_url,
                        spec_source=matching_spec_source,
                        suggested_by=suggestion_name,
                        notes="archive was moved under different subdomain in the same URL domain",
                        confidence=1.00,
                    )
                )

    return remote_archive_results


SUGGESTION_METHODS = [
    _suggest_remote_archive_from_spec_sources_exact,
    _suggest_remote_archive_from_spec_sources_sep_version,
    _suggest_remote_archive_from_spec_sources_ftp_to_https,
    _suggest_remote_archive_from_known_urls_exact,
    _suggest_remote_archive_that_was_moved_and_recompressed,
    _suggest_remote_archive_from_another_subdomain_url,
]
