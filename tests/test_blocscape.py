"""Test suite for blocscape."""


def test_version():
    """Test that version is defined."""
    from blocscape import __version__

    assert isinstance(__version__, str)
