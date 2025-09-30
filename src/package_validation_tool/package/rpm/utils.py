# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Module to help work with RPM packages.
"""

import glob
import logging
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from subprocess import DEVNULL
from typing import Dict, List, Optional, Tuple

from package_validation_tool.utils import pushd, versions_is_greater

log = logging.getLogger(__name__)


# known package endings to be stripped to get basename of package
KNOWN_PACKAGE_ENDINGS = [
    ".aarch64",
    ".aarch64.rpm",
    ".i686",
    ".i686.rpm",
    ".noarch",
    ".noarch.rpm",
    ".x86_64",
    ".x86_64.rpm",
]


@lru_cache(maxsize=None)
def rpmspec_present() -> bool:
    """Check if the 'rpmspec' tool is present in the environment."""
    return shutil.which("rpmspec") is not None


@lru_cache(maxsize=None)
def get_system_install_tool() -> str:
    """Return the name of the system install tool."""
    if shutil.which("dnf"):
        return "dnf"
    if shutil.which("yum"):
        return "yum"
    raise RuntimeError("No package installation tool found")


def parse_rpm_spec_file(spec_file: str, fallback_plain_rpm: bool) -> Optional[str]:
    """Use 'rpmspec -P' to handle macros in a spec file, and return the flat content."""

    # if spec_file path has $RPM_HOME / "rpmbuild" / "SPEC" / *.spec, then set home to $RPM_HOME
    path_split = Path(spec_file).parts
    if len(path_split) >= 3 and path_split[-3] == "rpmbuild" and path_split[-2] == "SPECS":
        home_env_dir = os.path.join(*path_split[:-3])
        log.debug("For running rpmspec, setting HOME to %s", home_env_dir)
        log.debug(
            "SOURCES content: %r", os.listdir(os.path.join(home_env_dir, "rpmbuild", "SOURCES"))
        )
    else:
        home_env_dir = os.environ.get("HOME")

    try:
        # run the rpmspec command and capture the output
        rpmspec_extra_args = ["-D", "%__python /usr/bin/python"]
        output = subprocess.check_output(
            ["rpmspec", "-P", spec_file] + rpmspec_extra_args,
            universal_newlines=True,
            stderr=subprocess.DEVNULL,
            env=get_env_with_home(home_env_dir),
        )
        return output

    except Exception as e:
        # handle any errors that occur when running the rpmspec command

        if fallback_plain_rpm:
            log.debug("Returning plain spec file content ...")
            with open(spec_file, "r", encoding="utf-8") as f:
                return f.read()

        log.error("Failed running rpmspec -P for %s with exception %r", spec_file, e)
        return None


def return_source_entries(lines: List[str]) -> Dict[str, str]:
    """Return all lines matching the Source entries of an RPM spec file."""
    pattern = r"^Source\d*\s*:"

    source_entries = {}
    for line in lines:
        if re.match(pattern, line):
            key, value = line.split(":", 1)
            real_value = value.strip()
            if real_value:
                source_entries[key.strip()] = real_value
    return source_entries


def get_package_basename(package_name):
    """Extract the base name of a package by removing known endings."""

    for ending in KNOWN_PACKAGE_ENDINGS:
        if package_name.endswith(ending):
            return package_name[: -len(ending)]

    # if no matching ending is found, return the original package name
    return package_name


def get_package_providing_latest(package_name: str):
    """Return package that provides the latest version of the asked package."""

    install_tool = get_system_install_tool()
    if install_tool != "dnf":
        # below logic in this func is dnf-specific; in case of e.g. yum, return None and let the
        # caller deal with this, see e.g. download_and_extract_source_package()
        return None

    packages = {}  # mapping from provider package to provided version

    # Execute the dnf command
    cmd = ["dnf", "provides", package_name]
    log.debug("Obtaining packages providing package %s with command %r", package_name, cmd)
    try:
        result = subprocess.check_output(
            cmd,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as e:
        log.warning("Detecting provider packages failed with %s", e.stderr)
        return None

    log.debug("Received %d lines of output for package provider query", len(result.splitlines()))

    # Parse the output with available packages
    current_package = None
    current_version = None

    """
    Output to be parsed from `dnf provides npm` command:
    Last metadata expiration check: 1 day, 12:52:22 ago on Mon Nov 25 19:48:43 2024.
    nodejs-npm-1:9.6.7-1.18.17.1.1.amzn2023.0.2.x86_64 : Node.js Package Manager
    Repo        : amazonlinux
    Matched from:
    Provide    : npm = 1:9.6.7-1.18.17.1.1

    ...

    npm-1:8.19.2-1.18.12.1.1.amzn2023.0.10.x86_64 : Node.js Package Manager
    Repo        : amazonlinux
    Matched from:
    Provide    : npm = 1:8.19.2-1.18.12.1.1.amzn2023.0.10
    """

    for line in result.splitlines():
        line = line.strip()
        if line.startswith("Last metadata expiration check:"):
            continue

        if not line:
            # next package block
            if current_package and current_version:
                packages[current_package] = current_version
            current_package = None
            current_version = None
        elif line.startswith("Provide") and "=" in line:
            current_version = line.split("=")[1].strip()
        elif " : " in line:
            # first line of a block is the providing package
            if not current_package:
                current_package = line.split()[0]

    # Add the last package if the output doesn't end with an empty line
    if current_package and current_version:
        packages[current_package] = current_version

    log.info("Detected %d packages providing %s", len(packages), package_name)
    log.debug("Packages providing %s: %r", package_name, packages)

    # Find the highest version
    highest_version = None
    highest_package = None
    for package, ver in packages.items():
        # Remove epoch (if present) for version comparison
        ver_without_epoch = re.sub(r"^\d+:", "", ver)
        if highest_version is None or versions_is_greater(ver_without_epoch, highest_version):
            highest_version = ver_without_epoch
            highest_package = package

    return highest_package


def download_and_extract_source_package(
    package_name: str,
    content_directory: str = "source_rpm_content",
    srpm_file: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Download the source RPM file for the given package and extract the source files in CWD.
    Returns a tuple with the location to the .src.rpm file and the directory with the package content
    """

    if srpm_file is None:
        try:

            provider_package = get_package_providing_latest(package_name)
            if provider_package is not None:
                log.info("Package providing '%s' is: %s", package_name, provider_package)
            else:
                log.warning(
                    "Could not find package providing '%s', falling back to the package name itself",
                    package_name,
                )
                provider_package = package_name

            # download the source RPM file
            download_cmd = ["yumdownloader", "--source", provider_package]
            log.debug(
                "Downloading source file for package %s via provider package %s with command %r",
                package_name,
                provider_package,
                download_cmd,
            )
            subprocess.run(
                download_cmd,
                stdout=DEVNULL,
                stderr=DEVNULL,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            log.warning("Failed to download source package for %s with %r", package_name, e)
            return None, None

        # extract the source files from the source RPM file
        src_rpm_files = glob.glob(os.path.join(os.getcwd(), "*.src.rpm"))
        if len(src_rpm_files) != 1:
            raise RuntimeError(
                f"Expected exactly one .src.rpm file, found {len(src_rpm_files)} for {package_name}"
            )
        src_rpm_file = src_rpm_files[0]
    else:
        log.debug("Use locally provided SRPM file %s", srpm_file)
        src_rpm_file = srpm_file

    os.mkdir(os.path.basename(content_directory))
    abs_content_directory = os.path.abspath(content_directory)

    try:
        with pushd(content_directory):
            log.debug("Extracting source package %s for package %s", src_rpm_file, package_name)
            p1 = subprocess.Popen(
                ["rpm2cpio", src_rpm_file],
                stdout=subprocess.PIPE,  # fed to p2
                stderr=subprocess.PIPE,  # used in `except subprocess.CalledProcessError` below
            )
            p2 = subprocess.Popen(
                ["cpio", "-idmv"],
                stdin=p1.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,  # used in `except subprocess.CalledProcessError` below
                text=True,
            )
            p2.communicate()
            log.debug(
                "Extracted %d source files from package %s",
                len(os.listdir(os.getcwd())),
                package_name,
            )
            if p2.returncode != 0:
                raise RuntimeError(f"Failed to extract src.rpm for package {package_name}")

        return src_rpm_file, abs_content_directory

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{e}\n{e.stderr}") from e


def get_env_with_home(new_home_var: str):
    """Generate an environment where HOME is modified to the given path."""
    home_env = os.environ.copy()
    home_env.update({"HOME": new_home_var})
    return home_env


def prepare_rpmbuild_source(
    src_rpm_file: str, package_rpmbuild_home: Optional[str] = None
) -> Tuple[str, str, str]:
    """
    Use an existing .src.rpm file, and prepare the source package for building.
    Returns a tuple with the HOME to be used for rpmbuild commands, the full path to the source, and
    the absolute path to the package's spec file.
    """

    if package_rpmbuild_home is None:
        package_rpmbuild_home = tempfile.mkdtemp(prefix="rpmbuild_home-")
    abs_package_rpmbuild_home = os.path.abspath(package_rpmbuild_home)
    os.makedirs(abs_package_rpmbuild_home, exist_ok=True)

    log.debug(
        "Preparing package source for %s with home dir %s", src_rpm_file, abs_package_rpmbuild_home
    )

    abs_spec_file_path = None
    abs_source_path = None
    with pushd(abs_package_rpmbuild_home):
        home_env = get_env_with_home(abs_package_rpmbuild_home)
        try:
            rpm_extract_cmd = ["rpm", "-ivh", src_rpm_file]
            log.debug("Running %r in CWD %s with env: %r", rpm_extract_cmd, os.getcwd(), home_env)
            subprocess.run(
                rpm_extract_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                env=home_env,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"{e}\n{e.stderr}") from e

        # Run RPM build preparation to apply patches in source and obtain a path to full source
        try:
            with pushd(os.path.join(abs_package_rpmbuild_home, "rpmbuild")):
                # Find the single *.spec file in the SPECS directory
                spec_file = get_single_spec_file("SPECS")
                abs_spec_file_path = os.path.abspath(spec_file)
                rpmbuild_prep_cmd = ["rpmbuild", "-bp", spec_file]
                log.debug(
                    "Running %r in CWD %s with env: %r", rpmbuild_prep_cmd, os.getcwd(), home_env
                )
                subprocess.run(
                    rpmbuild_prep_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                    env=home_env,
                    text=True,
                )
                abs_source_path = os.path.abspath("SOURCES")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"{e}\n{e.stderr}") from e

    return abs_package_rpmbuild_home, abs_source_path, abs_spec_file_path


