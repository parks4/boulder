"""Adopt a browser-authored config as the server's preloaded config.

Several Boulder features -- the Run Sweep button (:mod:`.routes.sweep`),
Scenario Pane authoring (:mod:`.routes.scenarios`), and result caching
(:mod:`...result_cache`) -- are keyed off ``app.state.preloaded_config_path``:
a real on-disk file, normally set once at CLI startup from a YAML path
argument (see the ``lifespan`` handler in :mod:`.main`). When Boulder is
instead started with no file -- a browser-only deployment where users paste
or upload their own config -- that path stays ``None`` for the whole session,
so those features never see whatever the user is editing, even a config that
already declares ``scenarios:``.

:func:`adopt_live_config` closes that gap: the first time a live config is
parsed or uploaded with no preloaded path set, it is written to a private
temp file and adopted as the preloaded config, exactly as if Boulder had been
started with that file. Subsequent edits overwrite the same temp file in
place instead of leaving a trail of one-off files.

When a config *was* preloaded from a real file, the two halves of "the
preloaded config" are treated differently:

* **Content** (``preloaded_raw`` / ``preloaded_config`` / ``preloaded_yaml``)
  always follows the browser -- an in-place edit saved from the YAML pane
  becomes the base that Run Sweep merges overlays onto and the ``scenarios:``
  block the Scenario Pane re-seeds from. Otherwise a scenario the user just
  typed vanishes from the pane and the sweep solves the startup network.
* **Location** (``preloaded_config_path`` / ``preloaded_filename``) stays with
  the user's file: its directory anchors relative paths (``from:``
  inheritance, mechanism files, ``cache_store``), the result store and the
  store's identity stamp. Adopting an edit into a temp copy would break all
  of those, so no temp file is written for a CLI-provided config.

A *file upload* is a different file, not an edit, so it adopts regardless
(``replace=True``) and gets its own location -- otherwise a server started
with a starter file would keep serving that file's result cache for whatever
the user uploads afterwards. The user's own file is never written to.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Request

logger = logging.getLogger(__name__)

#: Attribute name on ``app.state`` for the private directory backing
#: adopted live configs (created lazily, reused across calls).
_LIVE_CONFIG_DIR_ATTR = "_live_config_dir"


def adopt_live_config(
    request: Request,
    raw: Dict[str, Any],
    validated: Dict[str, Any],
    yaml_str: str,
    filename: Optional[str] = None,
    *,
    replace: bool = False,
) -> None:
    """Adopt *yaml_str* (and its parsed forms) as the preloaded config.

    With no real preloaded config path set, or with *replace* true, the YAML
    is written to a private temp file that becomes the config's location.
    When a real CLI-provided path is set and *replace* is false, only the
    *content* attributes are updated and the location is left alone (see the
    module docstring). The user's own file is never written to.

    Parameters
    ----------
    request
        The current request, used to reach and mutate ``app.state``.
    raw
        The inheritance-resolved config dict (pre-normalize -- keeps the
        ``scenarios:``/``scenarios_sweep:`` blocks intact), stored as
        ``app.state.preloaded_raw`` for the Run Sweep / Scenario Pane checks.
        Legacy run-set spellings are renamed in place here, with a warning,
        so the stored base speaks the canonical dialect.
    validated
        The normalized + validated config dict, stored as
        ``app.state.preloaded_config``.
    yaml_str
        The raw YAML text as authored in the browser, written verbatim to
        the adopted file and stored as ``app.state.preloaded_yaml``.
    filename
        Display filename to adopt (e.g. an uploaded file's original name).
        Defaults to ``"config.yaml"``.
    replace
        The browser replaced the whole config (file upload): adopt even over
        a CLI-preloaded file, location included, so the result cache follows
        the new file instead of the file the server started with.
    """
    from ..runset import canonicalize_run_set_keys  # noqa: PLC0415 — avoid import cycle

    canonicalize_run_set_keys(raw)
    state = request.app.state
    live_dir = getattr(state, _LIVE_CONFIG_DIR_ATTR, None)
    if live_dir is None:
        # First adoption this session with a *real* CLI-provided config path
        # already set: an in-place edit. Take the content, keep the location
        # (see the module docstring for why the two are split). Once we've
        # adopted once, `_LIVE_CONFIG_DIR_ATTR` is set and every later call is
        # known to be updating our own ephemeral file, so this branch is
        # skipped on subsequent calls -- otherwise the very first adoption
        # would set preloaded_config_path and route every later edit here.
        if getattr(state, "preloaded_config_path", None) and not replace:
            state.preloaded_config = validated
            state.preloaded_raw = raw
            state.preloaded_yaml = yaml_str
            logger.info(
                "Updated live config content; location stays %s",
                state.preloaded_config_path,
            )
            return
        live_dir = tempfile.mkdtemp(prefix="boulder-live-config-")
        setattr(state, _LIVE_CONFIG_DIR_ATTR, live_dir)

    path = Path(live_dir) / (
        filename or getattr(state, "preloaded_filename", None) or "config.yaml"
    )
    path.write_text(yaml_str, encoding="utf-8")

    state.preloaded_config = validated
    state.preloaded_raw = raw
    state.preloaded_yaml = yaml_str
    state.preloaded_filename = path.name
    state.preloaded_config_path = str(path)
    logger.info("Adopted browser-authored config as preloaded config: %s", path)
