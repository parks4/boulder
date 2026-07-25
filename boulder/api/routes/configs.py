"""Config management API routes.

Endpoints for loading, parsing, validating, exporting, and uploading
reactor network configurations in the STONE YAML format.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ...config import (
    convert_to_stone_format,
    get_initial_config_with_comments,
    load_yaml_string_with_comments,
    merge_config_into_yaml,
    normalize_config,
    validate_config,
    yaml_to_string_with_comments,
)
from ..live_config import adopt_live_config

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class YAMLParseRequest(BaseModel):
    yaml: str


class ConfigExportRequest(BaseModel):
    config: Dict[str, Any]


class ConfigValidateRequest(BaseModel):
    config: Dict[str, Any]


class ConfigSyncRequest(BaseModel):
    config: Dict[str, Any]
    original_yaml: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/default")
async def get_default_config(request: Request) -> Dict[str, Any]:
    """Return the default reactor network configuration with original YAML.

    The runner class registered by the CLI (stored on ``app.state.runner_class``)
    is used to normalise the config so that host-specific defaults (e.g. an
    application title injected by a custom runner) are applied even when no
    config file was preloaded.
    """
    try:
        config, original_yaml = get_initial_config_with_comments()
        runner_cls = getattr(request.app.state, "runner_class", None)
        if runner_cls is not None:
            config = runner_cls.normalize(config)
            config = runner_cls.validate(config)
        return {"config": config, "yaml": original_yaml}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/preloaded")
async def get_preloaded_config(request: Request) -> Dict[str, Any]:
    """Return the preloaded configuration if one was specified via CLI.

    If no configuration was preloaded (no BOULDER_CONFIG_PATH env var),
    returns an empty response with preloaded: false.
    """
    preloaded_config = getattr(request.app.state, "preloaded_config", None)
    if preloaded_config is not None:
        return {
            "preloaded": True,
            "config": preloaded_config,
            "yaml": getattr(request.app.state, "preloaded_yaml", None) or "",
            "filename": getattr(request.app.state, "preloaded_filename", None)
            or "config.yaml",
        }
    return {"preloaded": False}


@router.post("/parse")
async def parse_yaml(request: Request, body: YAMLParseRequest) -> Dict[str, Any]:
    """Parse a YAML string, normalise and validate it.

    Uses the runner class registered by the CLI (``app.state.runner_class``) so
    that host-specific normalisation (e.g. custom metadata defaults) is applied
    consistently whether a config is preloaded or uploaded through the editor.

    Returns the validated internal-format config dict.
    """
    try:
        data = load_yaml_string_with_comments(body.yaml)
        # Convert ruamel CommentedMap to plain dict for normalisation
        plain = _to_plain_dict(data)
        runner_cls = getattr(request.app.state, "runner_class", None)
        if runner_cls is not None:
            normalized = runner_cls.normalize(plain)
            validated = runner_cls.validate(normalized)
        else:
            normalized = normalize_config(plain)
            validated = validate_config(normalized)

        # See the Run Sweep button / Scenario Pane -- both need a real
        # on-disk config path to work at all, which a browser-only session
        # (no CLI-preloaded file) never has otherwise.
        adopt_live_config(request, raw=plain, validated=validated, yaml_str=body.yaml)

        return {"config": validated, "yaml": body.yaml}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/validate")
async def validate_config_endpoint(body: ConfigValidateRequest) -> Dict[str, Any]:
    """Validate a normalised config dict (no YAML parsing).

    Returns the validated config or a 422 error with details.
    """
    try:
        validated = validate_config(body.config)
        return {"config": validated}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/export")
async def export_config(body: ConfigExportRequest) -> Dict[str, Any]:
    """Convert an internal-format config back to STONE YAML string."""
    try:
        stone = convert_to_stone_format(body.config)
        yaml_str = yaml_to_string_with_comments(stone)
        return {"yaml": yaml_str}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/sync")
async def sync_config(body: ConfigSyncRequest) -> Dict[str, Any]:
    """Merge an updated config back into the original YAML, preserving comments and units.

    Accepts the live (normalized, SI) config from the frontend together with
    the original YAML string that was loaded from disk.  Returns the merged
    YAML and a list of non-fatal warnings (e.g. Pint back-conversion failures).

    Returns HTTP 422 when the sync cannot be performed safely, e.g.:

    * The original YAML used inline port shortcuts (``inlet:`` / ``outlet:``).
    * Top-level shape mismatch between original YAML and current config.
    """
    try:
        yaml_str, warnings = merge_config_into_yaml(body.config, body.original_yaml)
        return {"yaml": yaml_str, "warnings": warnings}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("POST /api/configs/sync failed")
        raise HTTPException(
            status_code=500,
            detail=f"YAML sync failed ({type(exc).__name__}): {exc}",
        ) from exc


@router.post("/upload")
async def upload_config(
    request: Request, file: UploadFile = File(...)
) -> Dict[str, Any]:
    """Upload a YAML or Python config file and return the validated config.

    Supported extensions: ``.yaml``, ``.yml``, ``.py``.
    Python files are automatically converted to YAML via sim2stone.

    Uses the runner class registered by the CLI (``app.state.runner_class``),
    same as ``/parse``, so host-specific normalisation (e.g. custom metadata
    defaults) is applied consistently whether a config is preloaded, parsed,
    or uploaded through the editor.
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in (".yaml", ".yml", ".py"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Use .yaml, .yml, or .py",
        )

    tmp_py = None
    yaml_path = None
    try:
        contents = await file.read()
        decoded = contents.decode("utf-8")

        if ext == ".py":
            # Save to temp file, convert via sim2stone, then load YAML
            from ...parser import convert_py_to_yaml

            # Securely create temp file with suffix to prevent path traversal
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", encoding="utf-8", delete=False
            ) as f:
                tmp_py = f.name
                f.write(decoded)

            try:
                yaml_path = convert_py_to_yaml(tmp_py)
                with open(yaml_path, "r", encoding="utf-8") as f:
                    yaml_str = f.read()
            finally:
                # Clean up temporary files
                if tmp_py and os.path.exists(tmp_py):
                    os.unlink(tmp_py)
                if yaml_path and os.path.exists(yaml_path):
                    os.unlink(yaml_path)
        else:
            yaml_str = decoded

        data = load_yaml_string_with_comments(yaml_str)
        plain = _to_plain_dict(data)
        runner_cls = getattr(request.app.state, "runner_class", None)
        if runner_cls is not None:
            normalized = runner_cls.normalize(plain)
            validated = runner_cls.validate(normalized)
        else:
            normalized = normalize_config(plain)
            validated = validate_config(normalized)

        adopt_live_config(
            request,
            raw=plain,
            validated=validated,
            yaml_str=yaml_str,
            filename=file.filename,
        )

        return {
            "config": validated,
            "yaml": yaml_str,
            "filename": file.filename,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_plain_dict(data: Any) -> Any:
    """Recursively convert ruamel CommentedMap/Seq to plain Python dicts/lists."""
    if isinstance(data, dict):
        return {k: _to_plain_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_to_plain_dict(item) for item in data]
    return data
