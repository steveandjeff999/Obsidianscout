from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required
from app.models import User, Team, ScoutingData, Event, Match
from app import db
from app.utils.theme_manager import ThemeManager
import difflib
import re
from datetime import datetime
from sqlalchemy import or_, and_, func, desc
from flask_login import current_user
from fuzzywuzzy import fuzz, process
import re
from difflib import SequenceMatcher
from functools import lru_cache
import time

bp = Blueprint('search', __name__, url_prefix='/search')

# Cache for team data to improve search performance
@lru_cache(maxsize=128)
def get_cached_teams():
    """Get cached team data for search suggestions"""
    try:
        teams = Team.query.limit(200).all()
        return [(team.team_number, team.team_name, team.location) for team in teams]
    except Exception as e:
        current_app.logger.error(f"Error caching teams: {e}")
        return []

@lru_cache(maxsize=64)
def get_cached_users():
    """Get cached user data for search suggestions"""
    try:
        users = User.query.limit(100).all()
        return [(user.username, user.email, getattr(user, 'team_number', None)) for user in users]
    except Exception as e:
        current_app.logger.error(f"Error caching users: {e}")
        return []

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

def fuzzy_match(query, text, threshold=0.6):
    """Check if query fuzzy matches text with given threshold"""
    if not query or not text:
        return False
    
    query = query.lower().strip()
    text = text.lower().strip()
    
    # Exact match
    if query in text:
        return True
    
    # Check similarity ratio
    ratio = SequenceMatcher(None, query, text).ratio()
    return ratio >= threshold

def get_close_matches(query, choices, n=3, cutoff=0.6):
    """Get close matches with spell checking"""
    if not query or not choices:
        return []
    
    # Use difflib for spell checking
    matches = difflib.get_close_matches(query.lower(), 
                                      [choice.lower() for choice in choices], 
                                      n=n, cutoff=cutoff)
    
    # Return original case matches
    result = []
    for match in matches:
        for choice in choices:
            if choice.lower() == match:
                result.append(choice)
                break
    
    return result

def extract_team_numbers_from_text(text):
    """Extract team numbers from text like 'team 5454' or 'teams 1234 and 5678'"""
    if not text:
        return []
    
    # Find all sequences of digits that could be team numbers (typically 1-5 digits)
    team_number_pattern = r'\b(\d{1,5})\b'
    matches = re.findall(team_number_pattern, text)
    
    # Convert to integers and filter reasonable team numbers (1-99999)
    team_numbers = []
    for match in matches:
        try:
            num = int(match)
            if 1 <= num <= 99999:  # Reasonable team number range
                team_numbers.append(num)
        except ValueError:
            continue
    
    return team_numbers

def fuzzy_match_teams(query, teams, threshold=60):
    """Use fuzzy matching to find teams that approximately match the query"""
    if not teams or not query:
        return []
    
    # Create a list of team strings for fuzzy matching
    team_strings = []
    team_map = {}
    
    for team in teams:
        # Create searchable strings for each team
        team_str = f"Team {team.team_number} {team.team_name or ''} {team.location or ''}".strip()
        team_strings.append(team_str)
        team_map[team_str] = team
    
    # Use fuzzy matching to find the best matches
    matches = process.extract(query, team_strings, limit=10, scorer=fuzz.partial_ratio)
    
    # Filter by threshold and return teams
    fuzzy_results = []
    for match_text, score in matches:
        if score >= threshold:
            team = team_map[match_text]
            fuzzy_results.append((team, score / 100.0))  # Convert to 0-1 scale
    
    return fuzzy_results

def calculate_search_relevance(query, team, match_type='partial'):
    """Calculate relevance score for a team based on the query"""
    query_lower = query.lower().strip()
    team_name_lower = (team.team_name or '').lower()
    team_location_lower = (team.location or '').lower()
    team_number_str = str(team.team_number)
    
    # Base relevance scores
    if match_type == 'exact_number':
        return 1.0
    elif match_type == 'exact_name':
        return 0.95
    elif match_type == 'partial_number':
        return 0.9
    elif match_type == 'partial_name':
        return 0.8
    elif match_type == 'location':
        return 0.7
    elif match_type == 'fuzzy':
        # Use fuzzy matching score
        name_score = fuzz.partial_ratio(query_lower, team_name_lower) / 100.0
        number_score = fuzz.partial_ratio(query_lower, team_number_str) / 100.0
        location_score = fuzz.partial_ratio(query_lower, team_location_lower) / 100.0
        return max(name_score, number_score, location_score) * 0.6  # Fuzzy gets lower max score
    else:
        return 0.5

