"""One run, one fingerprint — regardless of which path computed it.

``expand_scenarios`` labels the unmodified base config by injecting
``metadata.scenario_id`` (``BASELINE`` when a ``scenarios:`` block exists,
otherwise ``metadata.scenario_id`` or ``BASE``). That label is *bookkeeping*:
it names the run, it does not change the physics. Hashing it meant the very
same solve got two different fingerprints depending on whether it was reached
through the run-set expansion or straight from the preloaded config — so a
result cached by one path could never be recognised by the other, and the
Scenario pane could report a scenario "computed" that a sweep would
immediately re-solve.

These tests pin the invariant: the run-set's view of the base config and the
plain preloaded config hash identically.
"""

from __future__ import annotations

from typing import Any, Dict

from boulder.config import normalize_config
from boulder.result_cache import compute_fingerprint
from boulder.runset import BASELINE_SCENARIO_ID, expand_scenarios

_BASE: Dict[str, Any] = {
    "metadata": {"title": "identity test"},
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "network": [
        {
            "id": "feed",
            "Reservoir": {
                "temperature": "300 K",
                "pressure": "101325 Pa",
                "composition": "CH4:1",
            },
        },
    ],
}


def _with_scenarios() -> Dict[str, Any]:
    import copy

    cfg = copy.deepcopy(_BASE)
    cfg["scenarios"] = {"hot": {"metadata": {"description": "a variant"}}}
    return cfg


def _fingerprint(raw: Dict[str, Any]) -> str:
    """Fingerprint *raw* the way every caller does: normalize, then hash."""
    import copy

    return compute_fingerprint(
        normalize_config(copy.deepcopy(raw)), mechanism="gri30.yaml"
    )


def test_baseline_and_preloaded_config_share_one_fingerprint() -> None:
    """The regression: the run-set's BASELINE == the plain preloaded config.

    Both describe the identical unmodified base run. Before the fix these
    differed only because ``expand_scenarios`` had stamped
    ``metadata.scenario_id: BASELINE`` onto the config being hashed.
    """
    raw = _with_scenarios()
    runs = expand_scenarios(raw)
    baseline_id, baseline_cfg = runs[0]
    assert baseline_id == BASELINE_SCENARIO_ID

    # The plain preloaded config: same file, no run-set expansion, and
    # therefore no injected scenario id.
    preloaded = {k: v for k, v in raw.items() if k != "scenarios"}

    assert _fingerprint(baseline_cfg) == _fingerprint(preloaded)


def test_scenario_id_alone_never_changes_the_fingerprint() -> None:
    """Renaming a run must not invalidate its cached result."""
    import copy

    a = copy.deepcopy(_BASE)
    a.setdefault("metadata", {})["scenario_id"] = "called_one_thing"
    b = copy.deepcopy(_BASE)
    b.setdefault("metadata", {})["scenario_id"] = "called_another"

    assert _fingerprint(a) == _fingerprint(b)
    # ...and the same as carrying no id at all.
    assert _fingerprint(a) == _fingerprint(_BASE)


def test_stone_version_alone_never_changes_the_fingerprint() -> None:
    """A result cached before the format stamp existed must still be found.

    ``normalize_config`` stamps ``metadata.stone_version`` on every load, so
    the stamp is varied *after* normalization here, the way a cache entry
    written by an older Boulder (no stamp, or an older value) would differ.
    """
    import copy

    normalized = normalize_config(copy.deepcopy(_BASE))
    assert "stone_version" in normalized["metadata"]

    unstamped = copy.deepcopy(normalized)
    del unstamped["metadata"]["stone_version"]
    older = copy.deepcopy(normalized)
    older["metadata"]["stone_version"] = "1.9"

    fp = compute_fingerprint(normalized, mechanism="gri30.yaml")
    assert compute_fingerprint(unstamped, mechanism="gri30.yaml") == fp
    assert compute_fingerprint(older, mechanism="gri30.yaml") == fp


def test_a_real_parameter_change_still_changes_the_fingerprint() -> None:
    """Guard against over-stripping: physics must still invalidate."""
    import copy

    hotter = copy.deepcopy(_BASE)
    hotter["network"][0]["Reservoir"]["temperature"] = "400 K"

    assert _fingerprint(hotter) != _fingerprint(_BASE)


def test_validated_and_merely_normalised_configs_agree() -> None:
    """The other half of the mismatch: Pydantic's explicit nulls.

    ``BoulderRunner.validate`` stamps every unset optional with an explicit
    ``None`` (``export``/``signals``/``bindings`` at top level, and
    ``metadata``/``network_class`` on every node); the run-set path only
    normalises, so it simply omits them. Same run, different dicts — the
    fingerprint must not care.
    """
    import copy

    normalised = normalize_config(copy.deepcopy(_BASE))
    validated = copy.deepcopy(normalised)
    validated["export"] = None
    validated["signals"] = None
    validated["bindings"] = None
    for node in validated["nodes"]:
        node["metadata"] = None
        node["network_class"] = None

    assert compute_fingerprint(
        validated, mechanism="gri30.yaml"
    ) == compute_fingerprint(normalised, mechanism="gri30.yaml")


def test_a_real_none_to_value_change_still_counts() -> None:
    """Dropping nulls must not hide a null → real-value edit."""
    import copy

    without = normalize_config(copy.deepcopy(_BASE))
    with_value = copy.deepcopy(without)
    with_value["nodes"][0]["metadata"] = {"note": "something real"}

    assert compute_fingerprint(
        with_value, mechanism="gri30.yaml"
    ) != compute_fingerprint(without, mechanism="gri30.yaml")


def test_other_metadata_still_participates() -> None:
    """Only the injected run *label* is excluded, not metadata generally.

    ``description``/``title`` come from the user's YAML rather than from
    Boulder's own run-set bookkeeping, so they are left in the hash — dropping
    them would be a separate, larger decision about what "the same run" means.
    """
    import copy

    retitled = copy.deepcopy(_BASE)
    retitled["metadata"]["title"] = "a different title"

    assert _fingerprint(retitled) != _fingerprint(_BASE)
