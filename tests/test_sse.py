"""Tests for boulder.api.sse.

Asserts:
- sanitize_for_json replaces NaN/Infinity/-Infinity floats with None, recursively
  through dicts and lists, leaving everything else untouched.
- The resulting structure survives a real json.dumps round-trip (regression for
  a bug where a NaN anywhere in a simulation's reactors_series/reactor_reports
  made json.dumps emit the bare, non-standard token `NaN` — invalid per the
  JSON spec, so a strict consumer like JavaScript's JSON.parse throws on it.
  The frontend's SSE "complete" handler wrapped that parse in a bare try/catch,
  so the failure was completely silent: the run had finished on the backend,
  but the UI stayed in "Running..." forever with no results and no error shown).
"""

from __future__ import annotations

import json
import math

from boulder.api.sse import sanitize_for_json


def test_replaces_nan_with_none():
    assert sanitize_for_json(float("nan")) is None


def test_replaces_infinity_with_none():
    assert sanitize_for_json(float("inf")) is None
    assert sanitize_for_json(float("-inf")) is None


def test_leaves_finite_floats_and_other_types_untouched():
    assert sanitize_for_json(1.5) == 1.5
    assert sanitize_for_json(0.0) == 0.0
    assert sanitize_for_json("k") == "k"
    assert sanitize_for_json(None) is None
    assert sanitize_for_json(True) is True


def test_recurses_through_nested_dicts_and_lists():
    data = {
        "times": [0.0, 1e-11, 2e-11],
        "reactors_series": {
            "plasma": {
                "radius": [5e-4, 5e-4, 5e-4],
                "k": [float("nan")] * 3,
            },
        },
        "nested": [{"a": float("inf")}, {"a": 1.0}],
    }
    result = sanitize_for_json(data)
    assert result["reactors_series"]["plasma"]["k"] == [None, None, None]
    assert result["reactors_series"]["plasma"]["radius"] == [5e-4, 5e-4, 5e-4]
    assert result["nested"][0]["a"] is None
    assert result["nested"][1]["a"] == 1.0
    # Original is untouched (progress.reactors_series is live/actively-appended-to).
    assert math.isnan(data["reactors_series"]["plasma"]["k"][0])


def test_sanitized_payload_survives_strict_json_round_trip():
    """The actual regression: json.dumps must not emit a bare NaN/Infinity token."""
    data = {"k": [float("nan"), float("inf"), float("-inf"), 1.23]}
    payload = json.dumps(sanitize_for_json(data))
    assert "NaN" not in payload
    assert "Infinity" not in payload
    # A strict JSON parser (any real one) would reject this if NaN/Infinity had
    # leaked through; re-parsing it here is itself part of the regression check.
    reparsed = json.loads(payload)
    assert reparsed["k"] == [None, None, None, 1.23]
