"""Entry point for running the Blocscape application."""
from blocscape.app import run_server

if __name__ == '__main__':
    run_server(debug=False) # debug=True)   # in debug mode errors are sent to the browser not the terminal. 