// API Keys Management System - Professional Version
console.log('API Keys Management System Loading...');

document.addEventListener('DOMContentLoaded', function() {
    console.log('API Keys page ready - initializing functionality');
    
    // Find elements
    const createForm = document.getElementById('create-key-form');
    const refreshBtn = document.getElementById('refresh-btn');
    
    // Store full API keys for copying
    window.fullApiKeys = new Map();
    
    // Professional showAlert function with enhanced styling
    window.showAlert = function(type, message) {
        const container = document.getElementById('alert-container');
        if (!container) return;
        
        const alertClass = type === 'error' ? 'alert-danger' : `alert-${type}`;
        const alert = document.createElement('div');
        alert.className = `alert ${alertClass} alert-dismissible fade show border-0 shadow-sm`;
        alert.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="fas ${getAlertIcon(type)} me-2"></i>
                <span>${message}</span>
            </div>
            <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
        `;
        container.appendChild(alert);
        
        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            if (alert.parentNode) alert.remove();
        }, 5000);
    };
    
    // Get appropriate icon for alert type
    function getAlertIcon(type) {
        const icons = {
            'success': 'fa-check-circle',
            'info': 'fa-info-circle',
            'warning': 'fa-exclamation-triangle',
            'error': 'fa-times-circle'
        };
        return icons[type] || 'fa-info-circle';
    }

    // Show API key success with full key for copying
    window.showApiKeySuccess = function(keyName, fullKey) {
        const container = document.getElementById('alert-container');
        if (!container) return;
        
        const alert = document.createElement('div');
        alert.className = 'alert alert-success alert-dismissible fade show border-0 shadow-sm';
        alert.innerHTML = `
            <div class="d-flex align-items-start">
                <i class="fas fa-check-circle me-2 mt-1"></i>
                <div class="flex-grow-1">
                    <h6 class="alert-heading mb-2">API Key Created Successfully!</h6>
                    <p class="mb-2">API Key "<strong>${escapeHtml(keyName)}</strong>" has been created.</p>
                    <div class="alert alert-warning alert-sm mb-3">
                        <small><i class="fas fa-exclamation-triangle me-1"></i> This is the only time you'll see the full key. Copy it now!</small>
                    </div>
                    <div class="input-group mb-0">
                        <input type="text" class="form-control font-monospace" value="${escapeHtml(fullKey)}" readonly id="newApiKeyValue">
                        <button class="btn btn-outline-secondary" type="button" onclick="copyNewApiKey()">
                            <i class="fas fa-copy"></i> Copy
                        </button>
                    </div>
                </div>
            </div>
            <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
        `;
        container.appendChild(alert);
        
        // Auto-dismiss after 30 seconds (longer for key copying)
        setTimeout(() => {
            if (alert.parentNode) alert.remove();
        }, 30000);
    };

    // Copy new API key function
    window.copyNewApiKey = function() {
        const input = document.getElementById('newApiKeyValue');
        if (input) {
            input.select();
            input.setSelectionRange(0, 99999);
            navigator.clipboard.writeText(input.value).then(() => {
                showAlert('success', 'Full API key copied to clipboard!');
            }).catch(() => {
                showAlert('error', 'Could not copy to clipboard');
            });
        }
    };
    
    // Form submission
    if (createForm) {
        createForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            console.log('Creating API key...');
            
            const formData = new FormData(createForm);
            const keyName = formData.get('name');
            const rateLimit = formData.get('rate_limit_per_hour') || 1000;
            
            if (!keyName || !keyName.trim()) {
                showAlert('error', 'Please enter an API key name');
                return;
            }
            
            showAlert('info', 'Creating API key...');
            
            try {
                const response = await fetch('/api/keys/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
                    },
                    body: JSON.stringify({
                        name: keyName.trim(),
                        rate_limit_per_hour: parseInt(rateLimit)
                    })
                });
                
                const data = await response.json();
                
                if (response.ok && data.success) {
                    const fullKey = data.api_key.key;
                    
                    // Store the full API key for immediate copying
                    window.fullApiKeys.set(data.api_key.id, fullKey);
                    
                    // Show success with copy button for the new key
                    showApiKeySuccess(keyName, fullKey);
                    createForm.reset();
                    
                    // Refresh the API keys list
                    setTimeout(() => loadApiKeys(), 500);
                } else {
                    showAlert('error', `Failed to create API key: ${data.error || 'Unknown error'}`);
                }
            } catch (error) {
                console.error('Create API key error:', error);
                showAlert('error', `Error creating API key: ${error.message}`);
            }
        });
    }
    
    // Refresh button
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadApiKeys);
    }
    
    // Function to load and display API keys
    async function loadApiKeys() {
        console.log('Loading API keys...');
        const container = document.getElementById('api-keys-container');
        const loadingDiv = document.getElementById('loading-message');
        
        if (!container) {
            console.error('API keys container not found');
            return;
        }
        
        // Show loading
        if (loadingDiv) loadingDiv.style.display = 'block';
        
        try {
            const response = await fetch('/api/keys/', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                console.log('Loaded API keys:', data.api_keys.length);
                displayApiKeys(data.api_keys);
                updateApiKeysBadge(data.active_count);
                
                // Hide loading
                if (loadingDiv) loadingDiv.style.display = 'none';
            } else {
                throw new Error(data.error || 'Failed to load API keys');
            }
        } catch (error) {
            console.error('Load API keys error:', error);
            showAlert('error', `Failed to load API keys: ${error.message}`);
            
            // Hide loading and show error
            if (loadingDiv) {
                loadingDiv.innerHTML = '<p class="text-danger">Failed to load API keys. Please refresh the page.</p>';
            }
        }
    }
    
    // Enhanced function to display API keys in the UI
    function displayApiKeys(apiKeys) {
        const container = document.getElementById('api-keys-container');
        if (!container) return;
        
        if (!apiKeys || apiKeys.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <div class="mb-4">
                        <i class="fas fa-key fa-4x text-muted opacity-50"></i>
                    </div>
                    <h4 class="text-muted mb-3">No API Keys Created</h4>
                    <p class="text-muted mb-4">Get started by creating your first API key using the form above.</p>
                    <div class="row justify-content-center">
                        <div class="col-md-8">
                            <div class="alert alert-info border-0 shadow-sm">
                                <i class="fas fa-lightbulb me-2"></i>
                                <strong>Tip:</strong> API keys allow external applications to securely access your scouting data.
                            </div>
                        </div>
                    </div>
                </div>
            `;
            return;
        }
        
        let html = '<div class="row">';
        apiKeys.forEach(key => {
            const statusBadge = key.is_active 
                ? '<span class="badge bg-success fs-6"><i class="fas fa-check-circle me-1"></i>Active</span>'
                : '<span class="badge bg-secondary fs-6"><i class="fas fa-pause-circle me-1"></i>Inactive</span>';
            
            const lastUsed = key.last_used_at 
                ? new Date(key.last_used_at).toLocaleString()
                : 'Never used';
            
            const created = new Date(key.created_at).toLocaleString();
            
            html += `
                <div class="col-12 mb-4">
                    <div class="card border-0 shadow-sm">
                        <div class="card-header bg-gradient bg-light border-bottom-0">
                            <div class="d-flex justify-content-between align-items-center">
                                <h5 class="card-title mb-0 fw-bold">
                                    <i class="fas fa-key text-primary me-2"></i>
                                    ${escapeHtml(key.name)}
                                </h5>
                                ${statusBadge}
                            </div>
                        </div>
                        <div class="card-body">
                            <div class="row">
                                <div class="col-lg-8">
                                    <div class="mb-3 p-3 bg-light rounded">
                                        <label class="form-label fw-bold text-muted mb-2">API Key</label>
                                        <div class="d-flex align-items-center">
                                            <code class="flex-grow-1 bg-white p-2 rounded border">${key.key_prefix}••••••••••••••••••••••••</code>
                                            <button class="btn btn-sm btn-outline-secondary ms-2" onclick="copyApiKey(${key.id})">
                                                <i class="fas fa-copy"></i>
                                            </button>
                                        </div>
                                    </div>
                                    <div class="row text-muted small">
                                        <div class="col-sm-6 mb-2">
                                            <i class="fas fa-user me-1 text-primary"></i> Created by ${escapeHtml(key.created_by)}
                                        </div>
                                        <div class="col-sm-6 mb-2">
                                            <i class="fas fa-calendar me-1 text-primary"></i> ${created}
                                        </div>
                                        <div class="col-sm-6 mb-2">
                                            <i class="fas fa-clock me-1 text-primary"></i> ${lastUsed}
                                        </div>
                                        <div class="col-sm-6 mb-2">
                                            <i class="fas fa-tachometer-alt me-1 text-primary"></i> ${key.rate_limit_per_hour} requests/hour
                                        </div>
                                    </div>
                                </div>
                                <div class="col-lg-4 text-end">
                                    <div class="d-grid gap-2">
                                        <button class="btn btn-outline-info" onclick="viewUsage(${key.id})">
                                            <i class="fas fa-chart-bar me-1"></i> View Usage
                                        </button>
                                        <button class="btn btn-outline-danger" onclick="deactivateKey(${key.id})">
                                            <i class="fas fa-trash me-1"></i> Deactivate
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        
        container.innerHTML = html;
    }
    
    // Function to update the API keys badge
    function updateApiKeysBadge(count) {
        const badge = document.querySelector('.api-keys-count');
        if (badge) {
            badge.textContent = `${count}/5`;
            badge.className = `api-keys-count badge ${count >= 5 ? 'bg-warning' : 'bg-secondary'}`;
        }
    }
    
    // HTML escape function
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // Load API keys when page loads
    loadApiKeys();
    
    // Global functions for button actions
    window.viewUsage = async function(keyId) {
        console.log('Viewing usage for key:', keyId);
        showAlert('info', 'Loading usage statistics...');
        
        try {
            const response = await fetch(`/api/keys/${keyId}/usage`);
            const data = await response.json();
            
            if (response.ok && data.success) {
                const stats = data.summary;
                showAlert('info', `Usage Statistics: ${stats.total_requests} total requests | Last used: ${stats.last_request_at || 'Never'}`);
            } else {
                showAlert('error', `Failed to load usage data: ${data.error || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Usage error:', error);
            showAlert('error', `Error loading usage data: ${error.message}`);
        }
    };
    
    window.deactivateKey = async function(keyId) {
        if (!confirm('Are you sure you want to deactivate this API key? This action cannot be undone and will immediately revoke access.')) {
            return;
        }
        
        console.log('Deactivating key:', keyId);
        showAlert('info', 'Deactivating API key...');
        
        try {
            const response = await fetch(`/api/keys/${keyId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
                }
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                showAlert('success', 'API key has been deactivated successfully');
                loadApiKeys(); // Refresh the list
            } else {
                showAlert('error', `Failed to deactivate API key: ${data.error || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Deactivate error:', error);
            showAlert('error', `Error deactivating API key: ${error.message}`);
        }
    };
    
    window.copyApiKey = function(keyId) {
        const fullKey = window.fullApiKeys.get(keyId);
        
        if (!fullKey) {
            showAlert('warning', 'Full API key is only available right after creation. This shows only the masked version for security.');
            return;
        }
        
        navigator.clipboard.writeText(fullKey).then(() => {
            showAlert('success', 'Full API key copied to clipboard');
        }).catch(() => {
            showAlert('error', 'Could not copy to clipboard');
        });
    };
    
    console.log('API Keys management system initialized successfully');
});

// Global error handler
window.addEventListener('error', function(e) {
    console.error('JavaScript Error:', e.error);
});