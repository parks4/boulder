"""The result store: one HDF5 file per run-set entry.

Every solve lands here — a whole sweep or a single run — because
:func:`boulder.runset.expand_scenarios` always yields at least one entry, so
"single-shot" and "sweep" are the same thing at N=1 and N=3. There is no second,
content-addressed store: the **name** is the key, and the ``fingerprint`` attr
recorded under that name is the staleness check.

    <store_dir>/
        BASELINE.h5 | <scenario_id>.h5
        artifacts/<scenario_id>/...

Consequence worth stating plainly: an entry holds **one** result, the latest.
Re-running an unchanged entry is a cache hit; going *back* to a previous value
re-solves. Keeping a value around is what authoring a scenario is for.

Two invariants this module exists to enforce
--------------------------------------------
**Never serve another config's results.** A name-addressed store has no
intrinsic protection against two same-named configs sharing a directory (which
``$BOULDER_CACHE_DIR`` makes possible — see
:func:`boulder.runset.resolve_store_dir`). Every file therefore records the
config it belongs to, and :func:`read_entry` / :func:`list_entries` refuse a
file whose stamp does not match, so a collision degrades to a rebuild instead of
a wrong answer.

**Never serve a half-written result.** ``fingerprint`` is the validity signal,
so it is written *last*, after the payload. A solve that dies midway leaves a
file with no fingerprint — read as "not computed", which is what it is. Writing
it earlier would let every later run cache-hit onto a broken payload: strictly
worse than a miss.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .runset import store_artifacts_dir, store_entry_path

logger = logging.getLogger(__name__)

try:  # pragma: no cover — h5py is a hard dependency in practice
    import h5py
except ImportError:  # pragma: no cover
    h5py = None  # type: ignore[assignment]

#: Bump when the per-entry attr/dataset layout changes, so older files are
#: rebuilt rather than misread. Distinct from ``payload_store.PAYLOAD_SCHEMA``
#: (the payload's own format) and from ``result_cache.CACHE_VERSION`` (which
#: feeds the fingerprint).
STORE_VERSION: int = 1

#: Root attrs this module owns. Kept out of the KPI/display attr namespace the
#: Scenario pane and Sweep Results plot read (``label``, ``order``,
#: ``computed_at``, ``in.<id>.<prop>``, host KPIs).
_ATTR_VERSION = "store_version"
_ATTR_CONFIG_IDENTITY = "config_identity"
_ATTR_FINGERPRINT = "fingerprint"

#: Additional fingerprints the same entry also answers to.
#:
#: One solve can be described by more than one config: the staged solver enriches
#: the network while building it (stream-point and interface nodes), so the
#: config the *frontend* holds afterwards hashes differently from the pre-build
#: config the run-set and the startup check use. :attr:`_ATTR_FINGERPRINT` stays
#: the canonical pre-build one — what a sweep compares against — and the
#: post-build variant is recorded here so a subsequent "is this still current?"
#: from the browser matches too. Replaces the old separate alias entries (and
#: their orphan pruning): the alternates live on the entry they belong to.
_ATTR_ALT_FINGERPRINTS = "alt_fingerprints"

#: Attrs that are bookkeeping rather than plottable KPIs. Anything *not* listed
#: here and numeric becomes a selectable axis in the Sweep Results plot, so an
#: omission shows up as a nonsense axis. Covers this module's own attrs, the
#: display attrs, and the four :mod:`boulder.payload_store` writes
#: (``schema_version`` + the three ``mechanism*`` keys). Mirrored by
#: ``NON_AXIS_KEYS`` in ``frontend/src/components/panels/SweepResultsPlot.tsx``.
NON_KPI_ATTRS = frozenset(
    {
        _ATTR_VERSION,
        _ATTR_CONFIG_IDENTITY,
        _ATTR_FINGERPRINT,
        _ATTR_ALT_FINGERPRINTS,
        "label",
        "order",
        "computed_at",
        "units",
        "schema_version",
        "mechanism",
        "mechanism_name",
        "mechanism_sha256",
    }
)


def config_identity(config_path: "Optional[str | Path]") -> str:
    """Return the stamp identifying which config a store entry belongs to.

    The config's resolved absolute path. Deliberately *not* the fingerprint:
    this answers "whose entry is this?", which must stay stable as the config's
    contents (and so its fingerprint) change.
    """
    return str(Path(config_path).resolve()) if config_path else ""


def _to_py(value: Any) -> Any:
    """Coerce an h5py attr to a plain Python scalar."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return value
    return value


def _usable(handle: Any, identity: str) -> bool:
    """Whether this file is a complete entry belonging to *identity*."""
    attrs = handle.attrs
    if _ATTR_FINGERPRINT not in attrs:
        return False  # interrupted write — see the module docstring
    if int(_to_py(attrs.get(_ATTR_VERSION, 0)) or 0) != STORE_VERSION:
        return False
    if identity:
        stamped = str(_to_py(attrs.get(_ATTR_CONFIG_IDENTITY, "")) or "")
        if stamped and stamped != identity:
            return False
    return True


