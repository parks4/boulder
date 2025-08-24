"""Pytest configuration for Boulder tests."""

import pytest


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "e2e: marks tests as end-to-end tests requiring Playwright"
    )


@pytest.fixture(scope="session", autouse=True)
def check_playwright():
    """Check if Playwright is available and provide helpful error messages."""
    try:
        import playwright

        playwright  # added not to raise a qa error.

        # Get version from the package metadata
        try:
            from importlib.metadata import version

            playwright_version = version("playwright")
            print(f"\n✅ Playwright found: {playwright_version}")
        except Exception:
            print("\n✅ Playwright found")
        print("   Browsers will be automatically managed by Playwright")
    except ImportError:
        print("\n❌ Playwright not found")
        print("   E2E tests will be skipped")
        print("   Install with: pip install playwright && playwright install")


# Skip E2E tests if Playwright is not available
def pytest_collection_modifyitems(config, items):
    """Skip E2E tests if Playwright is not available."""
    try:
        import playwright

        playwright  # added not to raise a qa error.
    except ImportError:
        skip_e2e = pytest.mark.skip(reason="Playwright not available")
        for item in items:
            if "test_e2e.py" in str(item.fspath):
                item.add_marker(skip_e2e)
