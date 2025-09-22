# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Package-Validation-Tool module."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>, Dmitrii Kuvaiskii <dimakuv@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All rights reserved."

from package_validation_tool.utils import set_default_python_socket_timeout

# By default, Python socket module (used under the hood by requests, urllib, etc. modules) does not
# specify a timeout, and this makes all connections blocking. In particular, establish-connection
# and receive-data operations may hang indefinitely. To prevent such hangs, we set a program-wide
# default timeout (10 seconds, but can be specified explicitly via PYTHON_SOCKET_TIMEOUT envvar).
#
# For reference, see:
#   - https://docs.aws.amazon.com/codeguru/detector-library/python/socket-connection-timeout/
#   - https://docs.python.org/3/library/socket.html#notes-on-socket-timeouts
set_default_python_socket_timeout()
