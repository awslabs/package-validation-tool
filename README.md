# Package-Validation-Tool

Package-Validation-Tool is a CLI tool to validate the origins of OS distro
packages. It compares local archives in the package against their remote
upstream sources and repositories, ensuring that locally packaged software
matches their declared upstream sources. This is an important step for supply
chain security and package provenance.

For example, the tool can check the contents of your local `zlib` package, find
the archive `zlib-1.2.11.tar.xz` and perform the following validations for
this archive:
1. Detect the upstream archive: https://www.zlib.net/fossils/zlib-1.2.11.tar.gz,
2. Match all files in the local archive against the upstream archive,
3. Detect the upstream git repo: https://github.com/madler/zlib,
4. Match all files in the local archive against the upstream repo.

If there are mismatches of certain files, the tool reports them. Several
heuristics are used to detect the upstream sources and to file-match them.

One important heuristic for file-matching (mostly for C projects) is
regeneration of Autotools-related files like `configure`, `Makefile.in`, etc.
Typically upstream source repositories do not check in Autotools-generated
files, whereas archives typically have them. To match these files also, the tool
tries to generate them in the source repository, so that these auto-generated
files are then picked up by the file-matching step. Autotools can fail to
generate these files -- this is not considered fatal, and file-matching step is
still executed.

## Requirements

- Python 3.7+
- Docker (we recommend to run the tool in a constrained environment)

## Quickstart

Run the following commands from this project root directory:
```sh
# using GITHUB_TOKEN is highly recommended for GitHub access, see comments below
export GITHUB_TOKEN="your_personal_access_token_here"

export DOCKERFILE=misc/AL2023-Dockerfile
export IMAGENAME=package-validation-tool-env-al2023

docker build --network host -t ${IMAGENAME}:alpha -f $DOCKERFILE misc

docker run -it -v $PWD:$PWD -w $PWD -eHOME=$PWD \
        --network=host --tmpfs /tmp \
        ${IMAGENAME}:alpha /bin/bash
```


Now inside the Docker container, install Package-Validation-Tool:
```sh
make install
```

Now you can execute the tool:
```sh
# 1. Obtain package from local repos and unpack it to a specified directory
package-validation-tool store-package -p zlib -o zlib/

# the unpacked package contents look like this:
#
# zlib/
# |-- SOURCE
# |   |-- CVE-2023-45853.patch
# |   |-- ...
# |   |-- zlib-1.2.11.tar.xz
# |-- SPECS
# |   `-- zlib.spec
# `-- SRPM_CONTENT
#     |-- CVE-2023-45853.patch
# |   |-- ...
#     |-- zlib-1.2.11.tar.xz
#     `-- zlib.spec

# 2. Match files in local archive against detected upstream archives
package-validation-tool match-package-archives -p zlib -o zlib-match-archives.json

# zlib-match-archives.json looks like this (remote archive was found):
#
# {
#   "matching": true,
#   "results": {
#     "zlib-1.2.11.tar.xz": {
#       "remote_archive": "https://www.zlib.net/fossils/zlib-1.2.11.tar.gz",
#       "matched": true,
#       "files_total": 253,
#       "conflicts": {}
#     }
#   }
# }


# 3. Match files in local archive against detected upstream repos
package-validation-tool match-package-repos -p zlib -o zlib-match-repos.json

# zlib-match-repos.json looks like this (upstream repo was found):
#
# {
#   "matching": true,
#   "results": {
#     "zlib-1.2.11.tar.xz": [
#       {
#         "remote_repo": "https://github.com/madler/zlib",
#         "commit_hash": "7085a61bce3ed39d5e56ca4d01d80f4338c8a4a6",
#         "tag": "v1.2.11",
#         "matched": true,
#         "files_total": 253,
#         "conflicts": {}
#       }
#   }
# }

# 4. Run full validation on all packages on the system
package-validation-tool validate-system-packages -o all-system-packages.json
```

**Notes on Docker**

The tool uses /tmp dir extensively. For performance reasons, we recommend to
mount `/tmp` as a tmpfs (in-memory-only) directory in your Docker container.

To test the tool with other OS distros, export these environment variables:
```sh
# test with Amazon Linux 2 (AL2)
export DOCKERFILE=misc/AL2-Dockerfile
export IMAGENAME=package-validation-tool-env-al2

# test with Fedora 40 (oldest maintained release as of Feb 2025)
export DOCKERFILE=misc/Fedora40-Dockerfile
export IMAGENAME=package-validation-tool-env-fedora40
```

If you put files in the path below from where you started the container, these
files will stay on the disk outside of the container as well. The owner of
these files is root (as you started the container without a user). This is
useful for later debugging, but don't forget about their root permissions.

**Notes on performance**

The tool queries the GitHub API when searching for code repositories. It is
recommended to set a GitHub personal access token when using the tool:

```sh
export GITHUB_TOKEN="your_personal_access_token_here"
```

This increases the GitHub API rate limit from 60 requests/hour (anonymous) to
5,000 requests/hour (authenticated). Without this token, you may experience
signifcant performance issues if validating multiple packages at once.

See https://docs.github.com/en/rest/overview/authenticating-to-the-rest-api for
instructions on how to set up and use a GitHub token.

## Limitations

- Currently only RPM packages and package managers (yum, dnf) are supported.
  - The tool was tested on Fedora and Amazon Linux,
  - but should work with any RPM-based OS distro.

- The versions of Autotools that are recognized by the tool are hard-coded (more
  specifically, their SHA256 checksums are hard-coded).
  - Done for security reasons: we do not want to download and execute unknown
    versions of Autotools.
  - This hard-coding implies that the tool may fail the Autotools "generate
    build files" step if the package under test uses a too-new version of
    Autotools. In this case, please check if a newer version of the tool is
    available or contact us.
  - For advanced users: you can add new versions of Autotools in the
    `TOOL_CONFIGS` variable in matching/autotools.py. If you do, please submit a
    pull request with this change.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This project is licensed under the Apache-2.0 License.

