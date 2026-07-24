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
place instead of leaving a trail of one-off files. A config that *was*
already preloaded from a real file is left untouched -- this only ever fires
for the "no file yet" case.
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
) -> None:
    """Persist *yaml_str* to disk and adopt it as the preloaded config.

    No-op when a real preloaded config path is already set (a config Boulder
    was started with from the CLI) -- this only ever materializes the
    "started with no file" case, and never overwrites or shadows a
    user-provided file.

    Parameters
    ----------
    request
        The current request, used to reach and mutate ``app.state``.
    raw
        The inheritance-resolved config dict (pre-normalize -- keeps
        ``scenarios:``/``sweep:``/``sweeps:`` blocks intact), stored as
        ``app.state.preloaded_raw`` for the Run Sweep / Scenario Pane checks.
    validated
        The normalized + validated config dict, stored as
        ``app.state.preloaded_config``.
    yaml_str
        The raw YAML text as authored in the browser, written verbatim to
        the adopted file and stored as ``app.state.preloaded_yaml``.
    filename
        Display filename to adopt (e.g. an uploaded file's original name).
        Defaults to ``"config.yaml"``.
    """
    state = request.app.state
    live_dir = getattr(state, _LIVE_CONFIG_DIR_ATTR, None)
    if live_dir is None:
        # First adoption this session: bail if a *real* CLI-provided config
        # path is already set. Once we've adopted once, `_LIVE_CONFIG_DIR_ATTR`
        # is set and every later call is known to be updating our own
        # ephemeral file, so this check is skipped on subsequent calls --
        # otherwise the very first adoption would set preloaded_config_path
        # and permanently block all later edits from ever being adopted.
        if getattr(state, "preloaded_config_path", None):
            return
        live_dir = tempfile.mkdtemp(prefix="boulder-live-config-")
        setattr(state, _LIVE_CONFIG_DIR_ATTR, live_dir)

    path = Path(live_dir) / (filename or getattr(state, "preloaded_filename", None) or "config.yaml")
    path.write_text(yaml_str, encoding="utf-8")

    state.preloaded_config = validated
    state.preloaded_raw = raw
    state.preloaded_yaml = yaml_str
    state.preloaded_filename = path.name
    state.preloaded_config_path = str(path)
    logger.info("Adopted browser-authored config as preloaded config: %s", path)
