"""Python to YAML conversion utilities using sim2stone."""

import os
import tempfile
from typing import Optional


def _run_sim2stone_conversion(py_path: str, verbose: bool = False) -> str:
    """Run sim2stone conversion on a Python file.

    Args:
        py_path: Path to the Python file
        verbose: Enable verbose output

    Returns
    -------
        Path to the generated YAML file

    Raises
    ------
        RuntimeError: If conversion fails
    """
    from ..sim2stone_cli import main as sim2stone_main

    # Generate output path
    base, _ = os.path.splitext(os.path.abspath(py_path))
    yaml_path = base + ".yaml"

    # Prepare arguments for sim2stone
    args = [py_path, "-o", yaml_path]
    if verbose:
        args.append("--verbose")

    # Run sim2stone conversion
    exit_code = sim2stone_main(args)
    if exit_code != 0:
        raise RuntimeError(f"sim2stone conversion failed with exit code {exit_code}")

    # Check if the expected file exists
    if os.path.exists(yaml_path):
        return yaml_path

    # If not, check for common variations (like .tmp files)
    temp_yaml_path = yaml_path + ".tmp"
    if os.path.exists(temp_yaml_path):
        return temp_yaml_path

    # If neither exists, raise an error
    raise RuntimeError(
        f"Expected YAML file was not created: {yaml_path} (also checked {temp_yaml_path})"
    )


def _generate_unique_yaml_path(original_yaml_path: str) -> str:
    """Generate a unique YAML path when a conflict exists.

    Args:
        original_yaml_path: The original YAML path that would conflict

    Returns
    -------
        A unique path with a suffix like _converted, _converted_2, etc.
    """
    base, ext = os.path.splitext(original_yaml_path)
    counter = 1

    # Try _converted first
    new_path = f"{base}_converted{ext}"
    while os.path.exists(new_path):
        counter += 1
        new_path = f"{base}_converted_{counter}{ext}"

    return new_path


def _yaml_files_are_different(yaml_path1: str, yaml_path2: str) -> bool:
    """Compare two YAML files to see if they have different content.

    Args:
        yaml_path1: Path to first YAML file
        yaml_path2: Path to second YAML file

    Returns
    -------
        True if files are different, False if they are the same
    """
    import yaml

    with open(yaml_path1, "r", encoding="utf-8") as f1:
        content1 = yaml.safe_load(f1)
    with open(yaml_path2, "r", encoding="utf-8") as f2:
        content2 = yaml.safe_load(f2)

    return content1 != content2