def search_teams(query):
    """Enhanced search teams by number, name, or location with fuzzy matching"""
    results = []
    
    try:
        query_original = query
        query_lower = query.lower().strip()
        
        # Extract potential team numbers from the query
        extracted_numbers = extract_team_numbers_from_text(query)
        
        # Step 1: Exact team number matches (highest priority)
        if extracted_numbers:
            for team_number in extracted_numbers:
                teams_by_exact_number = Team.query.filter(Team.team_number == team_number).all()
                for team in teams_by_exact_number:
                    results.append({
                        'type': 'team',
                        'title': f"Team {team.team_number} - {team.team_name}",
                        'subtitle': team.location or 'No location specified',
                        'url': f'/teams/{team.team_number}/view',
                        'icon': 'fas fa-users',
                        'relevance': calculate_search_relevance(query, team, 'exact_number')
                    })
        
        # Step 2: If query is purely numeric, also do partial number matching
        if query.isdigit():
            teams_by_partial_number = Team.query.filter(
                func.cast(Team.team_number, db.String).ilike(f'%{query}%')
            ).limit(15).all()
            
            added_team_ids = {result['title'].split(' - ')[0].replace('Team ', '') for result in results}
            
            for team in teams_by_partial_number:
                if str(team.team_number) not in added_team_ids:
                    results.append({
                        'type': 'team',
                        'title': f"Team {team.team_number} - {team.team_name}",
                        'subtitle': team.location or 'No location specified',
                        'url': f'/teams/{team.team_number}/view',
                        'icon': 'fas fa-users',
                        'relevance': calculate_search_relevance(query, team, 'partial_number')
                    })
        
        # Step 3: Exact and partial name/location matches
        teams_by_text = Team.query.filter(
            or_(
                Team.team_name.ilike(f'%{query}%'),
                Team.location.ilike(f'%{query}%')
            )
        ).limit(20).all()
        
        added_team_ids = {result['title'].split(' - ')[0].replace('Team ', '') for result in results}
        
        for team in teams_by_text:
            if str(team.team_number) not in added_team_ids:
                # Determine match type for relevance
                match_type = 'partial_name'
                if query_lower == (team.team_name or '').lower():
                    match_type = 'exact_name'
                elif query_lower in (team.location or '').lower():
                    match_type = 'location'
                
                results.append({
                    'type': 'team',
                    'title': f"Team {team.team_number} - {team.team_name}",
                    'subtitle': team.location or 'No location specified',
                    'url': f'/teams/{team.team_number}/view',
                    'icon': 'fas fa-users',
                    'relevance': calculate_search_relevance(query, team, match_type)
                })
        
        # Step 4: Fuzzy matching for spelling errors (if we don't have many results)
        if len(results) < 5:
            # Get all teams for fuzzy matching (limit to reasonable number)
            all_teams = Team.query.limit(500).all()
            fuzzy_matches = fuzzy_match_teams(query_original, all_teams, threshold=50)
            
            added_team_ids = {result['title'].split(' - ')[0].replace('Team ', '') for result in results}
            
            for team, fuzzy_score in fuzzy_matches:
                if str(team.team_number) not in added_team_ids:
                    results.append({
                        'type': 'team',
                        'title': f"Team {team.team_number} - {team.team_name}",
                        'subtitle': f"{team.location or 'No location specified'} (fuzzy match)",
                        'url': f'/teams/{team.team_number}/view',
                        'icon': 'fas fa-users',
                        'relevance': fuzzy_score * 0.6  # Lower relevance for fuzzy matches
                    })
        
        # Step 5: Handle special cases like "team 5454" where user types "team" prefix
        if 'team' in query_lower and extracted_numbers:
            # We already handled this in step 1, but let's boost relevance
            for result in results:
                if any(str(num) in result['title'] for num in extracted_numbers):
                    result['relevance'] = min(1.0, result['relevance'] + 0.1)
    
    except Exception as e:
        current_app.logger.error(f"Error in enhanced team search: {e}")
    
    # Sort by relevance and limit results
    results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
    return results[:15]  # Limit to 15 results

