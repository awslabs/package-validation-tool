#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Execute system level tests with the package-validation-tool
#
# WARNING: this script will install the local package-validation-tool with pip
# Run this in a container or similar environment, to not pollute your local
# development/runtime environment.

declare -r SCRIPT=$(readlink -e "$0")
declare -r SCRIPT_DIR=$(dirname "$SCRIPT")
declare -r PROJECT_DIR=$(readlink -e "$SCRIPT_DIR/..")

run_with_output_only_on_failure() (
    local -i status=0

    local log_file
    log_file=$(mktemp -t package-validation-tool-run-stdout-XXXXXX)
    trap '[ -d "$log_file" ] && rm -f "$log_file"' EXIT

    "$@" &> "$log_file" || status=$?
    if [ $status -ne 0 ]; then
        echo "ERROR: Command '$*' failed with status $status" 1>&2
        echo "Command output:" 1>&2
        cat "$log_file" 1>&2
        exit $status
    fi
)

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

# Create directory to work in, and jump there
TMP_WORKING_DIR=$(mktemp -d)
trap '[ -d "$TMP_WORKING_DIR" ] && rm -rf "$TMP_WORKING_DIR"' EXIT
cd "$TMP_WORKING_DIR"


# Copy package-validation-tool source, and install it
recompile_package () (
    local -i status=0
    cp -r "$PROJECT_DIR"/* .
    rm -rf build
    echo "Building package ..." 1>&2
    run_with_output_only_on_failure python3 setup.py install || status="$?"

    # Use exit, as this function is called in a subshell
    exit "$status"
)

test_package_storing () (
    # Test storing package content for two packages

    local log_file
    log_file=$(mktemp -t test-package-storing-log-XXXXXX)
    trap '[ -d "$log_file" ] && rm -f "$log_file"' EXIT

    local -i total_status=0
    for package in lz4 zlib-devel
    do
        rm -rf content-$package-dir
        echo "Test storing package $package ..."
        local output_dir="content-$package-dir"
        local -i status=0
        package-validation-tool -l DEBUG store-package -p "$package" -o "$output_dir" &> "$log_file" || status=$?
        ls "$output_dir"/SPECS/*.spec > /dev/null || status=1
        ls "$output_dir"/SRPM_CONTENT/*tar*  > /dev/null || status=1
        if [ "$status" -ne 0 ]; then
            echo "FAILED: storing package $package" 1>&2
            echo "Execution log:" 1>&2
            cat "$log_file" 1>&2
            total_status="$status"
        fi
    done
    return $total_status
)

test_package_suggesting_archives () (
    # Test suggesting remote archives for the package

    local log_file
    log_file=$(mktemp -t test-package-suggesting-log-XXXXXX)
    trap '[ -d "$log_file" ] && rm -f "$log_file"' EXIT

    local -i total_status=0
    for package in zlib openssh
    do
        local output_file="content-$package.json"
        rm -rf "$output_file"
        echo "Test suggesting remote archives for package $package ..."
        local -i status=0
        package-validation-tool -l DEBUG suggest-package-archives \
            -p "$package" -o "$output_file" --transform-archives &> "$log_file" || status=$?
        # below greps are brittle because they depend on how Python json module formats the output
        # but since it's just a manual test, we currently don't care about a more robust solution
        grep "\"suggested_by\": \"suggest_" "$output_file" > /dev/null || status=1
        grep "\"unused_spec_sources\": \[\]" "$output_file" > /dev/null || status=1
        if [ "$status" -ne 0 ]; then
            echo "FAILED: suggesting remote archives for package $package" 1>&2
            echo "Execution log:" 1>&2
            cat "$log_file" 1>&2
            total_status="$status"
        fi
    done
    return $total_status
)

test_package_suggesting_archives_cache_same_package () (
    # Test suggesting remote archives twice for the same package:
    #   - first invocation caches the suggestion results (should be rather slow)
    #   - second invocation reuses the cached results (should be very fast)

    local log_file
    log_file=$(mktemp -t test-package-suggesting-cache-same-package-log-XXXXXX)
    trap '[ -d "$log_file" ] && rm -f "$log_file"' EXIT

    local cache_dir
    cache_dir=$(mktemp -d test-package-suggesting-cache-same-package-cache-XXXXXX)
    trap '[ -d "$cache_dir" ] && rm -rf "$cache_dir"' EXIT

    local -i total_status=0
    local package="openssh"
    local -a elapsed=()
    local -i count=0
    echo "Test suggesting remote archives with caching for package $package ..."
    for iteration in 1 2
    do
        local output_file="content-$package.json"
        rm -rf "$output_file"
        local -i status=0

        start_time=$(date +%s)
        package-validation-tool -C "$cache_dir" -l DEBUG suggest-package-archives \
            -p "$package" -o "$output_file" --transform-archives &> "$log_file" || status=$?
        end_time=$(date +%s)

        # below greps are brittle because they depend on how Python json module formats the output
        # but since it's just a manual test, we currently don't care about a more robust solution
        grep "\"suggested_by\": \"suggest_" "$output_file" > /dev/null || status=1
        grep "\"unused_spec_sources\": \[\]" "$output_file" > /dev/null || status=1
        if [ "$status" -ne 0 ]; then
            echo "FAILED: suggesting remote archives for package $package" 1>&2
            echo "Execution log:" 1>&2
            cat "$log_file" 1>&2
            total_status="$status"
        fi

        elapsed[count]=$((end_time - start_time))
        echo "  iteration $iteration took ${elapsed[count]} seconds"
        ((count++))
    done

    if ((elapsed[0] < elapsed[1])); then
        echo "FAILED: operation with caching was slower than without caching" 1>&2
        echo "Execution log:" 1>&2
        cat "$log_file" 1>&2
        return 1
    fi
    return $total_status
)

test_package_suggesting_archives_cache_same_source () (
    # Test suggesting remote archives for two RPM packages that resolve to the same SRPM package:
    #   - first invocation (openssh-clients) caches the suggestion results (should be rather slow)
    #   - second invocation (openssh) reuses the cached results (should be pretty fast)

    local log_file
    log_file=$(mktemp -t test-package-suggesting-cache-same-source-log-XXXXXX)
    trap '[ -d "$log_file" ] && rm -f "$log_file"' EXIT

    local cache_dir
    cache_dir=$(mktemp -d test-package-suggesting-cache-same-source-cache-XXXXXX)
    trap '[ -d "$cache_dir" ] && rm -rf "$cache_dir"' EXIT

    local -i total_status=0
    local -a elapsed=()
    local -i count=0
    echo "Test suggesting remote archives with source-package caching ..."
    for package in openssh-clients openssh
    do
        local output_file="content-$package.json"
        rm -rf "$output_file"
        local -i status=0

        start_time=$(date +%s)
        package-validation-tool -C "$cache_dir" -l DEBUG suggest-package-archives \
            -p "$package" -o "$output_file" --transform-archives &> "$log_file" || status=$?
        end_time=$(date +%s)

        # below greps are brittle because they depend on how Python json module formats the output
        # but since it's just a manual test, we currently don't care about a more robust solution
        grep "\"suggested_by\": \"suggest_" "$output_file" > /dev/null || status=1
        grep "\"unused_spec_sources\": \[\]" "$output_file" > /dev/null || status=1
        if [ "$status" -ne 0 ]; then
            echo "FAILED: suggesting remote archives for package $package" 1>&2
            echo "Execution log:" 1>&2
            cat "$log_file" 1>&2
            total_status="$status"
        fi

        elapsed[count]=$((end_time - start_time))
        echo "  package $package took ${elapsed[count]} seconds"
        ((count++))
    done

    if ((elapsed[0] < elapsed[1])); then
        echo "FAILED: operation with caching was slower than without caching" 1>&2
        echo "Execution log:" 1>&2
        cat "$log_file" 1>&2
        return 1
    fi
    return $total_status
)

test_package_suggesting_repos () (
    # Test suggesting remote (git) repositories for the package

    local log_file
    log_file=$(mktemp -t test-package-suggesting-repos-log-XXXXXX)
    trap '[ -d "$log_file" ] && rm -f "$log_file"' EXIT

    local -i total_status=0
    for package in zlib openssh
    do
        local output_file="content-$package.json"
        rm -rf "$output_file"
        echo "Test suggesting remote repos for package $package ..."
        local -i status=0
        package-validation-tool -l DEBUG suggest-package-repos \
            -p "$package" -o "$output_file" &> "$log_file" || status=$?
        # below greps are brittle because they depend on how Python json module formats the output
        # but since it's just a manual test, we currently don't care about a more robust solution
        if [ "$package" = "zlib" ]; then
            grep "\"repo\": \"https://github.com/madler/zlib\"" "$output_file" > /dev/null || status=1
        elif [ "$package" = "openssh" ]; then
            grep "\"repo\": \"https://github.com/openssh/openssh-portable\"" "$output_file" > /dev/null || status=1
        fi
        if [ "$status" -ne 0 ]; then
            echo "FAILED: suggesting remote repos for package $package" 1>&2
            echo "Execution log:" 1>&2
            cat "$log_file" 1>&2
            total_status="$status"
        fi
    done
    return $total_status
)

test_package_matching_archives () (
    # Test matching local archives in the package against remote archives

    local log_file
    log_file=$(mktemp -t test-package-matching-archives-log-XXXXXX)
    trap '[ -d "$log_file" ] && rm -f "$log_file"' EXIT

    local -i total_status=0
    for package in zlib openssh
    do
        local output_file="matched-archives-$package.json"
        rm -rf "$output_file"
        echo "Test matching remote archives for package $package ..."
        local -i status=0
        package-validation-tool -l DEBUG match-package-archives \
            -p "$package" -o "$output_file" &> "$log_file" || status=$?
        # below greps are brittle because they depend on how Python json module formats the output
        # but since it's just a manual test, we currently don't care about a more robust solution
        grep "\"matching\": true" "$output_file" > /dev/null || status=1
        grep "\"unused_spec_sources\": \[\]" "$output_file" > /dev/null || status=1
        if [ "$status" -ne 0 ]; then
            echo "FAILED: matching remote archives for package $package" 1>&2
            echo "Execution log:" 1>&2
            cat "$log_file" 1>&2
            total_status="$status"
        fi
    done
    return $total_status
)

test_package_matching_repos () (
    # Test matching local archives in the package against remote (git) repositories

    local log_file
    log_file=$(mktemp -t test-package-matching-repos-log-XXXXXX)
    trap '[ -d "$log_file" ] && rm -f "$log_file"' EXIT

    local -i total_status=0
    for package in zlib openssh
    do
        local suggested_repos_file="suggested-repos-$package.json"
        rm -rf "$suggested_repos_file"
        local -i status=0
        run_with_output_only_on_failure package-validation-tool -l DEBUG suggest-package-repos \
            -p "$package" -o "$suggested_repos_file" || status="$?"
        if [ "$status" -ne 0 ]; then
            echo "FAILED PREPARATION: suggesting remote repos for package $package" 1>&2
            total_status="$status"
            continue
        fi

        local output_file="matching-repos-$package.json"
        rm -rf "$output_file"
        echo "Test matching remote repos for package $package ..."

        # NOTE: currently there are unexplained files in OpenSSH with trivial file matching, so we
        #       expect status "1" in OpenSSH case (also run_with_output_only_on_failure will print
        #       the log because of this expected failure, don't be surprised)
        local -i expected_status=0
        run_with_output_only_on_failure package-validation-tool -l DEBUG match-package-repos \
            -p "$package" -i "$suggested_repos_file" -o "$output_file" --no-apply-autotools || status=$?

        # below greps are brittle because they depend on how Python json module formats the output
        # but since it's just a manual test, we currently don't care about a more robust solution
        if [ "$package" = "zlib" ]; then
            grep "\"remote_repo\": \"https://github.com/madler/zlib\"" "$output_file" > /dev/null || status=1
        elif [ "$package" = "openssh" ]; then
            grep "\"remote_repo\": \"https://github.com/openssh/openssh-portable\"" "$output_file" > /dev/null || status=1
            expected_status=1
        fi
        if [ "$status" -ne "$expected_status" ]; then
            echo "FAILED: matching remote repos for package $package" 1>&2
            total_status="$status"
        fi
    done
    return $total_status
)

test_repology_website_structure() {
    local url="https://repology.org/project/zlib/information"
    local temp_file=$(mktemp)
    trap '[ -f "$temp_file" ] && rm -f "$temp_file"' EXIT

    # Download the page: Repology requires TLS v1.2, which is NOT available on Amazon Linux 2, so
    # the download may fail (we ignore this issue because this should succeed on newer Amazon Linux)
    if ! curl -A "Wget/1.14 (linux-gnu)" -s -f "$url" -o "$temp_file"; then
        echo "WARNING: Failed to fetch Repology page: $url, skipping this test ..."
        return 0
    fi

    echo "Test Repology website structure for example URL $url ..."

    # Check if Repository_links section exists
    if ! grep -q 'id="Repository_links"' "$temp_file"; then
        echo "ERROR: Repository_links section not found on Repology page"
        return 1
    fi

    # Extract content after Repository_links section until next section or end
    # Look for the <ul> list within this section
    local section_content=$(sed -n '/id="Repository_links"/,/<section id/p' "$temp_file" | head -n -1)

    # Check if there's a <ul> element in the Repository_links section
    if ! echo "$section_content" | grep -q '<ul'; then
        echo "ERROR: No <ul> list found in Repository_links section"
        return 1
    fi

    # Check if there's at least one <li> element with <a href> link
    if ! echo "$section_content" | grep -q '<li.*<a href'; then
        echo "ERROR: No <li> elements with <a href> links found in Repository_links section"
        return 1
    fi

    return 0
}

# Build package-validation-tool
if ! recompile_package; then
    echo "error: failed to compile package, aborting" 1>&2
    exit 1
fi

# Execute all required tests
STATUS=0
test_package_storing || STATUS=$?
test_package_suggesting_archives || STATUS=$?
test_package_suggesting_archives_cache_same_package || STATUS=$?
test_package_suggesting_archives_cache_same_source || STATUS=$?
test_package_suggesting_repos || STATUS=$?
test_package_matching_archives || STATUS=$?
test_package_matching_repos || STATUS=$?
test_repology_website_structure || STATUS=$?

echo "Executed system-level testing with status $STATUS" 1>&2
exit "$STATUS"
