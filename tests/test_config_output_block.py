from boulder.config import convert_to_stone_format, normalize_config, validate_config


def test_output_block_is_preserved_through_validation_and_conversion():
    config = {
        "nodes": [
            {
                "id": "reactor_id1",
                "IdealGasReactor": {"temperature": 300, "pressure": 101325},
            },
        ],
        "connections": [],
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
