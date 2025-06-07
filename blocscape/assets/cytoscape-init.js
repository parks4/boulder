// Wait for document and scripts to load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Document ready, setting up Cytoscape initialization');

    // Track if we've already initialized to prevent loops
    let initialized = false;

    // Function to get the Cytoscape instance from dash_cytoscape
    function getDashCytoscapeInstance() {
        // Method 1: Try to get from DOM
        const cytoscapeDiv = document.getElementById('reactor-graph');
        if (cytoscapeDiv && cytoscapeDiv._cyreg && cytoscapeDiv._cyreg.cy) {
            console.log('Found Cytoscape instance via DOM _cyreg');
            return cytoscapeDiv._cyreg.cy;
        }

        // Method 2: Try to get from _dash-cytoscape namespace
        if (window._dashCytoscape && window._dashCytoscape['reactor-graph']) {
            console.log('Found Cytoscape instance via _dashCytoscape');
            return window._dashCytoscape['reactor-graph'];
        }

        // Method 3: Look for any object that looks like a Cytoscape instance
        for (let key in window) {
            if (key.startsWith('cy') &&
                window[key] &&
                typeof window[key] === 'object' &&
                typeof window[key].add === 'function' &&
                typeof window[key].remove === 'function' &&
                typeof window[key].elements === 'function') {
                console.log('Found potential Cytoscape instance:', key);
                return window[key];
            }
        }

        return null;
    }

    // Function that will keep checking for the Cytoscape instance
    function initCytoscape() {
        if (initialized) {
            return; // Prevent multiple initializations
        }

        console.log('Checking for Cytoscape instance...');
        const cy = getDashCytoscapeInstance();

        if (cy) {
            console.log('Cytoscape instance found, initializing extensions');
            initialized = true;

            // Ensure the edgehandles extension is registered with Cytoscape
            if (typeof cytoscape !== 'undefined' && typeof cytoscapeEdgehandles !== 'undefined') {
                console.log('Registering edgehandles with Cytoscape');
                try {
                    cytoscape.use(cytoscapeEdgehandles);
                } catch (e) {
                    console.log('Registration error (might be already registered):', e.message);
                }
            }

            // Add the edgehandles functionality
            if (typeof cy.edgehandles === 'function') {
                console.log('Initializing edgehandles on instance');

                try {
                    const eh = cy.edgehandles({
                        preview: true,
                        snap: true,
                        snapThreshold: 20,
                        noEdgeEventsInDraw: true,
                        complete: function(sourceNode, targetNode, addedEles) {
                            console.log('Edge created:', sourceNode.id(), '->', targetNode.id());

                            // Dispatch event for Dash to handle
                            document.dispatchEvent(new CustomEvent('edgeCreate', {
                                detail: {
                                    source: sourceNode.id(),
                                    target: targetNode.id()
                                }
                            }));

                            // Add the edge directly to the graph for immediate visual feedback
                            cy.add([{
                                group: 'edges',
                                data: {
                                    id: 'e' + Date.now(), // unique ID
                                    source: sourceNode.id(),
                                    target: targetNode.id()
                                }
                            }]);
                        }
                    });

                    window.eh = eh; // Store globally

                    // Enable edgehandles with keyboard shortcut
                    document.addEventListener('keydown', function(e) {
                        if (e.key === 'Shift') {
                            eh.enable();
                            console.log('Edgehandles enabled');
                        }
                    });

                    document.addEventListener('keyup', function(e) {
                        if (e.key === 'Shift') {
                            eh.disable();
                            console.log('Edgehandles disabled');
                        }
                    });

                    // Initially disable
                    eh.disable();

                    console.log('Edgehandles successfully initialized');
                } catch (error) {
                    console.error('Error initializing edgehandles:', error);
                }
            } else {
                console.error('Edgehandles function not available:', typeof cy.edgehandles);
                console.log('Available methods on cy:', Object.getOwnPropertyNames(cy.__proto__));
            }
        } else {
            console.log('No Cytoscape instance found, will retry');
            // Try again after a delay
            setTimeout(initCytoscape, 1000);
        }
    }

    // Start initialization
    setTimeout(initCytoscape, 1500); // Give enough time for the page to load
});
