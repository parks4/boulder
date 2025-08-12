"""Launch Boulder from Python (as in run.py)."""

from boulder.app import run_server

if __name__ == "__main__":
    run_server(debug=True)
