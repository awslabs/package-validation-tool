#!/usr/bin/env python
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Package-Validation-Tool

This tool allows to validate a given package. Related activities can be
triggered independently through different commands available in the CLI
of the tool.
"""

import argparse
import logging
import sys

from package_validation_tool.matching.file_matching import match_files
from package_validation_tool.operation_cache import initialize_cache, manage_cache
from package_validation_tool.package import SUPPORTED_PACKAGE_TYPES, InstallationDecision
from package_validation_tool.package.suggesting_archives.core import suggest_remote_package_archives
from package_validation_tool.package.suggesting_repos.core import suggest_package_repos
from package_validation_tool.package.validation import (
    match_package_archives,
    match_package_repos,
    store_package_content,
    validate_package,
    validate_system_packages,
)

log = logging.getLogger(__name__)


def installation_decision(value: str) -> InstallationDecision:
    """Convert string into InstallationDecision type, to convert during parsing CLI."""
    try:
        return InstallationDecision(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid installation decision: {value}") from e


def add_output_json_parameter(parser):
    """Add an argument to the parser to store data in JSON."""
    parser.add_argument(
        "-o",
        "--output-json-path",
        type=str,
        default=None,
        help="Write obtained result in JSON format to given path",
    )


def add_package_type_parameter(parser):
    """Add an argument to the parser to specify the package type."""
    parser.add_argument(
        "-t",
        "--package-type",
        type=str,
        default="rpm",
        choices=SUPPORTED_PACKAGE_TYPES,
        help="The type of the package.",
    )


def add_srpm_file_parameter(parser):
    """Add an argument to the parser to specify the SRPM file to be used."""
    parser.add_argument(
        "-s",
        "--srpm-file",
        type=str,
        help="Local SRPM file to be used in the analysis (instead of downloading).",
    )


def add_autotools_parameters(parser):
    """Add autotools-related arguments to the parser."""
    parser.add_argument(
        "--autotools-dir",
        type=str,
        default="./autotools-cache",
        help="Directory where Autotools will be downloaded and installed (default: %(default)s)",
    )
    parser.add_argument(
        "--apply-autotools",
        action="store_true",
        dest="apply_autotools",
        default=True,
        help="Apply Autotools before performing matching (default: %(default)s)",
    )
    parser.add_argument(
        "--no-apply-autotools",
        action="store_false",
        dest="apply_autotools",
        help="Do not apply Autotools",
    )


def add_match_files_parser(parent):
    """Create parser to match files."""

    parser = parent.add_parser(
        "match-files",
        description=match_files.__doc__,
    )
    parser.set_defaults(command=match_files)
    parser.add_argument(
        "-l",
        "--left",
        type=str,
        required=True,
        help="File/directory to be matched",
    )
    parser.add_argument(
        "-r",
        "--right",
        type=str,
        required=True,
        help="File/directory to be used as source for matching",
    )


def add_package_match_archives_parser(parent):
    """Create parser to match package archives."""

    parser = parent.add_parser(
        "match-package-archives",
        description=match_package_archives.__doc__,
    )
    parser.set_defaults(command=match_package_archives)

    parser.add_argument(
        "-p",
        "--package-name",
        type=str,
        required=True,
        help="The name of the package to match the archives for.",
    )
    parser.add_argument(
        "-i",
        "--input-archives-json-path",
        type=str,
        required=False,
        help="JSON file containing suggested archives (output of `suggest-package-archives` subcommand).",
    )
    add_package_type_parameter(parser)
    add_output_json_parameter(parser)


def add_package_match_repos_parser(parent):
    """Create parser to match package repositories."""

    parser = parent.add_parser(
        "match-package-repos",
        description=match_package_repos.__doc__,
    )
    parser.set_defaults(command=match_package_repos)

    parser.add_argument(
        "-p",
        "--package-name",
        type=str,
        required=True,
        help="The name of the package to match the repositories for.",
    )
    parser.add_argument(
        "-i",
        "--input-repos-json-path",
        type=str,
        required=False,
        help="JSON file containing suggested repos (output of `suggest-package-repos` subcommand).",
    )
    add_package_type_parameter(parser)
    add_output_json_parameter(parser)
    add_autotools_parameters(parser)


def add_package_suggest_remote_archives_parser(parent):
    """Create parser to suggest remote (upstream) package archives based on several heuristics."""

    parser = parent.add_parser(
        "suggest-package-archives",
        description="Suggest remote (upstream) package archives based on several heuristics",
    )
    parser.set_defaults(command=suggest_remote_package_archives)

    parser.add_argument(
        "-p",
        "--package-name",
        type=str,
        required=True,
        help="The name of the package to suggest the remote archives for.",
    )
    parser.add_argument(
        "--transform-archives",
        action="store_true",
        default=False,
        help="Apply transformations on the archives/spec Source stanzas.",
    )
    add_srpm_file_parameter(parser)
    add_package_type_parameter(parser)
    add_output_json_parameter(parser)


def add_package_suggest_package_repos(parent):
    """Create parser to suggest (git) repos for a package based on several heuristics."""

    parser = parent.add_parser(
        "suggest-package-repos",
        description="Suggest (git) repos for a package based on several heuristics",
    )
    parser.set_defaults(command=suggest_package_repos)

    parser.add_argument(
        "-p",
        "--package-name",
        type=str,
        required=True,
        help="The name of the package to suggest the repo for.",
    )
    add_srpm_file_parameter(parser)
    add_package_type_parameter(parser)
    add_output_json_parameter(parser)


def add_package_store_parser(parent):
    """Store package's SOURCE and SPECS directory to a new directory."""

    parser = parent.add_parser(
        "store-package",
        description=store_package_content.__doc__,
    )
    parser.set_defaults(command=store_package_content)

    parser.add_argument(
        "-p",
        "--package-name",
        type=str,
        required=True,
        help="The name of the package to initialize the store for.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        required=True,
        help="Directory to store package source and spec files.",
    )
    add_package_type_parameter(parser)


