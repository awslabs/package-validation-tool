# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test CLI functionality
"""

import pytest

from package_validation_tool.cli import parse_args


def test_help_output():
    with pytest.raises(SystemExit):
        parse_args(["unknowncommand", "--some", "--parameter"])


def test_match_files():
    args = parse_args(["match-files", "--left", "a", "-r", "b"])
    assert args["left"] == "a"
    assert args["right"] == "b"