def _handle_yaml_conflicts(
    yaml_path: str, config_path: str, verbose: bool = False
) -> str:
    """Handle conflicts with existing YAML files.

    Args:
        yaml_path: Path to the newly generated YAML file
        config_path: Path to the original Python file
        verbose: Enable verbose output

    Returns
    -------
        Final path to use for the YAML file
    """
    base, _ = os.path.splitext(os.path.abspath(config_path))
    expected_yaml_path = base + ".yaml"

    # Handle .tmp files from sim2stone
    if yaml_path.endswith(".tmp"):
        proper_yaml_path = yaml_path[:-4]  # Remove .tmp extension

        if os.path.exists(proper_yaml_path):
            # There's an existing YAML file, check if they're different
            if _yaml_files_are_different(proper_yaml_path, yaml_path):
                # Files are different, create unique name and warn user
                unique_yaml_path = _generate_unique_yaml_path(proper_yaml_path)
                os.rename(yaml_path, unique_yaml_path)
                yaml_path = unique_yaml_path
                print("⚠️  WARNING: Existing YAML file has different content!")
                print(f"⚠️  Created new file: {yaml_path}")
                print(f"⚠️  Original file unchanged: {proper_yaml_path}")
                print(
                    "⚠️  The data currently loaded in Boulder is the one from the .py file."
                )
                print(
                    "⚠️  Investigate the differences manually, and choose whether to load the"
                )
                print(f"⚠️  python file or the other YAML file {proper_yaml_path}")
            else:
                # Files are the same, use existing file and suggest direct loading
                os.remove(yaml_path)
                yaml_path = proper_yaml_path
                print("⚠️  WARNING: YAML file already exists with identical content!")
                print("⚠️ You could have loaded the YAML file directly.")
                print("⚠️  It will be faster, for the same results. Use:")
                print("⚠️ Bash/Terminal:")
                print(f"⚠️       boulder {os.path.basename(proper_yaml_path)}")
        else:
            # No existing file, just rename temp to proper name
            os.rename(yaml_path, proper_yaml_path)
            yaml_path = proper_yaml_path
            if verbose:
                print(f"[Boulder] Created YAML file: {yaml_path}")

    elif os.path.exists(expected_yaml_path):
        # sim2stone created the file directly, but there's already an existing one
        if _yaml_files_are_different(expected_yaml_path, yaml_path):
            # Files are different, create unique name and warn user
            unique_yaml_path = _generate_unique_yaml_path(expected_yaml_path)

            # Move the newly created file to unique name
            if yaml_path != unique_yaml_path:
                # If yaml_path is the same as expected_yaml_path, we need to be careful
                if yaml_path == expected_yaml_path:
                    # Create a temporary backup of the original
                    # temp_backup = expected_yaml_path + ".orig_backup"  # Unused variable
                    # Read original content first
                    with open(expected_yaml_path, "r", encoding="utf-8") as f:
                        original_content = f.read()
                    # Read new content
                    with open(yaml_path, "r", encoding="utf-8") as f:
                        new_content = f.read()
                    # Write original back
                    with open(expected_yaml_path, "w", encoding="utf-8") as f:
                        f.write(original_content)
                    # Write new content to unique path
                    with open(unique_yaml_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                else:
                    os.rename(yaml_path, unique_yaml_path)

            yaml_path = unique_yaml_path
            print("⚠️  WARNING: Existing YAML file has different content!")
            print(f"⚠️  Created new file: {yaml_path}")
            print(f"⚠️  Original file unchanged: {expected_yaml_path}")
        else:
            # Files are the same, use existing file and suggest direct loading
            yaml_path = expected_yaml_path
            print("⚠️  WARNING: YAML file already exists with identical content!")
            print("⚠️  To avoid unnecessary conversion, load YAML directly:")
            print(f"⚠️  Command: boulder {os.path.basename(expected_yaml_path)}")

    return yaml_path


def convert_py_to_yaml(
    py_input, output_path: Optional[str] = None, verbose: bool = False
) -> str:
    """Convert Python file or content to YAML using sim2stone.

    This function handles the complete conversion process including:
    - Printing conversion message
    - Running sim2stone conversion
    - Handling temporary files
    - Resolving conflicts with existing YAML files

    Args:
        py_input: Either a file path (str) or Python code content (str)
        output_path: Path where to save the YAML file (optional for file input)
        verbose: Enable verbose output

    Returns
    -------
        Path to the final YAML file

    Raises
    ------
        RuntimeError: If conversion fails
        FileNotFoundError: If the Python file doesn't exist
    """
    # Always print the conversion message
    print(
        "🐍 Python file detected: will execute, convert to 🪨 STONE YAML format, then load into Boulder."
    )
    print("----------------------------------------------------------")
    print("")

    # Determine if input is a file path or content
    is_file_path = os.path.exists(py_input) if isinstance(py_input, str) else False
    cleanup_temp_file = False

    if is_file_path:
        # Input is a file path
        py_path = py_input
        config_path_for_conflicts = py_input
    else:
        # Input is Python content - save to temporary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(py_input)
            py_path = temp_file.name
        cleanup_temp_file = True
        config_path_for_conflicts = py_path

    try:
        # Run the conversion
        yaml_path = _run_sim2stone_conversion(py_path, verbose)

        # Handle conflicts and temporary files
        final_yaml_path = _handle_yaml_conflicts(
            yaml_path, config_path_for_conflicts, verbose
        )

        # If output_path is specified and different, move the file
        if output_path and final_yaml_path != output_path:
            import shutil

            shutil.move(final_yaml_path, output_path)
            final_yaml_path = output_path

        if verbose:
            print(f"[Boulder] Conversion complete. Final YAML: {final_yaml_path}")

        return final_yaml_path

    finally:
        # Clean up temporary file if we created one
        if cleanup_temp_file and os.path.exists(py_path):
            os.unlink(py_path)