def add_package_validation_parser(parent):
    """Create parser for validating a given package."""

    parser = parent.add_parser(
        "validate-package",
        description=validate_package.__doc__,
    )
    parser.set_defaults(command=validate_package)

    parser.add_argument(
        "-p",
        "--package",
        type=str,
        required=True,
        help="Name of the package to analyze.",
    )
    parser.add_argument(
        "-i",
        "--install-build-deps",
        type=installation_decision,
        help="Install build dependencies for the received SRPM as well.",
        choices=list(InstallationDecision),
        default="no",
    )

    add_srpm_file_parameter(parser)
    add_package_type_parameter(parser)
    add_output_json_parameter(parser)
    add_autotools_parameters(parser)


def add_system_validation_parser(parent):
    """Create parser for validating all system packages."""

    parser = parent.add_parser(
        "validate-system-packages",
        description=validate_system_packages.__doc__,
    )
    parser.set_defaults(command=validate_system_packages)

    parser.add_argument(
        "-n",
        "--nr-packages-to-check",
        type=int,
        help="Only process a random subset of packages of the given size.",
    )
    parser.add_argument(
        "-N",
        "--nr-processes",
        type=int,
        help="Use the given number of processes for parallelizing over packages.",
    )
    parser.add_argument(
        "-e",
        "--extra-package",
        type=str,
        action="append",
        dest="extra_packages",
        help="Add an extra package to be validated.",
    )

    add_package_type_parameter(parser)
    add_output_json_parameter(parser)
    add_autotools_parameters(parser)


def add_cache_parser(parent):
    """Create parser for interacting with the operations cache."""

    parser = parent.add_parser(
        "cache",
        description=manage_cache.__doc__,
    )
    parser.set_defaults(command=manage_cache)
    parser.add_argument(
        "-c",
        "--clean",
        action="store_true",
        help="Clean the operations cache",
    )


def parse_args(given_args=None):
    """Parse args to be compatible with the used clients, return as dict."""

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-l",
        "--level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"],
        help="Set loglevel for the script (default WARNING)",
        default="INFO",
    )
    parser.add_argument(
        "-C",
        "--op-cache-directory",
        type=str,
        help="Store results of function calls in this directory",
    )
    parser.add_argument(
        "--override-cache",
        action="store_true",
        default=False,
        help="Do not read from the cache, but store new results",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True
    add_match_files_parser(subparsers)
    add_package_match_archives_parser(subparsers)
    add_package_match_repos_parser(subparsers)
    add_package_suggest_remote_archives_parser(subparsers)
    add_package_suggest_package_repos(subparsers)
    add_package_validation_parser(subparsers)
    add_system_validation_parser(subparsers)
    add_package_store_parser(subparsers)
    add_cache_parser(subparsers)

    return vars(parser.parse_args(given_args))


def main(given_args=None):
    args = parse_args(given_args=given_args)
    logging.basicConfig(
        format="[%(levelname)-7s] %(asctime)s %(name)s:%(lineno)d %(message)s",
        level=args.get("level", "INFO"),
    )
    args.pop("level", None)
    log.debug("Parsed args %r", args)

    # setup cache
    cache_directory = args.pop("op_cache_directory", None)
    override_cache = args.pop("override_cache", False)
    initialize_cache(cache_directory, write_only=override_cache)

    # run the function from CLI
    return_success = args.pop("command")(**args)
    log.debug("Command was executed and returned success: %r", return_success)
    return 0 if return_success else 1


if __name__ == "__main__":
    sys.exit(main())
