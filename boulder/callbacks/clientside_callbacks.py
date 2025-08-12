"""Client-side JavaScript callbacks."""

from dash import Input, Output


def register_callbacks(app) -> None:  # type: ignore
    """Register client-side callbacks."""
    # Keyboard shortcut for Ctrl+Enter
    app.clientside_callback(
        """
        function(n_intervals) {
            if (window._boulder_keyboard_shortcut) return window.dash_clientside.no_update;
            window._boulder_keyboard_shortcut = true;
            document.addEventListener('keydown', function(e) {
                if (e.ctrlKey && e.key === 'Enter') {
                    // Check if Add Reactor modal is open and MFC modal is not
                    var addReactorModal = document.getElementById('add-reactor-modal');
                    var addMFCModal = document.getElementById('add-mfc-modal');
                    if (
                        addReactorModal &&
                        addReactorModal.classList.contains('show') &&
                        (!addMFCModal || !addMFCModal.classList.contains('show'))
                    ) {
                        var btn = document.getElementById('add-reactor');
                        if (btn && !btn.disabled) btn.click();
                    } else {
                        var runBtn = document.getElementById('run-simulation');
                        if (runBtn && !runBtn.disabled) runBtn.click();
                    }
                }
            });
            return window.dash_clientside.no_update;
        }
        """,
        Output("keyboard-trigger", "data"),
        Input("reactor-graph", "id"),
        prevent_initial_call=False,
    )

    # Immediately show simulation overlay on click (no server roundtrip)
    app.clientside_callback(
        """
        function(n_clicks) {
            if (!n_clicks) return window.dash_clientside.no_update;
            try {
                var overlay = document.getElementById('simulation-overlay');
                if (overlay) {
                    overlay.style.display = 'block';
                    overlay.style.position = 'fixed';
                    overlay.style.inset = 0;
                    overlay.style.zIndex = 2000;
                    overlay.style.pointerEvents = 'none';
                }
            } catch (e) {}
            return true;
        }
        """,
        Output("simulation-running", "data", allow_duplicate=True),
        Input("run-simulation", "n_clicks"),
        prevent_initial_call=True,
    )

    # Hide overlay promptly when simulation-running becomes false
    app.clientside_callback(
        """
        function(is_running) {
            var overlay = document.getElementById('simulation-overlay');
            if (!overlay) return window.dash_clientside.no_update;
            overlay.style.display = is_running ? 'block' : 'none';
            return window.dash_clientside.no_update;
        }
        """,
        Output("keyboard-trigger", "data", allow_duplicate=True),
        Input("simulation-running", "data"),
        prevent_initial_call=True,
    )
