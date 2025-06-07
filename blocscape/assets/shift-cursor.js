document.addEventListener('DOMContentLoaded', function() {
    console.log('edgehandles.js loaded');

    // Wait for Cytoscape to be ready
    const checkCytoscape = setInterval(() => {
        if (window.cy) {
            clearInterval(checkCytoscape);
            console.log('Cytoscape found, initializing edgehandles');

            try {
                // Initialize edgehandles
                const eh = window.cy.edgehandles({
                    preview: true,
                    snap: true,
                    snapThreshold: 20,
                    noEdgeEventsInDraw: true,
                    complete: function(sourceNode, targetNode, addedEles) {
                        console.log('Edge created:', sourceNode.id(), '->', targetNode.id());
                        // Trigger the create-edge event
                        window.dispatchEvent(new CustomEvent('create-edge', {
                            detail: {
                                source: sourceNode.id(),
                                target: targetNode.id()
                            }
                        }));
                    }
                });
                console.log('Edgehandles initialized successfully');

                // Enable edgehandles when Shift is pressed
                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Shift') {
                        console.log('Shift pressed, enabling edgehandles');
                        eh.enable();
                    }
                });

                // Disable edgehandles when Shift is released
                document.addEventListener('keyup', function(e) {
                    if (e.key === 'Shift') {
                        console.log('Shift released, disabling edgehandles');
                        eh.disable();
                    }
                });
            } catch (error) {
                console.error('Error initializing edgehandles:', error);
            }
        }
    }, 100);
});
