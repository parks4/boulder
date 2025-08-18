// Console forwarding for debug mode
(function() {
    'use strict';

    // Store original console methods immediately to prevent recursion
    const originalLog = console.log;
    const originalError = console.error;
    const originalWarn = console.warn;
    const originalInfo = console.info;
    const originalDebug = console.debug;

    // Use original console for our own debug messages
    originalLog.call(console, '[DEBUG] Console forwarding script loaded');

    // Function to safely convert arguments to string
    function formatArguments(args) {
        if (!args || args.length === 0) {
            return '';
        }

        return Array.from(args).map(function(arg) {
            if (arg === null) {
                return 'null';
            }
            if (arg === undefined) {
                return 'undefined';
            }
            if (typeof arg === 'string') {
                return arg;
            }
            if (typeof arg === 'number' || typeof arg === 'boolean') {
                return String(arg);
            }
            if (typeof arg === 'function') {
                return '[Function: ' + (arg.name || 'anonymous') + ']';
            }
            if (typeof arg === 'object') {
                try {
                    if (arg instanceof Error) {
                        return arg.name + ': ' + arg.message + (arg.stack ? '\n' + arg.stack : '');
                    }
                    return JSON.stringify(arg, null, 2);
                } catch (e) {
                    return '[Object: ' + Object.prototype.toString.call(arg) + ']';
                }
            }
            return String(arg);
        }).join(' ');
    }

    // Function to forward console messages to server
    function forwardToServer(level, args, url, line) {
        const message = formatArguments(args);

        // Don't forward empty messages or our own debug messages to prevent recursion
        if (!message || message.includes('[DEBUG]') || message.includes('Console forwarding')) {
            return;
        }

        try {
            fetch('/console_forward', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    level: level,
                    message: message,
                    timestamp: Date.now(),
                    url: url || window.location.href,
                    line: line || ''
                })
            }).catch(function(err) {
                // Use original console to prevent recursion
                originalError.call(console, '[DEBUG] Failed to forward message to server:', err);
            });
        } catch (e) {
            // Use original console to prevent recursion
            originalError.call(console, '[DEBUG] Error in forwardToServer:', e);
        }
    }

    // Override console methods to capture and forward messages
    console.log = function() {
        forwardToServer('log', arguments);
        originalLog.apply(console, arguments);
    };

    console.error = function() {
        forwardToServer('error', arguments);
        originalError.apply(console, arguments);
    };

    console.warn = function() {
        forwardToServer('warn', arguments);
        originalWarn.apply(console, arguments);
    };

    console.info = function() {
        forwardToServer('info', arguments);
        originalInfo.apply(console, arguments);
    };

    console.debug = function() {
        forwardToServer('debug', arguments);
        originalDebug.apply(console, arguments);
    };

    // Capture unhandled errors
    window.addEventListener('error', function(event) {
        const errorMessage = 'Uncaught ' + (event.error ? event.error.toString() : event.message) +
                           ' at ' + event.filename + ':' + event.lineno + ':' + event.colno;
        forwardToServer('error', [errorMessage], event.filename, event.lineno);
    });

    // Capture unhandled promise rejections
    window.addEventListener('unhandledrejection', function(event) {
        const rejectionMessage = 'Unhandled promise rejection: ' + event.reason;
        forwardToServer('error', [rejectionMessage]);
    });

    // Use original console for our own messages to prevent recursion
    originalLog.call(console, '[DEBUG] Console forwarding is now active!');

    // Add a test message that should be forwarded (not containing [DEBUG])
    console.log('Console forwarding test - this should appear in server console');

})();
