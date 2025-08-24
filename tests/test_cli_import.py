"""Test CLI import functionality to catch import errors early."""

import pytest


def test_cli_import():
    """Test that CLI module can be imported without errors."""
    try:
        from boulder.cli import main, parse_args

        # If we get here, the imports worked
        assert main is not None
        assert parse_args is not None
    except ImportError as e:
        pytest.fail(f"Failed to import CLI module: {e}")


def test_cli_parse_args():
    """Test that CLI argument parsing works."""
    from boulder.cli import parse_args

    # Test default arguments
    args = parse_args([])
    assert args.config is None
    assert args.host == "127.0.0.1"
    assert args.port == 8050
    assert args.debug is False
    assert args.no_open is False
    assert args.verbose is False
    assert args.no_port_search is False

    # Test with arguments
    args = parse_args(["--host", "0.0.0.0", "--port", "9000", "--debug", "--verbose"])
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.debug is True
    assert args.verbose is True


def test_cli_main_import_dependencies():
    """Test that main function imports work correctly.

    This test specifically checks that the imports in the main function
    work correctly, which was the source of the original error.
    """
    # Test that we can import the CLI module and its dependencies
    try:
        # Test that we can import the app module that was failing
        from boulder import app
        from boulder.cli import main

        # If we get here, the imports worked
        assert main is not None
        assert app is not None
    except ImportError as e:
        pytest.fail(f"Import error in CLI dependencies: {e}")
