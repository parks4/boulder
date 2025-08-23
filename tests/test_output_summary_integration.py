from boulder.cantera_converter import DualCanteraConverter


def test_output_summary_in_results():
    """Test that output summary appears in simulation results."""
    config = {
        "nodes": [
            {
                "id": "PFR",
                "type": "IdealGasReactor",
                "properties": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            }
        ],
        "connections": [],
        "settings": {"end_time": 1.0, "dt": 1.0},
        "output": [{"PFR": "temperature"}],  # Test the list format user mentioned
    }

    conv = DualCanteraConverter()
    conv.build_network(config)
    results, _ = conv.run_streaming_simulation(
        simulation_time=1.0,
        time_step=1.0,
        config=config,  # Pass config to run_streaming_simulation
    )

    # Check that summary is present
    assert "summary" in results
    summary = results["summary"]
    assert len(summary) == 1
    assert summary[0]["reactor"] == "PFR"
    assert summary[0]["quantity"] == "temperature"
    assert "value" in summary[0]
    assert summary[0]["value"] is not None


def test_output_summary_text_formatting():
    """Test that the text formatting works."""
    from boulder.output_summary import format_summary_text

    summary = [
        {"reactor": "PFR", "quantity": "temperature", "value": 310.5, "unit": "K"},
        {"reactor": "PFR", "quantity": "pressure", "value": 2.5, "unit": "bar"},
    ]

    text = format_summary_text(summary)
    assert "SIMULATION SUMMARY" in text
    assert "PFR temperature: 310.500 K" in text
    assert "PFR pressure: 2.500 bar" in text
