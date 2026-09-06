"""STONE format version: ``STONE_FORMAT_VERSION`` and ``metadata.stone_version``.

The migration behaviour itself (legacy keys, GUI round-trip) is covered in
``tests/test_legacy_metadata_keys.py``; this module pins the invariant that
the metadata vocabulary constants match the pydantic model. ``STONE_FORMAT_VERSION``
is versioned independently of the Boulder package version.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict

import pytest

from boulder.config import (
    STONE_FORMAT_VERSION,
    migrate_stone_config,
    normalize_config,
    validate_config,
)
from boulder.validation import METADATA_ALLOWED_KEYS, MetadataModel

_CLEAN: Dict[str, Any] = {
    "metadata": {"description": "clean"},
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "network": [
        {
            "id": "feed",
            "Reservoir": {
                "temperature": "300 K",
                "pressure": "1 atm",
                "composition": "CH4:1",
            },
        }
    ],
}


def test_metadata_vocabulary_matches_model() -> None:
    """The exported frozensets and ``MetadataModel`` are two sources of truth."""
    assert set(MetadataModel.model_fields) == set(METADATA_ALLOWED_KEYS)


def test_unversioned_file_is_stamped_silently(caplog) -> None:
    cfg = copy.deepcopy(_CLEAN)
    with caplog.at_level(logging.WARNING, logger="boulder.config"):
        assert migrate_stone_config(cfg) == []
    assert cfg["metadata"]["stone_version"] == STONE_FORMAT_VERSION
    assert not caplog.records

    # No metadata block at all: one is created.
    bare = {k: v for k, v in _CLEAN.items() if k != "metadata"}
    assert migrate_stone_config(bare) == []
    assert bare["metadata"] == {"stone_version": STONE_FORMAT_VERSION}

    # End to end: normalize stamps, validation accepts the stamp.
    normalized = normalize_config(copy.deepcopy(_CLEAN))
    assert (
        validate_config(normalized)["metadata"]["stone_version"] == STONE_FORMAT_VERSION
    )


def test_current_version_is_a_no_op() -> None:
    cfg = copy.deepcopy(_CLEAN)
    cfg["metadata"]["stone_version"] = STONE_FORMAT_VERSION
    assert migrate_stone_config(cfg) == []


@pytest.mark.parametrize(
    ("found", "fragment"),
    [
        ("2.99", "newer than this Boulder"),
        ("3.0", "reads STONE 2.x"),
        ("1.0", "reads STONE 2.x"),
        ("abc", "not MAJOR.MINOR"),
    ],
)
def test_foreign_versions_warn_but_load(found: str, fragment: str) -> None:
    cfg = copy.deepcopy(_CLEAN)
    cfg["metadata"]["stone_version"] = found
    notices = migrate_stone_config(cfg)
    assert len(notices) == 1 and fragment in notices[0]
    assert cfg["metadata"]["stone_version"] == STONE_FORMAT_VERSION
    validate_config(normalize_config(cfg))


def test_unquoted_float_version_is_tolerated() -> None:
    """``stone_version: 2.0`` (no quotes) loads as a YAML float."""
    cfg = copy.deepcopy(_CLEAN)
    cfg["metadata"]["stone_version"] = 2.0
    assert migrate_stone_config(cfg) == []
    assert cfg["metadata"]["stone_version"] == STONE_FORMAT_VERSION
