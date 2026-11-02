"""Python to YAML conversion utilities using sim2stone."""

import os
import tempfile
from typing import Optional

import yaml

# sim2stone only accepts a .yaml/.yml output path, so the temporary name keeps it.
_TEMP_SUFFIX = ".tmp.yaml"


def _run_sim2stone_conversion(py_path: str, verbose: bool = False) -> str:
    """Run sim2stone conversion on a Python file.

    The result is written to a temporary ``<name>.tmp.yaml`` beside the
    script, never straight to ``<name>.yaml``: an existing (possibly
    hand-edited) YAML must survive until it has been compared with the new one.

    Args:
        py_path: Path to the Python file
        verbose: Enable verbose output

    Returns
    -------
        Path to the temporary YAML file

    Raises
    ------
        RuntimeError: If conversion fails
    """
    from ..sim2stone_cli import main as sim2stone_main

    base, _ = os.path.splitext(os.path.abspath(py_path))
    temp_yaml_path = base + _TEMP_SUFFIX

    args = [py_path, "-o", temp_yaml_path]
    if verbose:
        args.append("--verbose")

    exit_code = sim2stone_main(args)
    if exit_code != 0:
        raise RuntimeError(f"sim2stone conversion failed with exit code {exit_code}")

    if not os.path.exists(temp_yaml_path):
        raise RuntimeError(f"Expected YAML file was not created: {temp_yaml_path}")
    return temp_yaml_path


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
    with open(yaml_path1, "r", encoding="utf-8") as f1:
        content1 = yaml.safe_load(f1)
    with open(yaml_path2, "r", encoding="utf-8") as f2:
        content2 = yaml.safe_load(f2)

    return content1 != content2


def _handle_yaml_conflicts(yaml_path: str, verbose: bool = False) -> str:
    """Settle the temporary YAML written by sim2stone against an existing one.

    Args:
        yaml_path: Path to the newly generated temporary YAML (``<name>.tmp.yaml``)
        verbose: Enable verbose output

    Returns
    -------
        Final path to use for the YAML file. An existing YAML with different
        content is never modified: the new conversion goes to a ``_converted``
        file instead.
    """
    proper_yaml_path = yaml_path[: -len(_TEMP_SUFFIX)] + ".yaml"

    try:
        if not os.path.exists(proper_yaml_path):
            os.rename(yaml_path, proper_yaml_path)
            if verbose:
                print(f"[Boulder] Created YAML file: {proper_yaml_path}")
            return proper_yaml_path

        try:
            different = _yaml_files_are_different(proper_yaml_path, yaml_path)
        except yaml.YAMLError:
            # A broken hand-edited YAML counts as different: keep it, write a new file.
            different = True
        if different:
            unique_yaml_path = _generate_unique_yaml_path(proper_yaml_path)
            os.rename(yaml_path, unique_yaml_path)
            print("⚠️  WARNING: Existing YAML file has different content!")
            print(f"⚠️  Created new file: {unique_yaml_path}")
            print(f"⚠️  Original file unchanged: {proper_yaml_path}")
            print(
                "⚠️  The data currently loaded in Boulder is the one from the .py file."
            )
            print(
                "⚠️  Investigate the differences manually, and choose whether to load the"
            )
            print(f"⚠️  python file or the other YAML file {proper_yaml_path}")
            return unique_yaml_path

        print("⚠️  WARNING: YAML file already exists with identical content!")
        print("⚠️ You could have loaded the YAML file directly.")
        print("⚠️  It will be faster, for the same results. Use:")
        print("⚠️ Bash/Terminal:")
        print(f"⚠️       boulder {os.path.basename(proper_yaml_path)}")
        return proper_yaml_path
    finally:
        # No-op after a rename; removes the temp file on identical content or error.
        if os.path.exists(yaml_path):
            os.remove(yaml_path)


def convert_py_to_yaml(
    py_input, output_path: Optional[str] = None, verbose: bool = False
) -> str:
    """Convert Python file or content to YAML using sim2stone.

    This function handles the complete conversion process including:
    - Printing conversion message
    - Running sim2stone conversion
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
    else:
        # Input is Python content - save to temporary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(py_input)
            py_path = temp_file.name
        cleanup_temp_file = True

    try:
        # Run the conversion
        yaml_path = _run_sim2stone_conversion(py_path, verbose)

        existing_yaml = yaml_path[: -len(_TEMP_SUFFIX)] + ".yaml"
        if not os.path.exists(existing_yaml):
            existing_yaml = None

        # Settle the temporary file against any existing YAML
        final_yaml_path = _handle_yaml_conflicts(yaml_path, verbose)

        # If output_path is specified and different, move the file
        if output_path and final_yaml_path != output_path:
            import shutil

            # Never move the user's own existing YAML away: copy it.
            if final_yaml_path == existing_yaml:
                shutil.copyfile(final_yaml_path, output_path)
            else:
                shutil.move(final_yaml_path, output_path)
            final_yaml_path = output_path

        if verbose:
            print(f"[Boulder] Conversion complete. Final YAML: {final_yaml_path}")

        return final_yaml_path

    finally:
        # Clean up temporary file if we created one
        if cleanup_temp_file and os.path.exists(py_path):
            os.unlink(py_path)