def search_users(query):
    """Enhanced search users by username or email with fuzzy matching"""
    results = []
    
    try:
        query_lower = query.lower().strip()
        
        # Step 1: Exact matches (highest priority)
        exact_users = User.query.filter(
            or_(
                func.lower(User.username) == query_lower,
                func.lower(User.email) == query_lower
            )
        ).all()
        
        for user in exact_users:
            results.append({
                'type': 'user',
                'title': user.username,
                'subtitle': user.email or 'No email',
                'url': f'/auth/users/{user.id}',
                'icon': 'fas fa-user',
                'relevance': 1.0
            })
        
        # Step 2: Partial matches
        partial_users = User.query.filter(
            or_(
                User.username.ilike(f'%{query}%'),
                User.email.ilike(f'%{query}%')
            )
        ).limit(10).all()
        
        added_user_ids = {result['title'] for result in results}
        
        for user in partial_users:
            if user.username not in added_user_ids:
                results.append({
                    'type': 'user',
                    'title': user.username,
                    'subtitle': user.email or 'No email',
                    'url': f'/auth/users/{user.id}',
                    'icon': 'fas fa-user',
                    'relevance': 0.8
                })
        
        # Step 3: Fuzzy matching for spelling errors (if we don't have many results)
        if len(results) < 3:
            all_users = User.query.limit(100).all()  # Limit for performance
            
            for user in all_users:
                if user.username not in added_user_ids:
                    # Check fuzzy match on username
                    username_score = fuzz.partial_ratio(query_lower, user.username.lower()) / 100.0
                    email_score = 0
                    if user.email:
                        email_score = fuzz.partial_ratio(query_lower, user.email.lower()) / 100.0
                    
                    best_score = max(username_score, email_score)
                    
                    if best_score >= 0.6:  # 60% similarity threshold
                        results.append({
                            'type': 'user',
                            'title': user.username,
                            'subtitle': f"{user.email or 'No email'} (fuzzy match)",
                            'url': f'/auth/users/{user.id}',
                            'icon': 'fas fa-user',
                            'relevance': best_score * 0.6  # Lower relevance for fuzzy matches
                        })
                        added_user_ids.add(user.username)
    
    except Exception as e:
        current_app.logger.error(f"Error in enhanced user search: {e}")
    
    # Sort by relevance and limit results
    results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
    return results[:10]

def search_scouting_data(query):
    """Search scouting data by match, team, or scout"""
    results = []
    
    try:
        # Search by joining with Match and Team tables
        scouting_entries = ScoutingData.query\
            .join(Match, ScoutingData.match_id == Match.id)\
            .join(Team, ScoutingData.team_id == Team.id)\
            .filter(
                or_(
                    Match.match_number.ilike(f'%{query}%'),
                    Team.team_number.ilike(f'%{query}%'),
                    Team.team_name.ilike(f'%{query}%'),
                    ScoutingData.scout_name.ilike(f'%{query}%')
                )
            ).limit(15).all()
        
        for entry in scouting_entries:
            results.append({
                'type': 'scouting_data',
                'title': f"Match {entry.match.match_number} - Team {entry.team.team_number}",
                'subtitle': f"Scout: {entry.scout_name or 'Unknown'} | Alliance: {entry.alliance or 'Unknown'}",
                'url': f'/scouting/view/{entry.id}',
                'icon': 'fas fa-clipboard-list',
                'relevance': 0.6
            })
    
    except Exception as e:
        current_app.logger.error(f"Error searching scouting data: {e}")
    
    return results

def search_events(query):
    """Search events by name or code"""
    results = []
    
    try:
        events = Event.query.filter(
            or_(
                Event.name.ilike(f'%{query}%'),
                Event.code.ilike(f'%{query}%')
            )
        ).limit(10).all()
        
        for event in events:
            results.append({
                'type': 'event',
                'title': event.name,
                'subtitle': f"Event Code: {event.code}" + 
                           (f" | {event.start_date}" if hasattr(event, 'start_date') and event.start_date else ""),
                'url': f'/events/{event.id}',
                'icon': 'fas fa-calendar',
                'relevance': 1.0 if event.code.lower() == query.lower() else 0.8
            })
    
    except Exception as e:
        current_app.logger.error(f"Error searching events: {e}")
    
    return results

