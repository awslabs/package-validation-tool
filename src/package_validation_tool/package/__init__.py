# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Module to implement functionality specific to package types."""

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Type, TypeVar

# Packages with support right now
SUPPORTED_PACKAGE_TYPES = ["rpm"]


class InstallationDecision(Enum):
    """Whether to attempt, and how to deal with error of, installing packages."""

    ALWAYS = "yes"
    TRY = "try"
    NO = "no"

    def __str__(self):
        return self.value


# Type variable for generic class methods
T = TypeVar("T")


class JsonSerializableMixin:
    """Mixin providing JSON serialization capabilities for dataclasses."""

    def to_json_dict(self) -> dict:
        """Return a dict of the object that can be stored as json."""

        def obj_without_internal_fields(obj):
            # remove internal fields (those starting with _) from JSON serialization
            if isinstance(obj, dict):
                return {
                    k: obj_without_internal_fields(v)
                    for k, v in obj.items()
                    if not k.startswith("_")
                }
            elif isinstance(obj, list):
                return [obj_without_internal_fields(item) for item in obj]
            return obj

        return obj_without_internal_fields(dataclasses.asdict(self))

    def write_json_output(self, output_path: str):
        """Write result in JSON format to given path."""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_json_dict(), f, indent=2)

    @classmethod
    def from_dict(cls: Type[T], json_dict: dict) -> T:
        """Create instance from dictionary."""
        return cls(**json_dict)


@dataclass
class FileMatchingStatsMixin:
    """Mixin providing file matching statistics fields."""

    files_total: int = 0
    files_matched: int = 0
    files_different: int = 0
    files_no_counterpart: int = 0

    files_matched_ratio: float = 0.0
    files_different_ratio: float = 0.0
    files_no_counterpart_ratio: float = 0.0

    # dict of "file in upstream source -> NO_COUNTERPART/DIFFERENT conflict"
    conflicts: Dict[str, str] = field(default_factory=dict)


@dataclass
class PackageResultMixin:
    """Mixin providing common package result fields."""

    matching: bool
    source_package_name: str = None
    archive_hashes: Dict[str, str] = field(default_factory=dict)

    # Package state indicators
    srpm_available: bool = True
    spec_valid: bool = True
    source_extractable: bool = True

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        """Reconstruct nested dataclass objects from dicts after cache restoration."""
        if hasattr(self, "results") and hasattr(self, "_result_class") and self._result_class:
            # dataclass doesn't support nested dataclasses out of the box, thus if
            # this object is restored from cache on disk (see operation_cache.py),
            # then `results` will contain dicts, not the proper dataclass objects
            for item_list in self.results.values():
                for idx, item in enumerate(item_list):
                    if isinstance(item, dict):
                        item_list[idx] = self._result_class(**item)


@dataclass
class SuggestionMixin:
    """Mixin providing common suggestion fields."""

    spec_source: str = None
    suggested_by: str = None
    notes: str = None
    confidence: float = 0.00  # 0.00 .. 1.00


@dataclass
class UpstreamMatchingMixin:
    """Mixin providing common remote accessibility and matching status fields."""

    accessible: bool = False
    matched: bool = False


@dataclass
class RemoteArchiveResult(JsonSerializableMixin, FileMatchingStatsMixin, UpstreamMatchingMixin):
    """Result of matching a package local archive."""

    remote_archive: str = None


@dataclass
class PackageRemoteArchivesResult(JsonSerializableMixin, PackageResultMixin):
    """Result of matching remote archives for each local archive in the source package."""

    _result_class: Type[Any] = field(default=RemoteArchiveResult)

    results: Dict[str, List[RemoteArchiveResult]] = field(
        default_factory=dict
    )  # dict of "local archive -> list of remote archives and their matching status"

    unused_spec_sources: List[str] = field(
        default_factory=list
    )  # spec Source lines that are not used / not accessible


@dataclass
class RemoteRepoResult(JsonSerializableMixin, FileMatchingStatsMixin, UpstreamMatchingMixin):
    """Result of remote repo matching a package local archive."""

    remote_repo: str = None

    # particular version in the repo; tag may be empty/None (if corresponding version in the
    # repository is identified solely by the commit hash)
    commit_hash: str = None
    tag: str = None

    # Autotools-related fields
    autotools_applied: bool = False
    tools_versions: Dict[str, str] = field(default_factory=dict)


@dataclass
class PackageRemoteReposResult(JsonSerializableMixin, PackageResultMixin):
    """Result of matching remote repos for each local archive in the source package."""

    _result_class: Type[Any] = field(default=RemoteRepoResult)

    results: Dict[str, List[RemoteRepoResult]] = field(
        default_factory=dict
    )  # dict of "local archive -> list of remote repos and their matching status"
