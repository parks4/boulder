# Boulder Test Suite

This directory contains the comprehensive test suite for the Boulder application.

## Test Organization

### Test Files

- **`test_unit.py`** - Unit tests for core Boulder functionality
- **`test_yaml_comment_system.py`** - Comprehensive YAML comment preservation tests
- **`test_e2e.py`** - End-to-end tests (requires ChromeDriver)
- **`test_blocscape.py`** - Basic version/import tests

### Test Categories

Tests are organized using pytest markers:

- `@pytest.mark.unit` - Fast unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.e2e` - End-to-end tests requiring browser
- `@pytest.mark.slow` - Slow-running tests

## Running Tests

### All Tests (except E2E)
```bash
pytest tests/ -m "not e2e"
```

### Unit Tests Only
```bash
pytest tests/ -m unit
```

### YAML Comment Tests Only
```bash
pytest tests/test_yaml_comment_system.py -v
```

### E2E Tests (requires ChromeDriver)
```bash
pytest tests/ -m e2e
```

### All Tests with Coverage
```bash
pytest tests/ -m "not e2e" --cov=boulder --cov-report=html
```

## Test Requirements

### Standard Tests
- Python 3.11+
- pytest
- All Boulder dependencies

### E2E Tests (Optional)
- ChromeDriver installed and in PATH
- Chrome browser
- Selenium WebDriver

## Test Structure

### YAML Comment System Tests

The `test_yaml_comment_system.py` file contains comprehensive tests for:

1. **Core Functionality** (`TestYAMLCommentCore`)
   - YAML loading and saving with comments
   - Data type preservation
   - Basic comment preservation

2. **Round-Trip Conversions** (`TestYAMLCommentRoundTrip`)
   - YAML ↔ Internal ↔ STONE format conversions
   - Comment preservation during format changes

3. **Integration Tests** (`TestYAMLCommentIntegration`)
   - File upload simulation
   - Application integration
   - Error handling

4. **Edge Cases** (`TestYAMLCommentEdgeCases`)
   - Invalid YAML handling
   - Empty/minimal configurations
   - Various unit formats

5. **File Operations** (`TestYAMLFileOperations`)
   - File I/O with comment preservation
   - UTF-8 encoding handling

### Unit Tests

The `test_unit.py` file covers:

- Configuration loading and validation
- Component creation and management
- Callback logic
- Layout generation
- Application integration

### E2E Tests

The `test_e2e.py` file provides browser-based testing for:

- User interface interactions
- Modal dialogs
- Form validation
- Graph interactions
- Simulation workflows

## Configuration

Test configuration is managed through `pyproject.toml` in the `[tool.pytest.ini_options]` section:

- Test discovery patterns
- Marker definitions
- Warning filters
- Default options

## Best Practices

1. **Test Isolation** - Each test should be independent
2. **Clear Naming** - Test names should describe what they test
3. **Comprehensive Coverage** - Test both success and failure cases
4. **Fast Execution** - Keep unit tests fast, mark slow tests appropriately
5. **Documentation** - Include docstrings explaining test purpose

## Troubleshooting

### E2E Test Failures
- Ensure ChromeDriver is installed and in PATH
- Check Chrome browser version compatibility
- Verify network connectivity for app startup

### Import Errors
- Ensure Boulder package is properly installed
- Check Python path configuration
- Verify all dependencies are installed

### YAML Test Failures
- Check file encoding (should be UTF-8)
- Verify ruamel.yaml installation
- Check for Unicode character issues

## Contributing

When adding new tests:

1. Choose the appropriate test file based on test type
2. Add appropriate pytest markers
3. Follow existing naming conventions
4. Include comprehensive docstrings
5. Test both success and failure scenarios
6. Update this README if adding new test categories 