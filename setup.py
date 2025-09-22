# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Package-Validation-Tool packaging setup.
"""

import os

from setuptools import setup

# Declare your non-python data files:
# Files underneath configuration/ will be copied into the build preserving the
# subdirectory structure if they exist.
data_files = []
for root, dirs, files in os.walk("configuration"):
    data_files.append((root, [os.path.join(root, f) for f in files]))

setup(
    # include data files
    data_files=data_files,
)