def search_pages(query):
    """Search for pages/routes within the application"""
    results = []
    query_lower = query.lower()
    
    # Define searchable pages with their metadata
    pages = [
        {
            'title': 'Dashboard',
            'description': 'Main dashboard and overview',
            'url': '/',
            'keywords': ['home', 'dashboard', 'main', 'overview', 'index']
        },
        {
            'title': 'Teams',
            'description': 'View and manage teams',
            'url': '/teams',
            'keywords': ['teams', 'team', 'roster', 'participants']
        },
        {
            'title': 'Scouting',
            'description': 'Create and manage scouting reports',
            'url': '/scouting',
            'keywords': ['scout', 'scouting', 'reports', 'data entry', 'matches']
        },
        {
            'title': 'Events',
            'description': 'View and manage events',
            'url': '/events',
            'keywords': ['events', 'event', 'competitions', 'tournaments']
        },
        {
            'title': 'Graphs & Analytics',
            'description': 'View performance graphs and analytics',
            'url': '/graphs',
            'keywords': ['graphs', 'analytics', 'charts', 'statistics', 'performance', 'analysis']
        },
        {
            'title': 'Matches',
            'description': 'View match information and predictions',
            'url': '/matches',
            'keywords': ['matches', 'match', 'games', 'predictions', 'schedule']
        },
        {
            'title': 'User Management',
            'description': 'Manage users and permissions',
            'url': '/auth/users',
            'keywords': ['users', 'user', 'accounts', 'permissions', 'manage']
        },
        {
            'title': 'Profile',
            'description': 'View and edit your profile',
            'url': '/auth/profile',
            'keywords': ['profile', 'account', 'settings', 'personal']
        },
        {
            'title': 'Search',
            'description': 'Search teams, users, and data',
            'url': '/search',
            'keywords': ['search', 'find', 'lookup']
        },
        {
            'title': 'Admin Settings',
            'description': 'Administrative settings and configuration',
            'url': '/auth/admin/settings',
            'keywords': ['admin', 'settings', 'configuration', 'system']
        }
    ]
    
    try:
        for page in pages:
            # Check if query matches page title, description, or keywords
            title_match = query_lower in page['title'].lower()
            desc_match = query_lower in page['description'].lower()
            keyword_match = any(query_lower in keyword for keyword in page['keywords'])
            exact_keyword_match = query_lower in page['keywords']
            
            if title_match or desc_match or keyword_match:
                # Calculate relevance score
                relevance = 0.0
                if exact_keyword_match:
                    relevance = 1.0  # Exact keyword match
                elif title_match:
                    relevance = 0.9  # Title match
                elif keyword_match:
                    relevance = 0.8  # Partial keyword match
                elif desc_match:
                    relevance = 0.6  # Description match
                
                results.append({
                    'type': 'page',
                    'title': page['title'],
                    'subtitle': page['description'],
                    'url': page['url'],
                    'icon': 'fas fa-file-alt',
                    'relevance': relevance
                })
    
    except Exception as e:
        current_app.logger.error(f"Error searching pages: {e}")
    
    return results

def get_search_suggestions(query, types_filter=None):
    """Get search suggestions based on partial query"""
    suggestions = []
    
    try:
        # Parse types filter
        if types_filter:
            allowed_types = [t.strip() for t in types_filter.split(',')]
        else:
            allowed_types = ['team', 'user']  # Default to teams and users only
        
        all_suggestions = []
        
        # Get team suggestions
        if 'team' in allowed_types:
            teams = Team.query.limit(50).all()
            team_suggestions = [f"Team {team.team_number}" for team in teams] + [team.team_name for team in teams if team.team_name]
            all_suggestions.extend(team_suggestions)
        
        # Get user suggestions
        if 'user' in allowed_types:
            users = User.query.limit(30).all()
            user_suggestions = [user.username for user in users]
            all_suggestions.extend(user_suggestions)
        
        # Get close matches
        suggestions = get_close_matches(query, all_suggestions, n=8, cutoff=0.4)
    
    except Exception as e:
        current_app.logger.error(f"Error getting search suggestions: {e}")
    
    return suggestions

