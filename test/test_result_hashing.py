# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import dataclasses
import json
import os
import tempfile
from pathlib import Path

from package_validation_tool.operation_cache import (
    load_return_value_from_cache_file,
    store_return_value_in_cache_file,
)
from package_validation_tool.package import PackageRemoteArchivesResult, RemoteArchiveResult
from package_validation_tool.package.rpm.source_package import RPMSourcepackage

TEST_DIR_PATH = os.path.dirname(__file__)
TESTRPM_SPEC_FILE = Path(TEST_DIR_PATH) / "artefacts" / "rpm" / "testrpm.spec"


def test_remotematchresult_hashing():
    """Test whether PackageRemoteArchivesResult objects can be hashed."""

    srpm_result = PackageRemoteArchivesResult(
        matching=True,
        results={"test": [RemoteArchiveResult(remote_archive="testrpm", matched=True)]},
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = os.path.join(temp_dir, "cache.json")

        cache_meta_data = {
            "test_metadata": "test_value",
        }

        # write temporary cache
        cache_entry = {
            "metadata": cache_meta_data,
            "result": srpm_result.to_json_dict(),
        }
        with open(cache_file, "w") as f:
            json.dump(cache_entry, f, indent=2)

        # read cache
        with open(cache_file, "r") as f:
            cache_entry = json.load(f)

        # validate cached data
        assert cache_entry["metadata"] == cache_meta_data
        assert (
            cache_entry["result"] == srpm_result.to_json_dict()
            if dataclasses.is_dataclass(srpm_result)
            else srpm_result
        )

        # load from cache and compare properties with original object
        cached_srpm_result = PackageRemoteArchivesResult.from_dict(cache_entry["result"])
        assert cached_srpm_result.matching == srpm_result.matching


def test_remotematchresult_caching():
    """Test whether PackageRemoteArchivesResult objects can be cached and reloaded."""

    srpm_result = PackageRemoteArchivesResult(
        matching=True,
        results={"test": [RemoteArchiveResult(remote_archive="testrpm", matched=True)]},
    )

    cache_meta_data = {
        "test_metadata": "test_value",
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = os.path.join(temp_dir, "cache.json")

        store_return_value_in_cache_file(
            cache_file,
            RPMSourcepackage.match_remote_archives,
            srpm_result,
            cache_meta_data=cache_meta_data,
        )
        cached_srpm_result = load_return_value_from_cache_file(
            cache_file, RPMSourcepackage.match_remote_archives, cache_meta_data=cache_meta_data
        )
        assert cached_srpm_result is not None
        assert cached_srpm_result.matching == srpm_result.matching
