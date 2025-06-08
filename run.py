"""Entry point for running the Boulder application."""

from blocscape.app import run_server

if __name__ == "__main__":
    run_server(debug=True)  # Enable debug mode to see errors in the browser


# TODO
# - min/max values for temperature, pressure.
# - check inputs format
# - add graphical option to delete a node (we can already do it through the JSON)
