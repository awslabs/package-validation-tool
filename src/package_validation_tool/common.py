# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Common definitions for the project
"""

import shutil
import string

# NOTE: Use tuples instead of lists due to better performance and because they are preferred over
#       lists in funcs like endswith(). See also:
#       - https://stackoverflow.com/questions/626759/whats-the-difference-between-lists-and-tuples
#       - https://docs.python.org/3/library/stdtypes.html#str.endswith

archive_formats = shutil.get_unpack_formats()
SUPPORTED_ARCHIVE_TYPES = tuple([ext for format_info in archive_formats for ext in format_info[1]])

BINARY_FILE_TYPES = (".a", ".pdf", ".png", ".svg")

RANDOM_STRING_BASE_CHARACTERS = string.ascii_letters + string.digits
