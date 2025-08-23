import pytest

from boulder.output_summary import (
    evaluate_output_items,
    format_summary_text,
    parse_output_block,
)


def _dummy_results():
    return {
        "time": [0.0, 1.0, 2.0],
        "reactors": {
            "PFR": {
                "T": [290.0, 300.0, 310.0],
                "P": [1.0e5, 1.05e5, 1.1e5],
                "X": {"H2": [0.1, 0.2, 0.3]},
            },
            "CSTR": {
                "T": [1000.0, 1100.0, 1200.0],
                "P": [2.0e5, 2.5e5, 3.0e5],
                "X": {"CH4": [0.05, 0.02, 0.01]},
            },
        },
    }


def test_parse_mapping_format():
    """Test parsing dict format: {reactor_id: spec}."""
    block = {
        "PFR": "temperature",
        "CSTR": ["temperature, K", "pressure, bar"],
    }
    items = parse_output_block(block)
    assert len(items) == 3
    assert items[0].reactor == "PFR" and items[0].quantity == "temperature"
    assert (
        items[1].reactor == "CSTR"
        and items[1].quantity == "temperature"
        and items[1].unit == "K"
    )
    assert (
        items[2].reactor == "CSTR"
        and items[2].quantity == "pressure"
        and items[2].unit == "bar"
    )


def test_parse_list_format():
    """Test parsing list format: [{reactor_id: spec}, ...]."""
    block = [
        {"PFR": "temperature"},
        {"CSTR": "pressure, bar"},
    ]
    items = parse_output_block(block)
    assert len(items) == 2
    assert items[0].reactor == "PFR" and items[0].quantity == "temperature"
    assert (
        items[1].reactor == "CSTR"
        and items[1].quantity == "pressure"
        and items[1].unit == "bar"
    )


def test_evaluate_temperature_and_pressure():
    """Test evaluation of temperature and pressure with unit conversion."""
    items = parse_output_block(
        {
            "PFR": ["temperature, K", "temperature, C"],
            "CSTR": ["pressure, Pa", "pressure, bar"],
        }
    )
    evaluated = evaluate_output_items(items, _dummy_results())

    # PFR final T = 310 K
    assert evaluated[0]["value"] == pytest.approx(310.0)  # K
    assert evaluated[1]["value"] == pytest.approx(36.85, rel=1e-3)  # C

    # CSTR final P = 3.0e5 Pa
    assert evaluated[2]["value"] == pytest.approx(3.0e5)  # Pa
    assert evaluated[3]["value"] == pytest.approx(3.0)  # bar


def test_evaluate_formula():
    """Test formula evaluation."""
    items = parse_output_block(
        {
            "result": "PFR.T(C) + 10",
        }
    )
    evaluated = evaluate_output_items(items, _dummy_results())
    # PFR final T = 310 K = 36.85 C, so result = 46.85
    assert evaluated[0]["value"] == pytest.approx(46.85, rel=1e-3)


def test_format_summary_text():
    """Test text formatting."""
    evaluated = [
        {"reactor": "PFR", "quantity": "temperature", "value": 310.0, "unit": "K"},
        {"reactor": "CSTR", "quantity": "pressure", "value": 3.0, "unit": "bar"},
    ]
    text = format_summary_text(evaluated)
    assert "SIMULATION SUMMARY" in text
    assert "PFR temperature: 310.000 K" in text
    assert "CSTR pressure: 3.000 bar" in text


def test_missing_reactor_error():
    """Test error handling for missing reactor."""
    items = parse_output_block({"missing": "temperature"})
    evaluated = evaluate_output_items(items, _dummy_results())
    assert "error" in evaluated[0]
