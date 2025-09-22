# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import socket
import sys


def deny_nework_connections():
    def audit_hook_deny_connects(event: str, args):
        if event == "socket.connect":
            sock: socket.socket = args[0]
            if sock.family != socket.AddressFamily.AF_UNIX:
                print("Connect denied to prevent accidental Internet access", file=sys.stderr)
                raise Exception("Network connection denied to prevent accidental Internet access")
        if event == "socket.getaddrinfo":
            sock_family: socket.AddressFamily = args[2]
            if sock_family != socket.AddressFamily.AF_UNIX:
                print("Getaddrinfo denied to prevent accidental Internet access", file=sys.stderr)
                raise Exception("Getaddrinfo denied to prevent accidental Internet access")

    # introduced in Python 3.8; simply ignore in a test environment with Python <3.8
    if sys.version_info >= (3, 8):
        sys.addaudithook(audit_hook_deny_connects)


def pytest_runtest_setup():
    """
    Disable all network connectivity to make sure the tests don't download packages/sources/etc.
    """
    deny_nework_connections()

    # Let pytests find ./configuration/... files
    os.environ["ENVROOT"] = os.getcwd()
