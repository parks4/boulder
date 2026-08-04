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
import subprocess
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

#: ``metadata`` keys Boulder *injects* to label a run, excluded from the hash.
#: :func:`boulder.runset.expand_scenarios` stamps ``scenario_id`` onto every
#: run-set entry (``BASELINE`` for the unmodified base). That is bookkeeping —
#: it names the run without changing the physics — so hashing it gave the same
#: solve two different fingerprints depending on whether it was reached through
#: the run-set expansion or straight from the preloaded config, and neither
#: path could recognise the other's cached result. Only keys Boulder writes
#: itself belong here: user-authored metadata (``title``, ``description``, …)
#: still participates. See ``tests/test_fingerprint_identity.py``.
_RUN_LABEL_METADATA_KEYS = ("scenario_id",)


def _canonical_config(config: Dict[str, Any]) -> Any:
    """Canonicalise *config* so equivalent representations hash identically.

    Two transformations, both about *representation* rather than physics:

    1. Drop the injected run label (:data:`_RUN_LABEL_METADATA_KEYS`).
    2. Drop ``None``-valued mapping keys recursively. A config that has been
       through Pydantic validation carries explicit nulls for every unset
       optional (``export: None``, and ``metadata``/``network_class`` on every
       node), while one that has only been normalised simply omits them —
       so the run-set path and the preloaded path described the identical run
       with different dicts.

    Same intent as :func:`_coerce`'s integer-float normalisation, and
    deliberately *not* folded into it: ``_coerce`` also serialises
    ``gui_payload`` in :func:`save_result`, where dropping ``None`` would
    discard real fields (e.g. ``error_message``).

    The caller's dict is never mutated.
    """

    def _strip(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _strip(v) for k, v in obj.items() if v is not None}
        if isinstance(obj, (list, tuple)):
            return [_strip(v) for v in obj]
        return obj

    metadata = config.get("metadata")
    if isinstance(metadata, dict) and any(
        k in metadata for k in _RUN_LABEL_METADATA_KEYS
    ):
        config = {
            **config,
            "metadata": {
                k: v for k, v in metadata.items() if k not in _RUN_LABEL_METADATA_KEYS
            },
        }
    return _strip(config)


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
        "config": _coerce(_canonical_config(config)),
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
