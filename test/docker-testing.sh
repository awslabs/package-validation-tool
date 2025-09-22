#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Execute system level tests with the package-validation-tool in a docker environment
# The script will create a docker image, and will then execute the script
# test/system-level-testing.sh in a docker container based on that image.


declare -r SCRIPT=$(readlink -e "$0")
declare -r SCRIPT_DIR=$(dirname "$SCRIPT")
declare -r PROJECT_DIR=$(readlink -e "$SCRIPT_DIR/..")

# Store generated docker images
declare -a DOCKER_TEST_IMAGES=()
declare -a IMAGE_PREFIXES=("AL2023-" "AL2-")

LOG_FILE=$(mktemp -t docker-image-build-log-XXXXXX)
trap '[ -d "$LOG_FILE" ] && rm -f "$LOG_FILE"' EXIT

error_handler() {
    local _PROG="$0"
    local LINE="$1"
    local ERR="$2"
    if [ $ERR != 0 ]; then
        echo "$_PROG: error_handler() invoked, line $LINE, exit status $ERR" 1>&2
    fi
    exit "$ERR"
}

set -e
trap 'error_handler $LINENO $?' ERR

usage () {
    cat << EOF 1>&2
$(basename $0) ... run integration tests in a docker environment

Usage: $0 [-a prefix]
  -a prefix: Set the image prefix to use for testing
EOF
}

# Parse command line options
while getopts "a:h" opt; do
    case $opt in
    a)
        # Override default prefixes with single specified prefix
        IMAGE_PREFIXES=("$OPTARG")
        ;;
    h)
        usage
        exit 0
        ;;
    \?)
        echo "Invalid option: -$OPTARG" >&2
        usage
        exit 1
        ;;
    :)
        echo "Option -$OPTARG requires an argument." >&2
        usage
        exit 1
        ;;
  esac
done

cd "$PROJECT_DIR"

build_docker_test_images () {
    # Build docker image to be used to provide an environment for the tool

    local status=0
    for prefix in "${IMAGE_PREFIXES[@]}"
    do
        local image_name="package-validation-tool-env:testing-$USER-${prefix}image"
        local dockerfile=misc/"${prefix}Dockerfile"
        if [ ! -f "$dockerfile" ]; then
            echo "$dockerfile not found, please run from the root of the package-validation-tool repository" 1>&2
            return 1
        fi
        echo "Building docker image $image_name ..." 1>&2

        docker build --network host -t "$image_name" -f "$dockerfile" misc &> "$LOG_FILE" || status=$?
        if [ $status -ne 0 ]; then
            echo "Failed to build docker image $image_name" 1>&2
            echo "Docker build log:" 1>&2
            cat "$LOG_FILE" 1>&2
            return $status
        fi
        DOCKER_TEST_IMAGES+=("$image_name")
    done
    return 0
}

build_docker_test_images

TMP_WORKING_DIR=$(mktemp -d)
trap '[ -d "$TMP_WORKING_DIR" ] && rm -rf "$TMP_WORKING_DIR"' EXIT

# Execute tests in docker from the new working directory
cd "$TMP_WORKING_DIR"
echo "Executing docker-based testing in directory $TMP_WORKING_DIR with images ${DOCKER_TEST_IMAGES[*]}..." 1>&2

# Execute all tests for all images, use a clean directory for each image
for image in "${DOCKER_TEST_IMAGES[@]}"
do
    image_dir=$(echo "$image" | tr -d ':')
    mkdir -p "$image_dir"
    pushd "$image_dir" > /dev/null
    echo " === Executing docker-based testing for image $image ..." 1>&2

    cp -r "$PROJECT_DIR"/* .
    docker run --rm -t -v $PWD:$PWD -w $PWD -eHOME=$PWD \
            --network=host \
            "$image" test/system-level-testing.sh
    popd > /dev/null
    echo -e " === done [$image]\n\n\n" 1>&2
done

echo "Successfully executed docker-based testing" 1>&2
