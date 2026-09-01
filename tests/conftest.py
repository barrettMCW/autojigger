# SPDX-FileCopyrightText: 2024-present barrettMCW <mjbarrett@mcw.edu>
#
# SPDX-License-Identifier: MIT
"""Shared pytest fixtures and configuration."""

import pytest

@pytest.fixture
def tmp_yaml_file(tmp_path):
    """Create a temporary YAML file for testing."""
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text("key: value\nnested:\n  foo: bar\n")
    return yaml_file
