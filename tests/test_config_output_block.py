from boulder.config import convert_to_stone_format, normalize_config, validate_config


def test_output_block_is_preserved_through_validation_and_conversion():
    """Assert that output: block survives normalize + validate + convert_to_stone_format."""
    config = {
        "network": [
            {
                "id": "upstream",
                "Reservoir": {"temperature": 300, "composition": "N2:1"},
            },
            {
                "id": "reactor_id1",
                "IdealGasReactor": {"volume": 1.0e-3},
            },
            {
                "id": "mfc1",
                "MassFlowController": {"mass_flow_rate": 0.001},
                "source": "upstream",
                "target": "reactor_id1",
            },
        ],
        "settings": {"end_time": 1.0, "dt": 1.0},
        "output": {
            "reactor_id1": ["temperature, K", "pressure, bar"],
        },
    }

    normalized = normalize_config(config)
    validated = validate_config(normalized)
    assert "output" in validated and isinstance(validated["output"], dict)
    assert "reactor_id1" in validated["output"]

    roundtrip = convert_to_stone_format(validated)
    assert "output" in roundtrip and roundtrip["output"] == config["output"]
