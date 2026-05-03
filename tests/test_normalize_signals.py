"""Tests for signals/bindings/scopes passthrough in normalize_config (Phase A).

Asserts:
- signals: block is preserved through normalize_config for single-stage YAML.
- bindings: block is preserved through normalize_config for single-stage YAML.
- scopes: block is preserved through normalize_config.
- All three keys are preserved in multi-stage (staged) YAML.
- YAML without these keys normalises without error.
"""

import pytest
import yaml

from boulder.config import normalize_config


def _parse(yaml_str: str):
    return yaml.safe_load(yaml_str)


_NETWORK_WITH_CAUSAL_YAML = """
metadata:
  title: causal layer test
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: micro_step
    t_total: 1.0e-7
    chunk_dt: 1.0e-9
    max_dt: 1.0e-10
signals:
  - id: pulse
    Gaussian:
      peak: 1.9e-19
      center: 24e-9
      fwhm: 7.06e-9
bindings:
  - source: pulse
    target: nodes.r1.reduced_electric_field
scopes:
  - variable: nodes.r1.T
    output: true
network:
- id: r1
  ConstPressureReactor:
    initial:
      temperature: 300.0
      pressure: 101325.0
      composition: "N2:1"
"""

_STAGED_WITH_CAUSAL_YAML = """
metadata:
  title: staged causal test
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: advance_to_steady_state
signals:
  - id: tau
    Constant:
      value: 0.1
bindings:
  - source: tau
    target: connections.mfc.tau_s
scopes:
  - variable: nodes.psr.T
    output: true
stages:
  psr:
    mechanism: gri30.yaml
    solver:
      kind: advance_to_steady_state
psr:
- id: psr
  IdealGasReactor:
    volume: 1 L
"""


class TestSignalsPassthrough:
    def test_signals_preserved_in_network_yaml(self):
        """signals: block is preserved through normalize_config."""
        cfg = normalize_config(_parse(_NETWORK_WITH_CAUSAL_YAML))
        assert "signals" in cfg
        assert len(cfg["signals"]) == 1
        assert cfg["signals"][0]["id"] == "pulse"

    def test_bindings_preserved_in_network_yaml(self):
        """bindings: block is preserved through normalize_config."""
        cfg = normalize_config(_parse(_NETWORK_WITH_CAUSAL_YAML))
        assert "bindings" in cfg
        assert cfg["bindings"][0]["source"] == "pulse"
        assert cfg["bindings"][0]["target"] == "nodes.r1.reduced_electric_field"

    def test_scopes_preserved_in_network_yaml(self):
        """scopes: block is preserved through normalize_config."""
        cfg = normalize_config(_parse(_NETWORK_WITH_CAUSAL_YAML))
        assert "scopes" in cfg
        assert cfg["scopes"][0]["variable"] == "nodes.r1.T"

    def test_causal_keys_preserved_in_staged_yaml(self):
        """signals:, bindings:, scopes: are preserved for staged YAML."""
        cfg = normalize_config(_parse(_STAGED_WITH_CAUSAL_YAML))
        assert "signals" in cfg
        assert "bindings" in cfg
        assert "scopes" in cfg

    def test_yaml_without_causal_keys_normalises_cleanly(self):
        """YAML without signals/bindings/scopes normalises without error."""
        raw = """
metadata:
  title: bare
phases:
  gas:
    mechanism: gri30.yaml
network:
- id: r1
  IdealGasReactor:
    volume: 1 L
"""
        cfg = normalize_config(_parse(raw))
        assert "signals" not in cfg
        assert "bindings" not in cfg
        assert "scopes" not in cfg

    def test_signals_content_survives_intact(self):
        """The full signals list is passed through unchanged."""
        cfg = normalize_config(_parse(_STAGED_WITH_CAUSAL_YAML))
        sig = cfg["signals"][0]
        assert sig["id"] == "tau"
        assert "Constant" in sig
        assert sig["Constant"]["value"] == pytest.approx(0.1)
