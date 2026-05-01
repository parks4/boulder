import pathlib
import re

import pytest
import yaml

VALID_DIR = pathlib.Path(__file__).parent / "fixtures" / "stone_v2" / "valid"
INVALID_DIR = pathlib.Path(__file__).parent / "fixtures" / "stone_v2" / "invalid"
SPEC_PATH = pathlib.Path(__file__).parent.parent / "STONE_SPECIFICATIONS.md"


@pytest.mark.parametrize("path", sorted(VALID_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_valid_fixture(path):
    """Each STONE v2 valid fixture normalizes and validates without error."""
    from boulder.config import normalize_config
    from boulder.validation import validate_normalized_config

    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    norm = normalize_config(cfg)
    validate_normalized_config(norm)


@pytest.mark.parametrize("path", sorted(INVALID_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_invalid_fixture(path):
    """Each STONE v2 invalid fixture raises ValueError with a useful message."""
    from boulder.config import normalize_config
    from boulder.validation import validate_normalized_config

    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        norm = normalize_config(cfg)
        validate_normalized_config(norm)


def test_spec_examples_are_valid_yaml():
    """Every YAML code block in STONE_SPECIFICATIONS.md is parseable without error."""
    spec = SPEC_PATH.read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", spec, re.DOTALL)
    assert len(blocks) > 0, "No YAML blocks found in STONE_SPECIFICATIONS.md"
    for i, block in enumerate(blocks):
        yaml.safe_load(block)  # raises yaml.YAMLError on malformed YAML