# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Module to implement suggestions of (git) repos based on heuristics."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List

from package_validation_tool.package import JsonSerializableMixin, SuggestionMixin


@dataclass
class RemoteRepoSuggestion(JsonSerializableMixin, SuggestionMixin):
    """Result of suggesting a repo for a local archive in the package."""

    repo: str = None

    # particular version in the repo; tag may be empty/None (if corresponding version in the
    # repository is identified solely by the commit hash)
    commit_hash: str = None
    tag: str = None


@dataclass
class PackageRemoteReposSuggestions(JsonSerializableMixin):
    """
    Result of suggesting (git) repos for local archives in the source package.

    Also contains a list of local archives and spec source lines, for convenience.
    """

    source_package_name: str = None

    local_archives: List[str] = field(default_factory=list)

    suggestions: Dict[str, List[RemoteRepoSuggestion]] = field(
        default_factory=dict
    )  # dict of "local archive -> list of suggested repos"

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        # dataclass doesn't support nested dataclasses out of the box, thus if
        # PackageRemoteReposSuggestions object is restored from the cache on disk (see
        # operation_cache.py), then `suggestions` will contains dicts, not RemoteRepoSuggestion
        for sugg_list in self.suggestions.values():
            for idx, sugg in enumerate(sugg_list):
                if isinstance(sugg, dict):
                    sugg_list[idx] = RemoteRepoSuggestion(**sugg)


@dataclass
class PackageRemoteReposStats(JsonSerializableMixin):
    """Statistics on the suggestions (repo URLs) found for a given package."""

    suggested_local_archives: int = 0
    total_local_archives: int = 0
    suggested_archives_ratio: float = 0.00
