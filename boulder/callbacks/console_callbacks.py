"""Console forwarding callbacks for debug mode."""

from datetime import datetime

from flask import request


def register_callbacks(app) -> None:  # type: ignore
    """Register console forwarding callbacks for debug mode.

    This function registers a Flask route that handles console messages forwarded
    from the browser. When debug mode is enabled, browser console messages (logs,
    warnings, errors) are captured by the console_forwarding.js script and sent
    to this endpoint via HTTP POST requests.

    The route processes incoming console messages and formats them for display
    in the server console with:
    - Timestamps in HH:MM:SS.mmm format
    - Source location (URL and line number)
    - Color-coded output based on message level
    - Proper error handling for malformed requests

    Args:
        app: The Dash application instance to register callbacks with

    Route:
        POST /console_forward: Receives JSON data containing console message details
            Expected JSON format:
            {
                "level": "log|error|warn|info|debug",
                "message": "The console message text",
                "timestamp": 1234567890123,  // Unix timestamp in milliseconds
                "url": "http://localhost:8050",  // Source URL
                "line": "42"  // Line number (optional)
            }
    """

    @app.server.route("/console_forward", methods=["POST"])
    def console_forward():
        """Handle console messages forwarded from the browser."""
        try:
            data = request.get_json()
            if not data:
                return {"status": "error", "message": "No JSON data received"}, 400

            level = data.get("level", "log")
            message = data.get("message", "")
            timestamp = data.get("timestamp", 0)
            url = data.get("url", "")
            line = data.get("line", "")

            # Convert timestamp to readable format
            if timestamp:
                dt = datetime.fromtimestamp(timestamp / 1000)
                time_str = dt.strftime("%H:%M:%S.%f")[:-3]
            else:
                time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            # Format the message for server console
            location = f" at {url}"
            if line:
                location += f":{line}"

            formatted_message = (
                f"[BROWSER {level.upper()}] {time_str}{location}: {message}"
            )

            # Print to server console with appropriate level
            if level == "error":
                print(f"\033[91m{formatted_message}\033[0m")  # Red for errors
            elif level == "warn":
                print(f"\033[93m{formatted_message}\033[0m")  # Yellow for warnings
            elif level == "info":
                print(f"\033[94m{formatted_message}\033[0m")  # Blue for info
            elif level == "debug":
                print(f"\033[90m{formatted_message}\033[0m")  # Gray for debug
            else:
                print(formatted_message)  # Default for log

            return {"status": "success"}, 200

        except Exception as e:
            print(f"[CONSOLE FORWARD ERROR] Failed to process console message: {e}")
            return {"status": "error", "message": str(e)}, 500
