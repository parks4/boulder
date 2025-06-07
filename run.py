"""Entry point for running the Blocscape application."""

from blocscape.app import run_server

if __name__ == "__main__":
    run_server(debug=True)  # Enable debug mode to see errors in the browser
