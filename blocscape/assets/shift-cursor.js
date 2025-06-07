document.addEventListener('DOMContentLoaded', function() {
    console.log('shift-cursor.js loaded');
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Shift') {
            // Try to find the Cytoscape container by class or id
            let cy = document.querySelector('#reactor-graph > div') || document.querySelector('.cytoscape-container');
            console.log('Shift down, found cy:', cy);
            if (cy) cy.style.cursor = 'crosshair';
        }
    });
    document.addEventListener('keyup', function(e) {
        if (e.key === 'Shift') {
            let cy = document.querySelector('#reactor-graph > div') || document.querySelector('.cytoscape-container');
            console.log('Shift up, found cy:', cy);
            if (cy) cy.style.cursor = 'default';
        }
    });
}); 