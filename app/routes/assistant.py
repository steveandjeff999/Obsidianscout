"""
Routes for the Scout Assistant feature
"""

from flask import Blueprint, render_template, request, jsonify, current_app, abort
from flask_login import login_required, current_user
from app.assistant import get_assistant, get_visualizer
from functools import wraps
import os
import markdown2
from app.utils.team_isolation import filter_users_by_scouting_team
from app.utils.theme_manager import ThemeManager
from app.models import User

HELP_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'help')

def get_help_docs():
    docs = []
    for f in os.listdir(HELP_FOLDER):
        if f.lower().endswith('.md'):
            with open(os.path.join(HELP_FOLDER, f), encoding='utf-8') as file:
                docs.append({
                    'file': f,
                    'title': f.replace('.md', '').replace('_', ' ').replace('-', ' ').title(),
                    'content': file.read()
                })
    return docs

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

bp = Blueprint('assistant', __name__, url_prefix='/assistant')

def admin_required(f):
    """Decorator to require admin role for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.has_role('admin'):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/')
@login_required
def index():
    """Main assistant page"""
    return render_template('assistant/index.html', **get_theme_context())

@bp.route('/config')
@login_required
@admin_required
def config():
    """AI configuration page (admin only)"""
    try:
        from app.utils.ai_helper import get_ai_config
        ai_config = get_ai_config()
    except ImportError:
        ai_config = {
            "endpoint": "https://api.browserai.co/v1/chat/completions",
            "api_key_configured": False,
            "fallback_enabled": True
        }
    
    return render_template('assistant/config.html', ai_config=ai_config, **get_theme_context())

@bp.route('/config', methods=['POST'])
@login_required
@admin_required
def update_config():
    """Update AI configuration (admin only)"""
    if not request.is_json:
        return jsonify({"success": False, "message": "Request must be JSON"}), 400
    
    data = request.get_json()
    
    try:
        from app.utils.ai_helper import set_ai_config
        success = set_ai_config(data)
        
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": "Failed to update configuration"})
    except ImportError:
        return jsonify({"success": False, "message": "AI helper module not available"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@bp.route('/ask', methods=['POST'])
@login_required
def ask_question():
    """API endpoint for asking questions to the assistant"""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    question = data.get('question', '')
    if not question:
        return jsonify({"error": "Question is required"}), 400
    # Log the question for analytics (optional)
    current_app.logger.info(f"Assistant question from {current_user.email}: {question}")
    # Get answer from assistant
    assistant = get_assistant()
    answer = assistant.answer_question(question)
    # Save both user question and assistant reply to chat history
    from app import save_chat_message
    import datetime
    username = current_user.username
    user_msg = {
        'sender': username,
        'recipient': 'assistant',
        'text': question,
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'owner': username
    }
    assistant_msg = {
        'sender': 'assistant',
        'recipient': username,
        'text': answer.get('text', ''),
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'owner': username
    }
    save_chat_message(user_msg)
    save_chat_message(assistant_msg)
    # Include AI config information for admin users
    if current_user.has_role('admin'):
        try:
            from app.utils.ai_helper import get_ai_config
            answer['ai_config'] = get_ai_config()
        except ImportError:
            pass
    return jsonify(answer)

@bp.route('/visualize', methods=['POST'])
@login_required
def generate_visualization():
    """Generate a visualization based on data"""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    data = request.get_json()
    vis_type = data.get('type')
    vis_data = data.get('data')
    
    if not vis_type or not vis_data:
        return jsonify({"error": "Visualization type and data are required"}), 400
    
    # Get visualizer instance and generate the visualization
    visualizer = get_visualizer()
    result = visualizer.generate_visualization(vis_type, vis_data)
    
    return jsonify(result)

@bp.route('/help-search')
@login_required
def help_search():
    docs = get_help_docs()
    return jsonify({'docs': docs})

@bp.route('/clear-context', methods=['POST'])
@login_required
def clear_context():
    """Clear the conversation context/history"""
    from flask import session
    
    if 'assistant_context' in session:
        session.pop('assistant_context')
    
    return jsonify({"success": True, "message": "Conversation context cleared"})

@bp.route('/clear-assistant-history', methods=['POST'])
@login_required
def clear_assistant_history():
    from flask_login import current_user
    username = current_user.username
    from app import load_chat_history
    import os, json
    history = load_chat_history()
    # Remove all assistant messages for this user (old and new format)
    new_history = [msg for msg in history if not (
        (msg.get('recipient') == 'assistant' and msg.get('owner') == username) or
        (msg.get('sender') == 'assistant' and msg.get('recipient') == username and msg.get('owner') == username) or
        (msg.get('recipient') == username and (msg.get('sender') == 'assistant' or msg.get('sender') == username))
    )]
    # Save the filtered history
    from app import CHAT_HISTORY_FILE, CHAT_HISTORY_LOCK
    with CHAT_HISTORY_LOCK:
        with open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_history, f, ensure_ascii=False, indent=2)
    return {'success': True, 'message': 'Assistant history cleared.'}

@bp.route('/chat-users')
@login_required
def chat_users():
    # Use team isolation to only show users from the same scouting team
    users = filter_users_by_scouting_team().with_entities(User.username).all()
    user_list = [u.username for u in users if u.username != current_user.username]
    return jsonify({
        'users': user_list,
        'current_user': current_user.username
    })

@bp.route('/history')
@login_required
def assistant_history():
    from flask_login import current_user
    username = current_user.username
    from app import load_chat_history
    history = load_chat_history()
    filtered = []
    for msg in history:
        if msg.get('recipient') == 'assistant' and msg.get('owner') and msg.get('owner') != username:
            continue
        # Also include messages where recipient is the user and sender is 'assistant' or the user
        if (
            msg.get('recipient') == username and (msg.get('sender') == 'assistant' or msg.get('sender') == username)
        ) or (
            msg.get('recipient') == 'assistant' and msg.get('owner') == username
        ) or (
            msg.get('sender') == 'assistant' and msg.get('recipient') == username and msg.get('owner') == username
        ):
            filtered.append(msg)
    return {'history': filtered}