"""Test suite for boulder."""


def test_version():
    """Test that version is defined."""
    from boulder import __version__

    assert isinstance(__version__, str)
