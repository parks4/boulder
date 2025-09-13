"""Tests for the if_no_species parameter in Sankey generation."""

import pytest

from boulder.sankey import generate_sankey_input_from_sim


class TestSankeyIfNoSpecies:
    """Test cases for the if_no_species parameter in Sankey generation."""

    def test_if_no_species_parameter_exists(self):
        """Test that the if_no_species parameter exists and has correct default."""
        # Test that we can call the function with the if_no_species parameter
        # This is a basic test to ensure the parameter was added correctly
        import inspect
        
        sig = inspect.signature(generate_sankey_input_from_sim)
        assert 'if_no_species' in sig.parameters
        assert sig.parameters['if_no_species'].default == "ignore"

    def test_if_no_species_docstring(self):
        """Test that the if_no_species parameter is documented."""
        docstring = generate_sankey_input_from_sim.__doc__
        assert "if_no_species" in docstring
        assert "ignore" in docstring
        assert "warn" in docstring
        assert "error" in docstring
