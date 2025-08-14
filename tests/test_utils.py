"""Shared test utilities for Boulder test suite."""

import base64
import yaml
from selenium.common.exceptions import TimeoutException


def upload_test_config_to_app(dash_duo):
    """Upload a test config file to enable config editing functionality.
    
    This utility function uploads a realistic test configuration that includes:
    - Multiple reactors with proper STONE format
    - Simulation parameters 
    - Comments and units (as they would appear in real configs)
    
    Args:
        dash_duo: The dash_duo fixture from pytest-dash
        
    Returns:
        bool: True if upload was successful, False otherwise
    """
    # Use a realistic config similar to what's in the YAML comment system tests
    # This matches the format users would actually use
    test_config_yaml = """# Boulder Test Configuration with STONE Standard
# This configuration is used for automated testing

metadata:
  name: "Test Configuration"
  description: "Configuration for automated testing"
  version: "1.0"

# Simulation parameters
simulation:
  end_time: 2.0      # seconds - total simulation duration
  dt: 0.01          # seconds - integration time step
  mechanism: "gri30.yaml"

# Reactor components with detailed comments
components:
  - id: "test-reactor"
    # Primary test reactor for automated testing
    IdealGasReactor:
      temperature: 300.0    # K - initial temperature
      pressure: 101325.0    # Pa - initial pressure (1 atm)
      composition: "O2:1,N2:3.76"  # standard air composition

  - id: "test-reservoir"
    # Reservoir for testing flow connections
    Reservoir:
      temperature: 300.0    # K - reservoir temperature
      pressure: 101325.0    # Pa - reservoir pressure
      composition: "CH4:1,O2:2,N2:7.52"  # methane-air mixture

# Flow connections for testing
connections:
  - id: "test-mfc"
    # Mass flow controller for testing
    MassFlowController:
      mass_flow_rate: 0.001  # kg/s - controlled flow rate
    source: "test-reservoir"
    target: "test-reactor"
"""

    # Encode as base64 (mimicking file upload)
    encoded_content = base64.b64encode(test_config_yaml.encode("utf-8")).decode("utf-8")
    
    # Create the upload data format expected by Dash
    upload_data = f"data:text/yaml;base64,{encoded_content}"
    
    # Wait for the upload element to be available
    try:
        dash_duo.wait_for_element("#upload-config", timeout=10)
        print("Upload element found, attempting to upload test config...")
        
        # Multiple attempts to trigger the upload
        for attempt in range(3):
            try:
                # Trigger the upload via JavaScript by directly calling the callback
                script = f"""
                console.log('Attempting config upload, attempt {attempt + 1}');
                var uploadElement = document.getElementById('upload-config');
                if (uploadElement) {{
                    console.log('Upload element found');
                    var props = {{
                        'contents': '{upload_data}',
                        'filename': 'test_config.yaml',
                        'last_modified': Date.now()
                    }};
                    
                    // Try multiple methods to trigger the callback
                    if (uploadElement._dashprivate_setProps) {{
                        console.log('Using _dashprivate_setProps');
                        uploadElement._dashprivate_setProps(props);
                    }} else if (window.dash_clientside && window.dash_clientside.set_props) {{
                        console.log('Using dash_clientside.set_props');
                        window.dash_clientside.set_props('upload-config', props);
                    }} else {{
                        console.log('Using custom event fallback');
                        var event = new CustomEvent('upload', {{
                            detail: props,
                            bubbles: true
                        }});
                        uploadElement.dispatchEvent(event);
                    }}
                    return 'upload_triggered';
                }} else {{
                    console.error('Upload element not found');
                    return 'element_not_found';
                }}
                """
                
                result = dash_duo.driver.execute_script(script)
                print(f"Upload script result: {result}")
                
                # Wait a bit longer for the upload to process
                import time
                time.sleep(2)
                
                # Check if the config file name appeared
                try:
                    dash_duo.wait_for_element("#config-file-name-span", timeout=5)
                    print("Config upload successful!")
                    return True  # Success
                except TimeoutException:
                    print(f"Config upload attempt {attempt + 1} failed, config file name not found")
                    continue
                    
            except Exception as e:
                print(f"Config upload attempt {attempt + 1} failed with error: {e}")
                continue
        
        print("All config upload attempts failed")
        return False
        
    except Exception as e:
        # If upload fails, that's okay - tests will handle gracefully
        print(f"Config upload failed: {e}")
        return False
