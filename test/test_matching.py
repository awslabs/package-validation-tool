# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from package_validation_tool.matching.file_matching import compare_strings_ignore_date_numbers


def test_identical_strings():
    assert compare_strings_ignore_date_numbers("Hello, world!", "Hello, world!")


def test_different_strings():
    assert not compare_strings_ignore_date_numbers("Hello, world!", "Hello, universe!")


def test_strings_with_dates():
    assert compare_strings_ignore_date_numbers(
        "The event is on 10/25/2024", "The event is on 05-12-2024"
    )


def test_strings_with_mixed_dates_and_years():
    assert compare_strings_ignore_date_numbers(
        "The event is on 10/25/2024 in 2024", "The event is on 05-12-2024 in 2024"
    )


def test_empty_strings():
    assert compare_strings_ignore_date_numbers("", "")


def test_one_empty_string():
    assert not compare_strings_ignore_date_numbers("", "Hello, world!")


def test_strings_with_spelled_out_dates():
    assert compare_strings_ignore_date_numbers(
        "Released January 02, 2023", "Released April 26, 2024"
    )


def test_strings_with_abbreviated_month_dates():
    assert compare_strings_ignore_date_numbers("Built on Apr 26, 2023", "Built on Nov 3, 2025")


def test_strings_with_year_ranges():
    assert compare_strings_ignore_date_numbers(
        "Copyright 2020-2023 Author", "Copyright 2020-2025 Author"
    )


def test_strings_with_standalone_years():
    assert compare_strings_ignore_date_numbers("Copyright 2023 Author", "Copyright 2025 Author")
