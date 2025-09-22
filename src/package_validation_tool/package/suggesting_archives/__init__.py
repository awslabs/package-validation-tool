# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Module to implement suggestions of remote archives based on heuristics."""

import glob
import json
import os
import pathlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List

from package_validation_tool.package import JsonSerializableMixin, SuggestionMixin


@dataclass
class LocalArchiveTransformation:
    """Result of transforming local archives and corresponding spec Sources in the package."""

    name: str = None
    input_local_archives: List[str] = field(default_factory=list)
    input_spec_sources: List[str] = field(default_factory=list)
    output_local_archives: List[str] = field(default_factory=list)
    output_spec_sources: List[str] = field(default_factory=list)
    notes: str = None
    confidence: float = 0.00  # 0.00 .. 1.00


@dataclass
class RemoteArchiveSuggestion(JsonSerializableMixin, SuggestionMixin):
    """Result of suggesting a remote archive for a local archive in the package."""

    remote_archive: str = None


@dataclass
class PackageRemoteArchivesSuggestions(JsonSerializableMixin):
    """
    Result of suggesting remote archives for local archives in the source package. Optionally
    contains a list of transformations applied on local archives/spec source lines before searching
    for remote archives.

    Also contains a list of original (before transformations) and "transformed" (after
    transformations) local archives and spec source lines. If no transformations were applied, then
    original and "transformed" lists will be identical.
    """

    source_package_name: str = None

    orig_local_archives: List[str] = field(default_factory=list)
    orig_spec_sources: List[str] = field(default_factory=list)
    trans_local_archives: List[str] = field(default_factory=list)
    trans_spec_sources: List[str] = field(default_factory=list)

    transformations: List[LocalArchiveTransformation] = field(default_factory=list)
    suggestions: Dict[str, List[RemoteArchiveSuggestion]] = field(
        default_factory=dict
    )  # dict of "local archive -> list of suggested remote archives"
    unused_spec_sources: List[str] = field(default_factory=list)

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        # dataclass doesn't support nested dataclasses out of the box, thus if
        # PackageRemoteArchivesSuggestions object is restored from the cache on disk (see
        # operation_cache.py), then `transformations` and `suggestions` will contains dicts, not
        # LocalArchiveTransformation and RemoteArchiveSuggestion
        for idx, trans in enumerate(self.transformations):
            if isinstance(trans, dict):
                self.transformations[idx] = LocalArchiveTransformation(**trans)
        for sugg_list in self.suggestions.values():
            for idx, sugg in enumerate(sugg_list):
                if isinstance(sugg, dict):
                    sugg_list[idx] = RemoteArchiveSuggestion(**sugg)


@dataclass
class PackageRemoteArchivesStats(JsonSerializableMixin):
    """Statistics on the transformations applied and suggestions found for a given package."""

    transformations_applied: int = 0
    suggested_local_archives: int = 0
    total_local_archives: int = 0
    suggested_archives_ratio: float = 0.00
    unused_spec_sources: int = 0
    all_spec_sources: int = 0
    unused_specs_ratio: float = 0.00


class Config:
    """Get configuration rules/patterns from `{transformations,suggestions}_*.json` files."""

    _transformations_config: dict = None
    _suggestions_config: dict = None

    @staticmethod
    def _merge(a: dict, b: dict, path: list):
        # NOTE: this func updates dict `a`
        for key in b:
            if key.startswith("_"):
                continue
            if key in a:
                if isinstance(a[key], dict) and isinstance(b[key], dict):
                    Config._merge(a[key], b[key], path + [str(key)])
                elif isinstance(a[key], list) and isinstance(b[key], list):
                    a[key].extend(b[key])
                elif a[key] != b[key]:
                    raise KeyError("Conflict at " + ".".join(path + [str(key)]))
            else:
                a[key] = b[key]
        return a

    @staticmethod
    def _get_config(config_files_glob: str) -> dict:
        config_dir = pathlib.Path(os.environ.get("ENVROOT", ".")) / "configuration/"

        config = dict()
        config_files = glob.glob(os.path.join(config_dir, config_files_glob))
        for filename in config_files:
            with open(filename, "r", encoding="utf-8") as f:
                Config._merge(config, json.load(f), list())
        return config

    @classmethod
    def get_transformations_config(cls) -> dict:
        if cls._transformations_config is None:
            cls._transformations_config = cls._get_config("transformations_*.json")
        return cls._transformations_config

    @classmethod
    def get_suggestions_config(cls) -> dict:
        if cls._suggestions_config is None:
            cls._suggestions_config = cls._get_config("suggestions_*.json")
        return cls._suggestions_config
