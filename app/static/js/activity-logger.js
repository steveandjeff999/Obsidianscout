/**
 * Activity Logger - Tracks user actions and keystrokes
 * 
 * This script tracks various user interactions including:
 * - Keystrokes (what keys were pressed)
 * - Button clicks
 * - Form submissions
 * - Page navigation
 */

class ActivityLogger {
    constructor() {
        this.queue = [];
        this.isProcessing = false;
        this.batchSize = 10;
        this.processingInterval = 5000; // Send logs every 5 seconds
        
        // Start the processing loop
        setInterval(() => this.processQueue(), this.processingInterval);
        
        // Current page information
        this.currentPage = window.location.pathname;
        
        // Initialize event listeners
        this.initEventListeners();
    }
    
    initEventListeners() {
        // Track keystrokes
        document.addEventListener('keydown', (e) => {
            // Don't log keys in password fields
            if (e.target.type === 'password') {
                this.logActivity('keystroke', {
                    key: '******',
                    isPassword: true
                }, e.target.id || null, e.target.tagName);
                return;
            }
            
            this.logActivity('keystroke', {
                key: e.key,
                keyCode: e.keyCode,
                ctrl: e.ctrlKey,
                alt: e.altKey,
                shift: e.shiftKey,
                meta: e.metaKey,
                target: e.target.tagName,
                targetId: e.target.id || null,
                targetType: e.target.type || null,
                targetName: e.target.name || null,
                targetValue: e.target.type === 'password' ? '******' : e.target.value
            }, e.target.id || null, e.target.tagName);
        });
        
        // Track mouse clicks
        document.addEventListener('click', (e) => {
            const target = e.target;
            
            // Get text content of the clicked element or its parent if it's empty
            let textContent = target.textContent ? target.textContent.trim().substring(0, 50) : '';
            if (!textContent && target.parentElement) {
                textContent = target.parentElement.textContent ? target.parentElement.textContent.trim().substring(0, 50) : '';
            }
            
            this.logActivity('click', {
                x: e.clientX,
                y: e.clientY,
                target: target.tagName,
                targetId: target.id || null,
                targetClass: target.className || null,
                targetText: textContent,
                isButton: target.tagName === 'BUTTON' || target.tagName === 'A' || 
                         target.parentElement?.tagName === 'BUTTON' || target.parentElement?.tagName === 'A',
            }, target.id || null, target.tagName);
        });
        
        // Track form submissions
        document.addEventListener('submit', (e) => {
            const form = e.target;
            
            // Don't log password values
            const formData = {};
            for (let element of form.elements) {
                if (element.name) {
                    formData[element.name] = element.type === 'password' ? '******' : element.value;
                }
            }
            
            this.logActivity('form_submit', {
                formId: form.id || null,
                formAction: form.action || null,
                formMethod: form.method || null,
                formData: formData
            }, form.id || null, 'FORM');
        });
        
        // Track page navigation
        window.addEventListener('popstate', () => {
            this.currentPage = window.location.pathname;
            this.logActivity('navigation', {
                from: this.currentPage,
                to: window.location.pathname,
                title: document.title
            });
            this.currentPage = window.location.pathname;
        });
    }
    
    logActivity(actionType, data = {}, elementId = null, elementType = null) {
        // Add standard metadata
        const logEntry = {
            actionType,
            timestamp: new Date().toISOString(),
            page: this.currentPage,
            elementId,
            elementType,
            data,
            userAgent: navigator.userAgent
        };
        
        this.queue.push(logEntry);
        
        // Process queue immediately if it's reached the batch size
        if (this.queue.length >= this.batchSize) {
            this.processQueue();
        }
    }
    
    async processQueue() {
        if (this.isProcessing || this.queue.length === 0) {
            return;
        }
        
        console.log(`Activity logger: Processing ${Math.min(this.queue.length, this.batchSize)} items`);
        this.isProcessing = true;
        
        // Take items from the queue up to batch size
        const batch = this.queue.splice(0, this.batchSize);
        
        try {
            // Get CSRF token if available (from meta tag)
            let csrfToken = '';
            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            if (csrfMeta) {
                csrfToken = csrfMeta.getAttribute('content');
            }
            
            const headers = {
                'Content-Type': 'application/json',
            };
            
            // Add CSRF token if available
            if (csrfToken) {
                headers['X-CSRFToken'] = csrfToken;
            }
            
            console.log('Sending activity logs to server');
            const response = await fetch('/activity/log_activity', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ logs: batch }),
                credentials: 'same-origin'
            });
            
            if (!response.ok) {
                // If submission fails, add the items back to the queue
                this.queue = [...batch, ...this.queue];
                console.error('Failed to submit activity logs', response.status, response.statusText);
            } else {
                const result = await response.json();
                console.log(`Activity logger: Successfully logged ${result.logged_entries} entries`);
            }
        } catch (error) {
            // If submission fails, add the items back to the queue
            this.queue = [...batch, ...this.queue];
            console.error('Error submitting activity logs:', error);
        } finally {
            this.isProcessing = false;
        }
    }
}

// Initialize the logger when the document is loaded
document.addEventListener('DOMContentLoaded', () => {
    try {
        window.activityLogger = new ActivityLogger();
        console.log('Activity logger initialized');
        
        // Log initial page load
        window.activityLogger.logActivity('page_load', {
            url: window.location.href,
            title: document.title,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to initialize activity logger:', error);
    }
});
