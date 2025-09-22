# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
List of methods to perform transformations on local archives and corresponding Source stanzas.

Each function in this module is a separate transformation with the following function signature:

  def _transform_...(local_archives: list[str], spec_sources: list[str]) -> LocalArchiveTransformation

Each function takes the list of locally extracted-from-srpm archives and the corresponding list of
archive URLs from Source stanzas in the spec file and tries one specific heuristic.

Each function returns a new LocalArchiveTransformation object that contains the new lists (extracted
archives and corresponding Source stanzas) if the transformation was applied, or None if the
transformation was not applied.
"""

# due to Config.get_transformations_config(), see https://github.com/pylint-dev/pylint/issues/1498
# pylint: disable=unsubscriptable-object

import inspect
import logging
import os
import re
import tarfile
from typing import List
from urllib.parse import urlparse, urlunparse

from package_validation_tool.common import SUPPORTED_ARCHIVE_TYPES
from package_validation_tool.package.suggesting_archives import Config, LocalArchiveTransformation
from package_validation_tool.utils import secure_tar_extractall

log = logging.getLogger(__name__)


def _transform_extract_nested_archives(
    local_archives: List[str], spec_sources: List[str]
) -> LocalArchiveTransformation:
    """
    If there is a single archive file which contains only archive files (i.e., nested archives), and
    there is a single corresponding Source stanza, then replace the original `local_archives` and
    `spec_sources` with the extracted archives and their basenames correspondingly.
    """
    if len(spec_sources) != 1 or len(local_archives) != 1:
        # heuristic assumes all source archives packed in a single archive (never in >1 archive)
        return None

    if os.path.basename(spec_sources[0]) != spec_sources[0]:
        # heuristic assumes Source to be path-less name of the archive (never with dir or URL)
        return None

    # read from configuration/transformations_*.json files, see also ./__init__.py
    transformations_config = Config.get_transformations_config()
    transformation_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name
    clues_regex = transformations_config[transformation_name]["clues_regex"]
    clues_required = 1

    clues_num = sum(1 for x in clues_regex if re.search(x, spec_sources[0], flags=re.IGNORECASE))
    if clues_num < clues_required:
        return None

    local_archives_dir = os.path.dirname(local_archives[0])
    assert local_archives_dir

    with tarfile.open(local_archives[0], "r") as tar:
        only_archive_files = all(f.endswith(SUPPORTED_ARCHIVE_TYPES) for f in tar.getnames())
        if not only_archive_files:
            return None

        try:
            log.debug("Extract nested archive %s ...", local_archives[0])
            if not secure_tar_extractall(tar, local_archives_dir):
                log.error("Failed to securely extract nested archive %s", local_archives[0])
                return None
            log.info("Nested archive extracted to: %s", local_archives_dir)
        except Exception as e:
            log.warning(
                "Extracting nested archive %s failed with exception %r", local_archives[0], e
            )
            raise e

        # don't need the original archive anymore, but keep for accountability
        os.rename(local_archives[0], local_archives[0] + ".original")

        return LocalArchiveTransformation(
            name=transformation_name,
            input_local_archives=[os.path.basename(x) for x in local_archives],
            input_spec_sources=spec_sources.copy(),
            output_local_archives=tar.getnames().copy(),
            output_spec_sources=tar.getnames().copy(),
            notes=f"clues: collected {clues_num}, required {clues_required}",
            confidence=min(float(clues_num) / clues_required, 1.00),
        )


def _transform_remove_url_fragment_from_spec_sources(
    local_archives: List[str], spec_sources: List[str]
) -> LocalArchiveTransformation:
    """
    This transformation potentially modifies `spec_sources` (i.e., keeps `local_archives` as is).
    The transformation checks each Source: if it is a URL with a valid schema, then a URL fragment
    (the last part of a URL after the hash mark `#`) is removed. This is a valid transformation
    because URLs in the Sources must point to archive files, and the `#` in URL makes no sense for
    such binary files. It was observed that these `#` parts are sometimes present in spec Sources.
    """
    transformation_name = inspect.stack()[0][3].lstrip("_")  # trick to get current function name

    output_spec_sources = []
    fixed_spec_sources_cnt = 0

    for spec_source in spec_sources:
        o = urlparse(spec_source)
        if o.scheme == "https" or o.scheme == "http":
            # last item in the tuple arg to urlunparse() is the URL fragment, we keep it blank
            spec_source = urlunparse((o.scheme, o.netloc, o.path, o.params, o.query, ""))
            fixed_spec_sources_cnt += 1
        output_spec_sources.append(spec_source)

    if not fixed_spec_sources_cnt:
        return None

    return LocalArchiveTransformation(
        name=transformation_name,
        input_local_archives=[os.path.basename(x) for x in local_archives],
        input_spec_sources=spec_sources.copy(),
        output_local_archives=[os.path.basename(x) for x in local_archives],
        output_spec_sources=output_spec_sources,
        notes=f"modified {fixed_spec_sources_cnt} Sources out of {len(spec_sources)}",
        confidence=1.00,
    )


# NOTE: transformation methods are applied in order
TRANSFORMATION_METHODS = [
    _transform_extract_nested_archives,
    _transform_remove_url_fragment_from_spec_sources,
]
