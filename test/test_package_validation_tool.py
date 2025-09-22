# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for Package-Validation-Tool module."""

import pytest


@pytest.mark.xfail
def test_that_you_wrote_tests():
    """Test that you wrote tests."""
    from textwrap import dedent

    assertion_string = dedent(
        """\
    No, you have not written tests.

    However, unless a test is run, the pytest execution will fail
    due to no tests or missing coverage. So, write a real test and
    then remove this!
    """
    )
    assert False, assertion_string


def test_package_validation_tool_importable():
    """Test package_validation_tool is importable."""
    import package_validation_tool  # noqa: F401
