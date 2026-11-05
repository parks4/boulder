"""Pytest configuration for Boulder tests."""


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")


def default_solution(mechanism: str, **kw):
    """Return the default converter's Solution, as the store step requires one."""
    from boulder.cantera_converter import DualCanteraConverter

    return DualCanteraConverter.create_solution(
        DualCanteraConverter.__new__(DualCanteraConverter), mechanism, **kw
    )