def write_entry(
    store_dir: Path,
    scenario_id: str,
    *,
    gui_payload: Dict[str, Any],
    mechanism: str,
    fingerprint: str,
    identity: str,
    label: Optional[str] = None,
    order: Optional[int] = None,
    alt_fingerprints: "Optional[tuple[str, ...]]" = None,
    units: Optional[Dict[str, str]] = None,
    extra_attrs: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write one solved entry, recording ``fingerprint`` last.

    Returns the file written. The payload goes through the same
    :func:`boulder.payload_store.write_payload` every result uses, so there is
    one serialisation format regardless of which action produced the result.
    """
    from .payload_store import write_payload  # noqa: PLC0415 — heavy import

    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_entry_path(store_dir, scenario_id)

    # Payload first: until `fingerprint` lands this file reads as "not
    # computed", so an interruption here cannot be mistaken for a valid result.
    write_payload(path, gui_payload, mechanism)

    with h5py.File(str(path), "a") as handle:
        attrs = handle.attrs
        attrs[_ATTR_VERSION] = STORE_VERSION
        attrs[_ATTR_CONFIG_IDENTITY] = identity
        attrs["computed_at"] = float(time.time())
        if label is not None:
            attrs["label"] = label
        if order is not None:
            attrs["order"] = int(order)
        alts = tuple(fp for fp in (alt_fingerprints or ()) if fp and fp != fingerprint)
        if alts:
            attrs[_ATTR_ALT_FINGERPRINTS] = list(alts)
        if units:
            attrs["units"] = json.dumps(units)
        for key, value in (extra_attrs or {}).items():
            attrs[key] = value
        handle.flush()
        # Last, and only now: this entry is complete and valid.
        attrs[_ATTR_FINGERPRINT] = fingerprint
    return path


def update_display_attrs(
    store_dir: Path,
    scenario_id: str,
    *,
    label: Optional[str] = None,
    order: Optional[int] = None,
) -> bool:
    """Refresh an entry's *display* attrs without touching its result.

    A sweep that skips an unchanged entry still wants the Scenario pane to track
    the YAML — a reordered run-set, or a renamed ``scenario_name``. Deliberately
    cannot touch the fingerprint or the payload: this is presentation only.
    Returns whether the entry existed.
    """
    if h5py is None:
        return False
    path = store_entry_path(store_dir, scenario_id)
    if not path.is_file():
        return False
    try:
        with h5py.File(str(path), "a") as handle:
            if label is not None:
                handle.attrs["label"] = label
            if order is not None:
                handle.attrs["order"] = int(order)
        return True
    except OSError:
        return False


def entry_attrs(
    store_dir: Path, scenario_id: str, identity: str = ""
) -> Optional[Dict[str, Any]]:
    """Return one entry's attrs, or ``None`` if absent/unusable.

    Attrs only — no payload — so listing a run-set stays cheap. Tolerates a
    concurrent write (``OSError`` from a locked or half-written file) by
    reporting "not available yet" rather than raising: a reader must never turn
    an in-flight solve into a 500.
    """
    if h5py is None:
        return None
    path = store_entry_path(store_dir, scenario_id)
    if not path.is_file():
        return None
    try:
        with h5py.File(str(path), "r") as handle:
            if not _usable(handle, identity):
                return None
            return {str(k): _to_py(v) for k, v in handle.attrs.items()}
    except (OSError, KeyError):
        return None


def list_entries(store_dir: Optional[Path], identity: str = "") -> List[Dict[str, Any]]:
    """Return every usable entry's attrs, ordered by ``order`` then id.

    Entries belonging to another config, written by another ``STORE_VERSION``,
    or left incomplete are skipped — never surfaced as results.
    """
    if h5py is None or store_dir is None or not store_dir.is_dir():
        return []
    entries: List[Dict[str, Any]] = []
    for path in sorted(store_dir.glob("*.h5")):
        try:
            with h5py.File(str(path), "r") as handle:
                if not _usable(handle, identity):
                    continue
                attrs = {str(k): _to_py(v) for k, v in handle.attrs.items()}
        except (OSError, KeyError):
            continue
        attrs.setdefault("id", path.stem)
        entries.append(attrs)
    entries.sort(key=lambda e: (e.get("order", 1 << 30), str(e.get("id", ""))))
    return entries


def read_entry(
    store_dir: Path, scenario_id: str, identity: str = ""
) -> Optional[Dict[str, Any]]:
    """Return one entry's GUI payload, or ``None`` if absent/unusable."""
    if h5py is None:
        return None
    path = store_entry_path(store_dir, scenario_id)
    if not path.is_file():
        return None
    try:
        with h5py.File(str(path), "r") as handle:
            if not _usable(handle, identity):
                return None
    except (OSError, KeyError):
        return None
    from .payload_store import read_payload  # noqa: PLC0415 — heavy import

    try:
        return read_payload(path)
    except (OSError, KeyError, ValueError):
        return None


def fingerprints(store_dir: Optional[Path], identity: str = "") -> Dict[str, str]:
    """Return ``{scenario_id: fingerprint}`` for every usable entry.

    The staleness check: an entry whose recorded fingerprint equals the one the
    current config produces needs no re-solve.
    """
    found: Dict[str, str] = {}
    for attrs in list_entries(store_dir, identity):
        fp = attrs.get(_ATTR_FINGERPRINT)
        sid = attrs.get("id")
        if fp and sid:
            found[str(sid)] = str(fp)
    return found


def _answers_to(attrs: Dict[str, Any], candidate_fingerprint: str) -> bool:
    """Whether an entry's attrs match *candidate_fingerprint*, canonical or alternate."""
    if str(attrs.get(_ATTR_FINGERPRINT, "")) == candidate_fingerprint:
        return True
    alts = attrs.get(_ATTR_ALT_FINGERPRINTS) or []
    if isinstance(alts, (str, bytes)):
        alts = [alts]
    return candidate_fingerprint in {str(_to_py(a)) for a in alts}


def find_entry(
    store_dir: Optional[Path], fingerprint: str, identity: str = ""
) -> Optional[Dict[str, Any]]:
    """Return the attrs of whichever entry already holds *fingerprint*.

    The one place the store is searched rather than addressed by name, and only
    because two callers legitimately have a config but no id: the startup check
    (which config was preloaded?) and ``check-cache`` (does this live-edited
    config match anything?). Both then reuse that entry instead of re-solving.

    Attrs only, so a "do we have this?" question costs no payload read. A
    run-set is bounded by its config -- a handful of entries -- so the linear
    scan is cheaper than an index that would need invalidating.
    """
    if not fingerprint:
        return None
    for attrs in list_entries(store_dir, identity):
        if _answers_to(attrs, fingerprint):
            return attrs
    return None


def load_matching(
    store_dir: Optional[Path], fingerprint: str, identity: str = ""
) -> Optional[Dict[str, Any]]:
    """:func:`find_entry` plus the payload, in the shape the cache routes serve.

    ``meta`` and ``artifacts_dir`` reproduce what the retired content-addressed
    store returned, so ``GET /api/simulations/cached`` and its artifacts sibling
    keep their response shape while the frontend still expects it.
    """
    if store_dir is None:
        return None
    attrs = find_entry(store_dir, fingerprint, identity)
    if attrs is None:
        return None
    scenario_id = str(attrs.get("id") or "")
    payload = read_entry(store_dir, scenario_id, identity)
    if payload is None:
        return None
    return {
        "id": scenario_id,
        "fingerprint": str(attrs.get(_ATTR_FINGERPRINT, "")),
        "gui_payload": payload,
        "artifacts_dir": str(store_artifacts_dir(store_dir, scenario_id)),
        "meta": {"created_at": float(attrs.get("computed_at", 0.0) or 0.0)},
    }


def collect_units(store_dir: Optional[Path], identity: str = "") -> Dict[str, str]:
    """Merge every entry's KPI display units into one ``{attr: unit}`` map.

    A unit belongs to the *KPI* — an efficiency is a percentage whichever entry
    reported it — not to the entry, so the per-entry maps are merged. With one
    file per entry there is nowhere config-wide to put this, and duplicating a
    handful of short strings is cheaper than a separate index file.
    """
    merged: Dict[str, str] = {}
    for attrs in list_entries(store_dir, identity):
        raw = attrs.get("units")
        if not raw:
            continue
        try:
            merged.update(json.loads(str(raw)))
        except (ValueError, TypeError):
            continue
    return merged


def delete_entry(store_dir: Path, scenario_id: str) -> bool:
    """Remove one entry's file *and* its artifacts. Returns whether it existed."""
    path = store_entry_path(store_dir, scenario_id)
    existed = path.is_file()
    path.unlink(missing_ok=True)
    shutil.rmtree(store_artifacts_dir(store_dir, scenario_id), ignore_errors=True)
    return existed


def prune_entries(store_dir: Optional[Path], keep_ids: "set[str]") -> List[str]:
    """Delete entries whose scenario id has left the run-set.

    Returns the ids removed. Without this a renamed or deleted scenario would
    linger in the Scenario pane forever.
    """
    if store_dir is None or not store_dir.is_dir():
        return []
    from .runset import store_entry_name  # noqa: PLC0415 — local, cheap

    keep_names = {store_entry_name(sid) for sid in keep_ids}
    removed: List[str] = []
    for path in sorted(store_dir.glob("*.h5")):
        if path.stem in keep_names:
            continue
        path.unlink(missing_ok=True)
        shutil.rmtree(store_dir / "artifacts" / path.stem, ignore_errors=True)
        removed.append(path.stem)
    return removed


def clear(store_dir: Optional[Path]) -> bool:
    """Remove the whole store directory (entries *and* artifacts).

    Returns whether there was anything to remove.
    """
    if store_dir is None or not store_dir.is_dir():
        return False
    shutil.rmtree(store_dir, ignore_errors=True)
    return True
