"""On-disk cache of the last simulation result.

Boulder stores the GUI results payload (times, reactor series, reports,
Sankey, summary, updated nodes/connections) to a fingerprinted directory
next to the loaded YAML file.  On startup, if the preloaded config
fingerprint matches a cache entry, Boulder loads it and sends it to the
frontend immediately so outputs are visible without re-running.

Host packages register :class:`CacheContributorPlugin`
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
            result.h5                  GUI payload (composite HDF5, see payload_store)
            meta.json                  created_at, versions, mechanism, config_snapshot
            COMPLETE                   marker written last (atomic write guard)
            artifacts/                 contributor-written files

Fingerprint
-----------
SHA-256 hex of canonical sorted-key JSON of:

* normalized config (nodes, connections, settings, phases)
* mechanism identity (content hash for local files; name+cantera-version for builtins)
* package source identity (git HEAD + dirty token for editable installs)
* cantera version
* per-plugin source identity from ``BOULDER_PLUGINS``
* ``BOULDER_PLUGINS`` env var
* ``CACHE_VERSION`` integer

:data:`CACHE_VERSION` must be bumped whenever the ``result.h5``
or ``meta.json`` schema changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Bump when the payload (result.h5) / meta.json schema changes to auto-invalidate
#: old entries. v2: payload moved from result.json → composite result.h5
#: (native SolutionArray + JSON blob); see :mod:`boulder.payload_store`.
CACHE_VERSION: int = 2

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
    """Return the base (major.minor.patch) version of *package*, or 'unknown'."""
    try:
        import re
        from importlib.metadata import version

        raw = version(package)
        m = re.match(r"^(\d+\.\d+\.\d+)", raw)
        return m.group(1) if m else raw
    except Exception:
        return "unknown"


def _ignore_code_changes() -> bool:
    """Return True when ``BOULDER_CACHE_IGNORE_CODE`` disables git-based identity."""
    return os.environ.get("BOULDER_CACHE_IGNORE_CODE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _find_git_root(start: Path) -> Optional[Path]:
    """Walk parents of *start* looking for a ``.git`` directory."""
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _git_head(repo_dir: Path) -> Optional[str]:
    """Return ``git rev-parse HEAD`` for *repo_dir*, or None."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _git_dirty_token(repo_dir: Path) -> Optional[str]:
    """Return a short hash when the work tree has uncommitted or untracked changes."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        combined = (status.stdout or "") + (diff.stdout or "")
        if not combined.strip():
            return None
        return hashlib.sha256(combined.encode()).hexdigest()[:12]
    except (OSError, subprocess.SubprocessError):
        return None


def _package_install_dir(package: str) -> Optional[Path]:
    """Return the on-disk directory for *package*, when discoverable."""
    try:
        import importlib
        from importlib.metadata import distribution

        dist = distribution(package)
        for entry in dist.files or []:
            if entry.name == "__init__.py":
                loc = entry.locate()
                if loc is not None:
                    loc_path = Path(loc)
                    if loc_path.is_file():
                        return loc_path.parent
        mod = importlib.import_module(package)
        mod_file = getattr(mod, "__file__", None)
        if mod_file:
            return Path(mod_file).parent
    except Exception:
        pass
    return None


def _source_identity(package: str) -> str:
    """Return a stable identity string for *package* source code.

    When the install lives inside a git work tree, uses ``HEAD`` plus a dirty
    token derived from ``git diff`` and ``git status``.  Falls back to the
    stripped package version for wheel installs or when git is unavailable.

    Set ``BOULDER_CACHE_IGNORE_CODE=1`` to restore version-only identity.
    """
    if _ignore_code_changes():
        return _package_version(package)

    install_dir = _package_install_dir(package)
    if install_dir is None:
        return _package_version(package)

    git_root = _find_git_root(install_dir)
    if git_root is None:
        return _package_version(package)

    head = _git_head(git_root)
    if head is None:
        return _package_version(package)

    dirty = _git_dirty_token(git_root)
    if dirty:
        return f"git:{head[:12]}+dirty:{dirty}"
    return f"git:{head[:12]}"


def _plugins_source_identity() -> Dict[str, str]:
    """Return source-identity strings for each top-level ``BOULDER_PLUGINS`` package."""
    plugins_env = os.environ.get("BOULDER_PLUGINS", "").strip()
    if not plugins_env:
        return {}

    identities: Dict[str, str] = {}
    for entry in plugins_env.split(","):
        module_name = entry.strip()
        if not module_name:
            continue
        root_pkg = module_name.split(".")[0]
        if root_pkg in identities:
            continue
        try:
            import importlib

            mod = importlib.import_module(module_name)
            pkg_name = (mod.__package__ or module_name).split(".")[0]
            identities[pkg_name] = _source_identity(pkg_name)
        except ImportError:
            identities[root_pkg] = _source_identity(root_pkg)
    return identities


def mechanism_from_config(
    config: Dict[str, Any],
    body_mechanism: Optional[str] = None,
) -> str:
    """Extract the mechanism string from *config* or an explicit POST override."""
    if body_mechanism:
        return body_mechanism
    phases = config.get("phases", {})
    if isinstance(phases, dict):
        gas = phases.get("gas", {})
        if isinstance(gas, dict):
            mechanism = gas.get("mechanism")
            if mechanism:
                return str(mechanism)
    return "gri30.yaml"


def resolve_mechanism_for_fingerprint(
    config: Dict[str, Any],
    converter_class: Any = None,
    body_mechanism: Optional[str] = None,
) -> str:
    """Resolve the mechanism string used for cache fingerprinting.

    Applies :meth:`~boulder.cantera_converter.DualCanteraConverter.resolve_mechanism`
    from *converter_class* when provided, without constructing a full converter
    (avoids loading Cantera during cache lookups).
    """
    raw = mechanism_from_config(config, body_mechanism=body_mechanism)
    if converter_class is None:
        return raw
    try:
        instance = object.__new__(converter_class)
        return converter_class.resolve_mechanism(instance, raw)
    except Exception:
        return raw


def lookup_cached_result(
    cache_root: Optional[Path],
    config: Dict[str, Any],
    mechanism: Optional[str] = None,
    preloaded_result: Optional[Dict[str, Any]] = None,
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Compute a fingerprint and load a matching cache entry when present.

    Returns
    -------
    tuple
        ``(fingerprint, cached_entry)``.  *fingerprint* is always computed
        when *cache_root* is set; *cached_entry* is ``None`` on a miss.
    """
    if cache_root is None:
        return None, None

    fingerprint = compute_fingerprint(config, mechanism=mechanism)
    cached = load_result_flexible(cache_root, fingerprint)
    if cached is None and preloaded_result is not None:
        snapshot = preloaded_result.get("config_snapshot") or {}
        if snapshot:
            snapshot_fp = compute_fingerprint(snapshot, mechanism=mechanism)
            if snapshot_fp == fingerprint:
                cached = preloaded_result
    return fingerprint, cached


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
        "boulder_source": _source_identity("boulder"),
        "cantera_version": _package_version("cantera"),
        "plugins_source": _plugins_source_identity(),
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

    Creates ``<cache_root>/<fingerprint>/result.h5`` (composite payload),
    ``meta.json`` (incl. ``config_snapshot``), and the ``COMPLETE`` marker.
    Prunes old entries to keep at most :data:`MAX_CACHE_ENTRIES`.

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

        from .payload_store import write_payload

        # Composite HDF5: heavy reactor series as native SolutionArrays / binary
        # datasets, everything else (sankey, reports, summary) as a JSON blob.
        write_payload(tmp_dir / "result.h5", _coerce(gui_payload), mechanism or "")

        # config_snapshot lives in meta.json (P1) so a snapshot scan never has
        # to restore the numeric HDF5.
        meta: Dict[str, Any] = {
            "fingerprint": fingerprint,
            "cache_version": CACHE_VERSION,
            "created_at": time.time(),
            "boulder_version": _package_version("boulder"),
            "cantera_version": _package_version("cantera"),
            "mechanism": mechanism or "",
            "config_snapshot": _coerce(config_snapshot),
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
        meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
        if meta.get("cache_version") != CACHE_VERSION:
            logger.debug("Cache entry version mismatch, ignoring: %s", fingerprint[:12])
            return None
        from .payload_store import read_payload

        gui_payload = read_payload(
            entry / "result.h5", mechanism_override=meta.get("mechanism") or None
        )
        return {
            "fingerprint": fingerprint,
            "gui_payload": gui_payload,
            "config_snapshot": meta.get("config_snapshot", {}),
            "meta": meta,
            "artifacts_dir": entry / "artifacts",
        }
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        logger.debug("Failed to load cache entry %s: %s", fingerprint[:12], exc)
        return None
    except Exception as exc:  # noqa: BLE001 — restore failure ⇒ treat as cache miss
        logger.warning(
            "Cache entry %s payload restore failed, ignoring: %s",
            fingerprint[:12],
            exc,
        )
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


def load_result_flexible(
    cache_root: Path, fingerprint: str
) -> Optional[Dict[str, Any]]:
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
            # Read config_snapshot from meta.json only — never restore the
            # numeric HDF5 just to compare snapshots (P1).
            meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
            if meta.get("cache_version") != CACHE_VERSION:
                continue
            snapshot = meta.get("config_snapshot") or {}
            if not snapshot:
                continue
            snapshot_fp = compute_fingerprint(snapshot, mechanism=mechanism)
            if snapshot_fp == fingerprint:
                # Match — now restore the payload for this one entry.
                return load_result(cache_root, entry_dir.name)
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return None


def clear_cache(cache_root: Path) -> None:
    """Remove all cache entries under *cache_root*."""
    if cache_root.exists():
        shutil.rmtree(cache_root)
    logger.info("Cache cleared: %s", cache_root)


def _prune_orphan_aliases(cache_root: Path) -> None:
    """Remove alias files whose canonical cache entry no longer exists."""
    if not cache_root.exists():
        return
    for alias_file in cache_root.iterdir():
        if not alias_file.is_file() or not alias_file.name.startswith("_alias_"):
            continue
        try:
            canonical_fp = alias_file.read_text(encoding="utf-8").strip()
            target_dir = _entry_dir(cache_root, canonical_fp)
            if not (target_dir / "COMPLETE").exists():
                alias_file.unlink(missing_ok=True)
                logger.debug("Pruned orphan cache alias: %s", alias_file.name[:20])
        except OSError:
            continue


def _prune_cache(cache_root: Path) -> None:
    """Remove oldest cache entries when count exceeds :data:`MAX_CACHE_ENTRIES`."""
    entries = [
        d
        for d in cache_root.iterdir()
        if d.is_dir() and not d.name.startswith("_tmp_") and (d / "COMPLETE").exists()
    ]
    if len(entries) > MAX_CACHE_ENTRIES:
        entries.sort(key=lambda d: (d / "COMPLETE").stat().st_mtime)
        for old in entries[: len(entries) - MAX_CACHE_ENTRIES]:
            shutil.rmtree(old, ignore_errors=True)
            logger.debug("Pruned cache entry: %s", old.name[:12])
    _prune_orphan_aliases(cache_root)


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
