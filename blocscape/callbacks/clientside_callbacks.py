"""Client-side JavaScript callbacks."""

from dash import Input, Output


def register_callbacks(app):
    """Register client-side callbacks."""
    
    # Custom edge creation from custom event
    app.clientside_callback(
        """
        function(n_clicks) {
            if (!window.cy) return null;

            // Listen for the create-edge event
            if (!window._edgeListenerAdded) {
                window._edgeListenerAdded = true;
                window.addEventListener('create-edge', function(e) {
                    const { source, target } = e.detail;
                    // Add the edge to Cytoscape
                    window.cy.add({
                        group: 'edges',
                        data: {
                            source: source,
                            target: target,
                            label: 'New Edge'  // You can customize this
                        }
                    });
                });
            }
            return null;
        }
        """,
        Output("reactor-graph", "tapEdgeData"),
        Input("reactor-graph", "tapNode"),
        prevent_initial_call=True,
    )

    # Setup client-side callback to handle edge creation
    app.clientside_callback(
        """
        function(n_clicks) {
            // This is a trigger to create an initial placeholder
            return [];
        }
        """,
        Output("hidden-edge-data", "children"),
        Input("reactor-graph", "id"),
        prevent_initial_call=True,
    )

    # Update the store when an edge is created
    app.clientside_callback(
        """
        function(n_clicks) {
            // Initialize event listener if not done already
            if (!window.edgeEventInitialized) {
                window.edgeEventInitialized = true;

                document.addEventListener('edgeCreate', function(e) {
                    if (e && e.detail) {
                        console.log('Edge creation event received:', e.detail);
                        // Update the store with new edge data
                        window.dash_clientside.no_update = false;
                        return e.detail;
                    }
                    return window.dash_clientside.no_update;
                });
            }

            // Initially return no update
            return window.dash_clientside.no_update;
        }
        """,
        Output("edge-added-store", "data"),
        Input("initialization-trigger", "children"),
        prevent_initial_call=True,
    )

    # Edgehandles setup
    app.clientside_callback(
        """
        function(n_intervals) {
            if (window.edgehandles_setup_complete) {
                return window.dash_clientside.no_update;
            }
            const cy = (
                document.getElementById('reactor-graph') &&
                document.getElementById('reactor-graph')._cyreg &&
                document.getElementById('reactor-graph')._cyreg.cy
            );
            if (!cy || typeof cy.edgehandles !== 'function') {
                console.log("Waiting for Cytoscape and the .edgehandles() function...");
                return window.dash_clientside.no_update;
            }
            // --- One-time setup ---
            window.blocscape_edge_queue = [];
            document.addEventListener('blocscape_edge_created', e => {
                window.blocscape_edge_queue.push(e.detail);
            });
            const eh = cy.edgehandles({
                preview: true, snap: true,
                complete: (sourceNode, targetNode, addedEles) => {
                    document.dispatchEvent(new CustomEvent('blocscape_edge_created', {
                        detail: { source: sourceNode.id(), target: targetNode.id(), ts: Date.now() }
                    }));
                }
            });
            document.addEventListener('keydown', e => { if (e.key === 'Shift') eh.enable(); });
            document.addEventListener('keyup', e => { if (e.key === 'Shift') eh.disable(); });
            eh.disable();
            window.edgehandles_setup_complete = true;
            console.log('Edgehandles initialized.');
            return window.dash_clientside.no_update;
        }
        """,
        Output("init-dummy-output", "children"),
        Input("init-interval", "n_intervals"),
    )

    # Keyboard shortcut for Ctrl+Enter
    app.clientside_callback(
        """
        function(n_intervals) {
            if (window._blocscape_keyboard_shortcut) return window.dash_clientside.no_update;
            window._blocscape_keyboard_shortcut = true;
            document.addEventListener('keydown', function(e) {
                if (e.ctrlKey && e.key === 'Enter') {
                    // Check if Add Reactor modal is open
                    var addReactorModal = document.getElementById('add-reactor-modal');
                    if (addReactorModal && addReactorModal.classList.contains('show')) {
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