def get_single_spec_file(content_directory):
    """Return the single spec file from the given directory."""
    spec_files = list(Path(content_directory).glob("*.spec"))

    if len(spec_files) == 1:
        return str(spec_files[0])
    elif len(spec_files) > 1:
        raise ValueError(f"Multiple spec files found in {content_directory}")
    else:
        raise ValueError(f"No spec file found in {content_directory}")


def all_system_packages():
    """Return list of all system packages available on the system, in NVR format."""

    # run the 'repoquery' command to list all installed packages, only get a single version if possible
    repo_query_packages = None
    for extra_parameters in [["--latest-limit", "1"], []]:
        repoquery_command = ["repoquery", "--nvr", "-a"] + extra_parameters
        try:
            log.debug(
                "Executing repoquery command to collect available packages: %r", repoquery_command
            )
            repoquery_output = subprocess.run(
                repoquery_command, capture_output=True, text=True, check=True
            )
        except Exception:
            log.debug(
                "Failed to obtain packages with command %r, trying next variant.", repoquery_command
            )
            continue
        # separate output to get package names only, and remove duplicates
        repo_query_packages = set(
            get_package_basename(x) for x in repoquery_output.stdout.strip().split("\n")
        )
        break

    if repo_query_packages is None:
        raise RuntimeError("Failed to detect packages via repoquery")

    log.info("Detected packages via repoquery: %d", len(repo_query_packages))

    rpm_qa_command = ["rpm", "-qa"]
    log.debug("Executing repoquery command to collect available packages: %r", rpm_qa_command)
    rpm_qa_output = subprocess.run(rpm_qa_command, capture_output=True, text=True, check=True)
    rpm_qa_packages = set(get_package_basename(x) for x in rpm_qa_output.stdout.strip().split("\n"))
    log.info("Detected packages via rpm -qa: %d", len(rpm_qa_packages))

    # return the union of all packages
    ret = list(repo_query_packages.union(rpm_qa_packages))
    log.debug("Detected %d total packages", len(ret))
    return ret


def install_build_dependencies(src_package_file: str):
    """Install the build dependencies of a package source file using the system's package manager."""

    log.info("Installing dependencies for package %s", src_package_file)
    install_tool = get_system_install_tool()

    cmd = ["yum-builddep"] if install_tool == "yum" else ["dnf", "builddep"]
    cmd += ["-y", src_package_file]

    # Run yum-builddep or dnf builddep to install package build dependencies
    try:
        log.debug("Running command %r", cmd)
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        log.error("Command %r failed", cmd)
        log.debug(
            "stderr:\n=== STDERR BEGIN ===\n%s\n=== STDERR  END  ===",
            e.stderr,
        )
        raise RuntimeError(f"Error executing command: {e}") from e
