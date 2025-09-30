# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os

from package_validation_tool.package.suggesting_archives.transformation_methods import (
    _transform_remove_url_fragment_from_spec_sources,
)


def test_transform_remove_url_fragment_from_spec_sources():

    local_archives = [
        "/some/tmp/dir/archive-0.1.tar.gz",
        "/some/other/tmp/dir/archive-0.2.tar.bz",
    ]
    spec_sources = [
        "http://example.com/download/archive-0.1.tar.gz#this-must-be-removed",
        "https://example.com/fossils/archive/tags/0.2.tar.bz#/archive-0.2.tar.bz",
    ]

    transformation_result = _transform_remove_url_fragment_from_spec_sources(
        local_archives, spec_sources
    )

    # local archives are not modified at all (except for keeping only basename)
    assert len(transformation_result.input_local_archives) == 2
    assert transformation_result.input_local_archives[0] == os.path.basename(local_archives[0])
    assert transformation_result.input_local_archives[1] == os.path.basename(local_archives[1])

    assert len(transformation_result.output_local_archives) == 2
    assert transformation_result.output_local_archives[0] == os.path.basename(local_archives[0])
    assert transformation_result.output_local_archives[1] == os.path.basename(local_archives[1])

    # spec sources get rid of the URL fragments (everything after `#`)
    assert len(transformation_result.input_spec_sources) == 2
    assert transformation_result.input_spec_sources[0] == spec_sources[0]
    assert transformation_result.input_spec_sources[1] == spec_sources[1]

    assert len(transformation_result.output_spec_sources) == 2
    assert transformation_result.output_spec_sources[0] == spec_sources[0].split("#")[0]
    assert transformation_result.output_spec_sources[1] == spec_sources[1].split("#")[0]
