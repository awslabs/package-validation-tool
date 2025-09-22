# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Module to implement file-matching functionality."""

import os
import pathlib

AUTOTOOLS_PATCHES_DIR = (
    pathlib.Path(os.environ.get("ENVROOT", ".")).absolute() / "configuration/external_patches"
)
