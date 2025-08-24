from flask import Blueprint, render_template_string

bp = Blueprint('test', __name__)

@bp.route('/test/search')
def test_search():
    """Test page for search functionality"""
    return render_template_string('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Simple Search Test</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            padding: 20px;
        }
        
        .search-container {
            position: relative;
            width: 400px;
            margin: 50px auto;
        }
        
        .search-input {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 16px;
        }
        
        .search-input:focus {
            border-color: #007bff;
            outline: none;
        }
        
        .suggestions {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            margin-top: 4px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            display: none;
            z-index: 1000;
        }
        
        .suggestions.show {
            display: block;
        }
        
        .suggestion-item {
            padding: 12px;
            border-bottom: 1px solid #eee;
            cursor: pointer;
        }
        
        .suggestion-item:hover {
            background: #f8f9fa;
        }
        
        .suggestion-item:last-child {
            border-bottom: none;
        }
        
        .suggestion-category {
            padding: 8px 12px;
            background: #f1f3f4;
            font-weight: bold;
            font-size: 12px;
            text-transform: uppercase;
            color: #666;
        }
        
        .loading {
            padding: 20px;
            text-align: center;
            color: #666;
        }
    </style>
</head>
<body>
    <h1>Search Dropdown Test</h1>
    <p>Type in the search box below to test the dropdown functionality:</p>
    
    <div class="search-container">
        <input type="text" class="search-input" id="searchInput" placeholder="Type 'team' or '100' to see suggestions...">
        <div class="suggestions" id="suggestions"></div>
    </div>
    
    <div style="margin-top: 40px;">
        <h3>Test Instructions:</h3>
        <ul>
            <li>Type "team" to see team suggestions</li>
            <li>Type "100" to see team number matches</li>
            <li>Type "admin" to see user suggestions</li>
            <li>Type any 2+ characters to trigger search</li>
        </ul>
        
        <h3>Debug Info:</h3>
        <div id="debug"></div>
    </div>

    <script>
        const searchInput = document.getElementById('searchInput');
        const suggestions = document.getElementById('suggestions');
        const debug = document.getElementById('debug');
        let timeout;

        searchInput.addEventListener('input', function() {
            clearTimeout(timeout);
            const query = this.value.trim();
            
            debug.innerHTML = `Query: "${query}" (length: ${query.length})`;
            
            if (query.length < 2) {
                hideSuggestions();
                return;
            }
            
            showLoading();
            
            timeout = setTimeout(() => {
                fetchSuggestions(query);
            }, 300);
        });
        
        function showLoading() {
            suggestions.innerHTML = '<div class="loading">Searching...</div>';
            suggestions.classList.add('show');
            debug.innerHTML += '<br>Showing loading...';
        }
        
        function fetchSuggestions(query) {
            debug.innerHTML += '<br>Fetching: ' + query;
            
            fetch(`/search/api/suggestions?q=${encodeURIComponent(query)}&types=team,user`)
                .then(response => {
                    debug.innerHTML += '<br>Response status: ' + response.status;
                    return response.json();
                })
                .then(data => {
                    debug.innerHTML += '<br>Data received: ' + JSON.stringify(data);
                    displaySuggestions(data.suggestions || []);
                })
                .catch(error => {
                    debug.innerHTML += '<br>Error: ' + error.message;
                    suggestions.innerHTML = '<div class="suggestion-item">Error fetching suggestions</div>';
                    suggestions.classList.add('show');
                });
        }
        
        function displaySuggestions(suggestionList) {
            debug.innerHTML += '<br>Displaying ' + suggestionList.length + ' suggestions';
            
            if (suggestionList.length === 0) {
                suggestions.innerHTML = '<div class="suggestion-item">No suggestions found</div>';
                suggestions.classList.add('show');
                return;
            }
            
            // Group by type
            const grouped = suggestionList.reduce((acc, suggestion) => {
                const type = suggestion.type || 'other';
                if (!acc[type]) acc[type] = [];
                acc[type].push(suggestion);
                return acc;
            }, {});
            
            let html = '';
            
            // Teams first
            if (grouped.team && grouped.team.length > 0) {
                html += '<div class="suggestion-category">Teams</div>';
                grouped.team.forEach(suggestion => {
                    html += `<div class="suggestion-item" onclick="selectSuggestion('${suggestion.text}')">${suggestion.text}</div>`;
                });
            }
            
            // Users next
            if (grouped.user && grouped.user.length > 0) {
                html += '<div class="suggestion-category">Users</div>';
                grouped.user.forEach(suggestion => {
                    html += `<div class="suggestion-item" onclick="selectSuggestion('${suggestion.text}')">${suggestion.text}</div>`;
                });
            }
            
            suggestions.innerHTML = html;
            suggestions.classList.add('show');
            debug.innerHTML += '<br>Suggestions should be visible now';
        }
        
        function selectSuggestion(text) {
            searchInput.value = text;
            hideSuggestions();
            debug.innerHTML += '<br>Selected: ' + text;
        }
        
        function hideSuggestions() {
            suggestions.classList.remove('show');
        }
        
        // Hide suggestions when clicking outside
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.search-container')) {
                hideSuggestions();
            }
        });
    </script>
</body>
</html>
    ''')
