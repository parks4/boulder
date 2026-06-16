"""On-disk cache of the last simulation result.

Boulder stores the GUI results payload (times, reactor series, reports,
Sankey, summary, updated nodes/connections) to a fingerprinted directory
next to the loaded YAML file.  On startup, if the preloaded config
fingerprint matches a cache entry, Boulder loads it and sends it to the
frontend immediately so outputs are visible without re-running.

Host packages (e.g. Bloc) register :class:`CacheContributorPlugin`
implementations.  After each successful GUI solve, Boulder calls every
registered contributor so they can write package-specific artifacts
(e.g. a calc-note bundle JSON + figure PNGs) into the same cache entry.
The contributor receives the solved ``converter`` so it can access
live network objects.

Cache layout
------------
::

    <yaml_dir>/.boulder-cache/         (or $BOULDER_CACHE_DIR)
        <fingerprint>/
            result.json                GUI payload + config snapshot
            meta.json                  created_at, versions, fingerprint inputs
            COMPLETE                   marker written last (atomic write guard)
            artifacts/                 contributor-written files

Fingerprint
-----------
SHA-256 hex of canonical sorted-key JSON of:

* normalized config (nodes, connections, settings, phases)
* mechanism identity (content hash for local files; name+cantera-version for builtins)
* package versions: boulder, cantera
* ``BOULDER_PLUGINS`` env var
* ``CACHE_VERSION`` integer

:data:`CACHE_VERSION` must be bumped whenever the ``result.json``
or ``meta.json`` schema changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Bump when result.json / meta.json schema changes to auto-invalidate old entries.
CACHE_VERSION: int = 1

#: Keep at most this many cache entries per cache directory (oldest pruned first).
MAX_CACHE_ENTRIES: int = 5


# ---------------------------------------------------------------------------
# JSON coercion helpers
# ---------------------------------------------------------------------------


def _coerce(obj: Any) -> Any:
    """Recursively coerce *obj* to JSON-native types.

    Handles numpy scalars/arrays, Path objects, tuples, and datetime objects.

    Integer-valued floats (e.g. ``0.0``, ``1.0``) are normalised to ``int``
    so that a value that starts as ``0.0`` in a Pydantic-validated config
    produces the same fingerprint as ``0`` after a JavaScript JSON round-trip
    (``JSON.stringify`` drops the ``.0`` for whole-number floats).
    """
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, float):
        # Normalise integer-valued floats (0.0 → 0, 1.0 → 1) to produce
        # stable fingerprints across Python↔JavaScript JSON round-trips.
        if obj.is_integer():
            return int(obj)
        return obj
    if isinstance(obj, int):
        return obj
    # numpy scalar
    if hasattr(obj, "item"):
        return obj.item()
    # numpy array or other array-like with tolist()
    if hasattr(obj, "tolist"):
        return _coerce(obj.tolist())
    if isinstance(obj, Path):
        return str(obj)
    # datetime/date objects (e.g. from YAML date fields like 2026-03-26)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _coerce(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_coerce(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------


def _mechanism_identity(mechanism: Optional[str]) -> str:
    """Return a stable string identifying the mechanism for hashing.

    For a local file path: sha256 of the file content.
    For a built-in Cantera mechanism name (no path separator, ends with .yaml
    or .cti, or is a known format): ``"builtin:<name>@cantera-<version>"``.
    Falls back to the bare name if unresolvable.
    """
    if not mechanism:
        return "builtin:gri30.yaml"

    p = Path(mechanism)
    if p.is_file():
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        return f"file:{p.name}@{digest}"

    # Not a local file — treat as built-in
    try:
        import cantera as ct  # type: ignore

        ct_version = getattr(ct, "__version__", "unknown")
    except ImportError:
        ct_version = "unknown"
    return f"builtin:{mechanism}@cantera-{ct_version}"


def _package_version(package: str) -> str:
    """Return the base (major.minor.patch) version of *package*, or 'unknown'.

    Development-install suffixes (``.dev*``, ``+local``, ``.dirty``) are
    stripped so that cache entries survive code edits within the same release
    series.  :data:`CACHE_VERSION` is the authoritative discriminator for
    schema-breaking changes; a version bump (e.g. 0.5.4 → 0.5.5) still
    produces a different fingerprint and invalidates old entries.
    """
    try:
        import re
        from importlib.metadata import version

        raw = version(package)
        m = re.match(r"^(\d+\.\d+\.\d+)", raw)
        return m.group(1) if m else raw
    except Exception:
        return "unknown"


def compute_fingerprint(
    config: Dict[str, Any],
    mechanism: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Compute a cache fingerprint (sha256 hex) for *config*.

    Parameters
    ----------
    config:
        Fully normalised simulation config dict (nodes/connections/settings/phases).
    mechanism:
        Mechanism string from the POST body or resolved from config.
    extra:
        Additional key/value pairs included verbatim in the hash (e.g.
        ``{"simulation_time": 10.0, "time_step": 1.0}``).

    Returns
    -------
    str
        64-character hex digest.
    """
    key: Dict[str, Any] = {
        "cache_version": CACHE_VERSION,
        "config": _coerce(config),
        "mechanism": _mechanism_identity(mechanism),
        "boulder_version": _package_version("boulder"),
        "cantera_version": _package_version("cantera"),
        "boulder_plugins": os.environ.get("BOULDER_PLUGINS", ""),
    }
    if extra:
        key["extra"] = _coerce(extra)

    canonical = json.dumps(key, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Cache directory resolution
# ---------------------------------------------------------------------------


def cache_dir_for(config_path: Optional[str]) -> Optional[Path]:
    """Return the cache directory for *config_path*.

    Respects ``$BOULDER_CACHE_DIR`` override.  Returns ``None`` when neither
    the override nor a valid config path is available.
    """
    override = os.environ.get("BOULDER_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    if config_path:
        return Path(config_path).parent / ".boulder-cache"
    return None


def _entry_dir(cache_root: Path, fingerprint: str) -> Path:
    return cache_root / fingerprint


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------


def save_result(
    cache_root: Path,
    fingerprint: str,
    gui_payload: Dict[str, Any],
    config_snapshot: Dict[str, Any],
    mechanism: Optional[str] = None,
    meta_extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """Atomically persist the GUI payload and config snapshot to disk.

    Creates ``<cache_root>/<fingerprint>/result.json``,
    ``meta.json``, and the ``COMPLETE`` marker.  Prunes old entries to keep
    at most :data:`MAX_CACHE_ENTRIES`.

    Parameters
    ----------
    cache_root:
        Root cache directory (``<yaml_dir>/.boulder-cache`` or override).
    fingerprint:
        Hex digest from :func:`compute_fingerprint`.
    gui_payload:
        The complete GUI results dict (times, reactor_reports, etc.).
    config_snapshot:
        Post-solve config dict (post stream-point enrichment).
    mechanism:
        Mechanism string for meta logging.
    meta_extra:
        Additional fields written into ``meta.json`` (e.g. contributor names).

    Returns
    -------
    Path
        The cache entry directory.
    """
    cache_root.mkdir(parents=True, exist_ok=True)
    entry = _entry_dir(cache_root, fingerprint)
    artifacts_dir = entry / "artifacts"

    # Use a temp dir inside the cache root for atomic replacement
    tmp_dir = Path(tempfile.mkdtemp(dir=cache_root, prefix="_tmp_"))
    try:
        (tmp_dir / "artifacts").mkdir()

        result_data = {
            "gui_payload": _coerce(gui_payload),
            "config_snapshot": _coerce(config_snapshot),
        }
        _write_json(tmp_dir / "result.json", result_data)

        meta: Dict[str, Any] = {
            "fingerprint": fingerprint,
            "cache_version": CACHE_VERSION,
            "created_at": time.time(),
            "boulder_version": _package_version("boulder"),
            "cantera_version": _package_version("cantera"),
            "mechanism": mechanism or "",
        }
        if meta_extra:
            meta.update(_coerce(meta_extra))
        _write_json(tmp_dir / "meta.json", meta)

        # Not yet COMPLETE — move into place first
        if entry.exists():
            shutil.rmtree(entry)
        shutil.move(str(tmp_dir), str(entry))
        artifacts_dir = entry / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)

    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Write COMPLETE marker atomically
    _write_complete_marker(entry)

    _prune_cache(cache_root)
    logger.info("Cache entry written: %s/%s", cache_root.name, fingerprint[:12])
    return entry


def _write_json(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically via temp file + rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _write_complete_marker(entry: Path) -> None:
    """Write the COMPLETE marker atomically."""
    marker = entry / "COMPLETE"
    tmp = entry / "COMPLETE.tmp"
    tmp.write_text(str(time.time()), encoding="utf-8")
    tmp.replace(marker)


def load_result(
    cache_root: Path,
    fingerprint: str,
) -> Optional[Dict[str, Any]]:
    """Load a cached result entry.

    Returns ``None`` when the entry does not exist, is incomplete
    (missing COMPLETE marker), or cannot be parsed.

    Returns
    -------
    dict or None
        Keys: ``"gui_payload"``, ``"config_snapshot"``, ``"meta"``,
        ``"artifacts_dir"`` (Path), ``"fingerprint"`` (str).
    """
    entry = _entry_dir(cache_root, fingerprint)
    if not (entry / "COMPLETE").exists():
        return None
    try:
        result_data = json.loads((entry / "result.json").read_text(encoding="utf-8"))
        meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
        if meta.get("cache_version") != CACHE_VERSION:
            logger.debug("Cache entry version mismatch, ignoring: %s", fingerprint[:12])
            return None
        return {
            "fingerprint": fingerprint,
            "gui_payload": result_data.get("gui_payload", {}),
            "config_snapshot": result_data.get("config_snapshot", {}),
            "meta": meta,
            "artifacts_dir": entry / "artifacts",
        }
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        logger.debug("Failed to load cache entry %s: %s", fingerprint[:12], exc)
        return None


def artifacts_dir_for(cache_root: Path, fingerprint: str) -> Optional[Path]:
    """Return the artifacts directory for a valid cache entry, or None."""
    entry = _entry_dir(cache_root, fingerprint)
    if not (entry / "COMPLETE").exists():
        return None
    return entry / "artifacts"


# ---------------------------------------------------------------------------
# Alias support (pre-build ↔ post-build fingerprint mapping)
# ---------------------------------------------------------------------------


def _alias_path(cache_root: Path, alias_fp: str) -> Path:
    """Return the path for an alias file mapping *alias_fp* to a canonical entry."""
    return cache_root / f"_alias_{alias_fp}"


def save_alias(cache_root: Path, alias_fp: str, canonical_fp: str) -> None:
    """Write an alias file mapping *alias_fp* → *canonical_fp*.

    Used to map post-build fingerprints to the pre-build (canonical) cache
    entry so that :func:`load_result_flexible` finds hits regardless of
    whether the caller provides a pre-build or post-build fingerprint.
    """
    cache_root.mkdir(parents=True, exist_ok=True)
    alias_file = _alias_path(cache_root, alias_fp)
    tmp = alias_file.with_suffix(".tmp")
    tmp.write_text(canonical_fp, encoding="utf-8")
    tmp.replace(alias_file)
    logger.debug("Cache alias written: %s → %s", alias_fp[:12], canonical_fp[:12])


def load_result_flexible(cache_root: Path, fingerprint: str) -> Optional[Dict[str, Any]]:
    """Load a cached result, following alias files when needed.

    Tries the direct entry first; if absent, checks for a
    ``_alias_<fingerprint>`` file written when a post-build fingerprint
    was aliased to the canonical (pre-build) cache entry.

    Returns
    -------
    dict or None
        Same structure as :func:`load_result`.
    """
    result = load_result(cache_root, fingerprint)
    if result is not None:
        return result
    alias_file = _alias_path(cache_root, fingerprint)
    if alias_file.is_file():
        try:
            canonical_fp = alias_file.read_text(encoding="utf-8").strip()
            return load_result(cache_root, canonical_fp)
        except OSError:
            return None
    return None


def find_result_by_config_snapshot(
    cache_root: Path,
    fingerprint: str,
    mechanism: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Scan cache entries for one whose ``config_snapshot`` fingerprint matches.

    This bridges the gap when the startup fingerprint (from the pre-build
    validated config) differs from the key under which the entry was stored
    (worker's pre-build fingerprint), but the POST-build ``config_snapshot``
    happens to match the startup fingerprint.  This occurs because of minor
    type differences (e.g. ``0.0`` float vs ``0`` int after JSON round-trips)
    that the ``_coerce`` normaliser now eliminates, so new entries will hash
    consistently.  The scan is only needed for entries written by older code.

    Parameters
    ----------
    cache_root:
        Root cache directory.
    fingerprint:
        The fingerprint to search for in stored ``config_snapshot`` fields.
    mechanism:
        Mechanism string used when computing the snapshot fingerprint.

    Returns
    -------
    dict or None
        Same structure as :func:`load_result`, or ``None`` if not found.
    """
    if not cache_root.exists():
        return None
    for entry_dir in cache_root.iterdir():
        if not entry_dir.is_dir() or entry_dir.name.startswith("_"):
            continue
        if not (entry_dir / "COMPLETE").exists():
            continue
        try:
            result_data = json.loads(
                (entry_dir / "result.json").read_text(encoding="utf-8")
            )
            meta = json.loads(
                (entry_dir / "meta.json").read_text(encoding="utf-8")
            )
            if meta.get("cache_version") != CACHE_VERSION:
                continue
            snapshot = result_data.get("config_snapshot") or {}
            if not snapshot:
                continue
            snapshot_fp = compute_fingerprint(snapshot, mechanism=mechanism)
            if snapshot_fp == fingerprint:
                return {
                    "fingerprint": entry_dir.name,
                    "gui_payload": result_data.get("gui_payload", {}),
                    "config_snapshot": snapshot,
                    "meta": meta,
                    "artifacts_dir": entry_dir / "artifacts",
                }
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return None


def clear_cache(cache_root: Path) -> None:
    """Remove all cache entries under *cache_root*."""
    if cache_root.exists():
        shutil.rmtree(cache_root)
    logger.info("Cache cleared: %s", cache_root)


def _prune_cache(cache_root: Path) -> None:
    """Remove oldest cache entries when count exceeds :data:`MAX_CACHE_ENTRIES`."""
    entries = [
        d
        for d in cache_root.iterdir()
        if d.is_dir() and not d.name.startswith("_tmp_") and (d / "COMPLETE").exists()
    ]
    if len(entries) <= MAX_CACHE_ENTRIES:
        return
    entries.sort(key=lambda d: (d / "COMPLETE").stat().st_mtime)
    for old in entries[: len(entries) - MAX_CACHE_ENTRIES]:
        shutil.rmtree(old, ignore_errors=True)
        logger.debug("Pruned cache entry: %s", old.name[:12])


# ---------------------------------------------------------------------------
# CacheContributorPlugin — plugin hook for host packages
# ---------------------------------------------------------------------------


class CacheContributorPlugin(ABC):
    """Plugin that writes package-specific artifacts into a Boulder cache entry.

    Implement this in a host package to persist additional derived data
    (e.g. calculation-note bundles, figure PNGs) alongside Boulder's GUI
    payload.  Boulder calls :meth:`contribute` after a successful solve.

    Parameters to :meth:`contribute`
    ----------------------------------
    config:
        Post-solve, fully normalised config dict (post stream-point enrichment).
    converter:
        The solved :class:`~boulder.cantera_converter.DualCanteraConverter`
        instance (gives access to live network objects for stream points, etc.).
    simulation_result:
        :class:`~boulder.simulation_result.SimulationResult` built from the
        converter after the solve.
    fingerprint:
        Hex digest identifying this cache entry.
    artifacts_dir:
        Directory where the contributor should write its files.  It exists
        and is writable before :meth:`contribute` is called.
    """

    @property
    @abstractmethod
    def contributor_id(self) -> str:
        """Unique identifier for this contributor."""

    @abstractmethod
    def contribute(
        self,
        config: Dict[str, Any],
        converter: Any,
        simulation_result: Any,
        fingerprint: str,
        artifacts_dir: Path,
    ) -> None:
        """Write artifacts into *artifacts_dir*.

        Must not raise: failures are logged but must not abort the live solve.
        Prefer explicit ``except SomeError`` over broad ``except Exception``
        inside implementations.
        """


@dataclass
class CacheContributorRegistry:
    """Registry for cache contributor plugins."""

    contributors: List[CacheContributorPlugin] = field(default_factory=list)

    def register(self, plugin: CacheContributorPlugin) -> None:
        """Register *plugin*, silently skipping duplicate IDs."""
        existing = {c.contributor_id for c in self.contributors}
        if plugin.contributor_id in existing:
            return
        self.contributors.append(plugin)


_cache_contributor_registry = CacheContributorRegistry()


def get_cache_contributor_registry() -> CacheContributorRegistry:
    """Return the global cache contributor registry."""
    return _cache_contributor_registry


def register_cache_contributor(plugin: CacheContributorPlugin) -> None:
    """Register a :class:`CacheContributorPlugin` with the global registry."""
    _cache_contributor_registry.register(plugin)


def run_contributors(
    contributors: List[CacheContributorPlugin],
    config: Dict[str, Any],
    converter: Any,
    simulation_result: Any,
    fingerprint: str,
    artifacts_dir: Path,
) -> None:
    """Call each contributor, logging but not re-raising on failure."""
    for contributor in contributors:
        try:
            contributor.contribute(
                config, converter, simulation_result, fingerprint, artifacts_dir
            )
            logger.debug(
                "Cache contributor %s completed for %s",
                contributor.contributor_id,
                fingerprint[:12],
            )
        except OSError as exc:
            logger.warning(
                "Cache contributor %s failed (OSError): %s",
                contributor.contributor_id,
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Cache contributor %s failed: %s",
                contributor.contributor_id,
                exc,
            )