@bp.route('/')
@login_required
def search_page():
    """Main search page"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return render_template('search/index.html', 
                             query='',
                             results=[],
                             suggestions=[],
                             **get_theme_context())
    
    # Perform search
    all_results = []
    
    # Search different categories
    all_results.extend(search_teams(query))
    all_results.extend(search_users(query))
    all_results.extend(search_events(query))
    all_results.extend(search_scouting_data(query))
    all_results.extend(search_pages(query))
    
    # Sort by relevance
    all_results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
    
    # Get suggestions if no exact matches
    suggestions = []
    if len(all_results) < 3:
        suggestions = get_search_suggestions(query)
    
    return render_template('search/index.html',
                         query=query,
                         results=all_results,
                         suggestions=suggestions,
                         **get_theme_context())

@bp.route('/api/suggestions')
@login_required
def api_suggestions():
    """Enhanced API endpoint for search suggestions with fuzzy matching"""
    query = request.args.get('q', '').strip()
    types_filter = request.args.get('types', 'team,user,page')  # Default to teams, users, and pages
    
    if len(query) < 1:  # Allow single character searches for better UX
        return jsonify({'suggestions': []})
    
    suggestions = []
    
    # Parse types filter
    allowed_types = [t.strip() for t in types_filter.split(',')]
    
    # Team suggestions with enhanced fuzzy matching
    if 'team' in allowed_types:
        try:
            query_lower = query.lower().strip()
            extracted_numbers = extract_team_numbers_from_text(query)
            
            # Priority 1: Exact team number matches from extracted numbers
            if extracted_numbers:
                for team_number in extracted_numbers[:3]:  # Limit to 3 extracted numbers
                    exact_team = Team.query.filter(Team.team_number == team_number).first()
                    if exact_team:
                        display_text = f"Team {exact_team.team_number}"
                        if exact_team.team_name:
                            display_text += f" - {exact_team.team_name}"
                        suggestions.append({
                            'text': display_text,
                            'type': 'team',
                            'relevance': 1.0,
                            'subtitle': exact_team.location or 'No location',
                            'team_number': exact_team.team_number,
                            'search_query': str(exact_team.team_number)
                        })
            
            # Priority 2: Direct numeric matches (if query is purely numeric)
            if query.isdigit() and not extracted_numbers:
                exact_team = Team.query.filter(Team.team_number == int(query)).first()
                if exact_team:
                    display_text = f"Team {exact_team.team_number}"
                    if exact_team.team_name:
                        display_text += f" - {exact_team.team_name}"
                    suggestions.append({
                        'text': display_text,
                        'type': 'team',
                        'relevance': 1.0,
                        'subtitle': exact_team.location or 'No location',
                        'team_number': exact_team.team_number,
                        'search_query': str(exact_team.team_number)
                    })
                
                # Partial number matches
                partial_teams = Team.query.filter(
                    func.cast(Team.team_number, db.String).ilike(f'%{query}%')
                ).filter(Team.team_number != int(query)).limit(4).all()
                
                for team in partial_teams:
                    display_text = f"Team {team.team_number}"
                    if team.team_name:
                        display_text += f" - {team.team_name}"
                    suggestions.append({
                        'text': display_text,
                        'type': 'team',
                        'relevance': 0.9,
                        'subtitle': team.location or 'No location',
                        'team_number': team.team_number,
                        'search_query': str(team.team_number)
                    })
            
            # Priority 3: Name and location matches
            text_teams = Team.query.filter(
                or_(
                    Team.team_name.ilike(f'%{query}%'),
                    Team.location.ilike(f'%{query}%')
                )
            ).limit(5).all()
            
            existing_team_numbers = {s.get('team_number') for s in suggestions}
            
            for team in text_teams:
                if team.team_number not in existing_team_numbers:
                    display_text = f"Team {team.team_number}"
                    if team.team_name:
                        display_text += f" - {team.team_name}"
                    
                    # Calculate relevance based on match quality
                    relevance = 0.8
                    if team.team_name and query_lower in team.team_name.lower():
                        relevance = 0.9
                    elif team.team_name and query_lower == team.team_name.lower():
                        relevance = 0.95
                    
                    suggestions.append({
                        'text': display_text,
                        'type': 'team',
                        'relevance': relevance,
                        'subtitle': team.location or 'No location',
                        'team_number': team.team_number,
                        'search_query': str(team.team_number)
                    })
            
            # Priority 4: Fuzzy matching (if we don't have enough suggestions)
            if len([s for s in suggestions if s['type'] == 'team']) < 3:
                all_teams = Team.query.limit(200).all()  # Limit for performance
                fuzzy_matches = fuzzy_match_teams(query, all_teams, threshold=55)
                
                for team, fuzzy_score in fuzzy_matches[:3]:  # Limit fuzzy results
                    if team.team_number not in existing_team_numbers:
                        display_text = f"Team {team.team_number}"
                        if team.team_name:
                            display_text += f" - {team.team_name}"
                        suggestions.append({
                            'text': display_text,
                            'type': 'team',
                            'relevance': fuzzy_score * 0.7,  # Lower relevance for fuzzy
                            'subtitle': f"{team.location or 'No location'} (similar)",
                            'team_number': team.team_number,
                            'search_query': str(team.team_number)
                        })
                        existing_team_numbers.add(team.team_number)
            
        except Exception as e:
            current_app.logger.error(f"Error in team suggestions: {e}")
    
    # User suggestions with fuzzy matching
    if 'user' in allowed_types:
        try:
            query_lower = query.lower().strip()
            
            # Exact matches first
            exact_users = User.query.filter(
                or_(
                    func.lower(User.username) == query_lower,
                    func.lower(User.email) == query_lower
                )
            ).limit(2).all()
            
            for user in exact_users:
                suggestions.append({
                    'text': user.username,
                    'type': 'user',
                    'relevance': 1.0,
                    'subtitle': f"Team {user.team_number}" if hasattr(user, 'team_number') and user.team_number else 'User',
                    'search_query': user.username
                })
            
            # Partial matches
            partial_users = User.query.filter(
                or_(
                    User.username.ilike(f'%{query}%'),
                    User.email.ilike(f'%{query}%')
                )
            ).limit(5).all()
            
            existing_usernames = {s.get('text') for s in suggestions if s.get('type') == 'user'}
            
            for user in partial_users:
                if user.username not in existing_usernames:
                    relevance = 0.9 if user.username.lower().startswith(query_lower) else 0.7
                    suggestions.append({
                        'text': user.username,
                        'type': 'user',
                        'relevance': relevance,
                        'subtitle': f"Team {user.team_number}" if hasattr(user, 'team_number') and user.team_number else 'User',
                        'search_query': user.username
                    })
                    existing_usernames.add(user.username)
            
            # Fuzzy matching for users (if not enough results)
            if len([s for s in suggestions if s['type'] == 'user']) < 2:
                all_users = User.query.limit(50).all()
                
                for user in all_users:
                    if user.username not in existing_usernames:
                        username_score = fuzz.partial_ratio(query_lower, user.username.lower()) / 100.0
                        email_score = 0
                        if user.email:
                            email_score = fuzz.partial_ratio(query_lower, user.email.lower()) / 100.0
                        
                        best_score = max(username_score, email_score)
                        
                        if best_score >= 0.6:  # 60% similarity threshold
                            suggestions.append({
                                'text': user.username,
                                'type': 'user',
                                'relevance': best_score * 0.7,
                                'subtitle': f"Team {user.team_number} (similar)" if hasattr(user, 'team_number') and user.team_number else 'User (similar)',
                                'search_query': user.username
                            })
                            existing_usernames.add(user.username)
                            
                            if len([s for s in suggestions if s['type'] == 'user']) >= 3:
                                break
            
        except Exception as e:
            current_app.logger.error(f"Error in user suggestions: {e}")
    
    # Page suggestions
    if 'page' in allowed_types:
        try:
            page_results = search_pages(query)
            for page in page_results[:3]:  # Limit to top 3 page results
                suggestions.append({
                    'text': page['title'],
                    'type': 'page',
                    'relevance': page['relevance'],
                    'subtitle': page['subtitle'],
                    'search_query': page['title'].lower(),
                    'url': page['url']
                })
        except Exception as e:
            current_app.logger.error(f"Error in page suggestions: {e}")
    
    # Sort by relevance and limit total results
    suggestions.sort(key=lambda x: x.get('relevance', 0), reverse=True)
    
    return jsonify({'suggestions': suggestions[:8]})

@bp.route('/api/quick-search')
@login_required
def api_quick_search():
    """API endpoint for quick search results - teams and users only"""
    query = request.args.get('q', '').strip()
    
    if len(query) < 2:
        return jsonify([])
    
    # Get top results from teams and users only
    results = []
    results.extend(search_teams(query)[:5])
    results.extend(search_users(query)[:3])
    results.extend(search_pages(query)[:3])
    
    # Sort by relevance and limit
    results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
    
    return jsonify(results[:8])
