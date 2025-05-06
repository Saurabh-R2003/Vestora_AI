from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from datetime import datetime, timedelta
import os
import re
import json
import uuid
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from groq import Groq
from flask_cors import CORS
import secrets


# Initialize Flask app
app = Flask(__name__, static_folder='static')
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
CORS(app)


conversation_history = {}
users = {}
chats = {} 

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = '/login.html'

# OAuth config
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id='841946854683-t28sfb0s2b15vqkgsn88rd99vf22ohft.apps.googleusercontent.com',
    client_secret='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',
    access_token_url='https://oauth2.googleapis.com/token',
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    client_kwargs={'scope': 'openid email profile'},
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
)


class User(UserMixin):
    def __init__(self, id_, name=None, email=None, picture=None):
        self.id = id_
        self.name = name
        self.email = email
        self.picture = picture

# Initialize Groq client
client = Groq(
    api_key="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"
)

# System Prompt for Investment Advisor
system_prompt = """
You are a professional Investment Advisor AI named Vestora.

- ONLY answer exactly what the user has asked.
- DO NOT assume or imagine new situations unless explicitly asked.
- If the user asks a DEFINITION or CONCEPTUAL question (e.g., 'What is grey market price?'), ONLY explain the concept clearly. DO NOT give portfolio advice unless the user explicitly requests it.
- If the user asks for FUNDS, suggest only relevant funds.
- If the user asks for PORTFOLIO SPLIT, provide a clear and detailed split.
- If the user asks for RETURNS, provide estimated returns.

Always:
- Be direct, clear, and professional.
- Keep answers tightly focused.
- Avoid repetition or adding extra information.

Portfolio format (only if requested):

Recommended Portfolio Split:
- Equity Funds: xx% (Large Cap: xx%, Mid Cap: xx%, Small Cap: xx%)
- Debt Funds: xx% (Type: e.g., Short-term Bonds, Gilt Funds)
- Gold: xx% (Gold ETFs)
- (Optional) Real Estate: xx% (REITs)

If giving projections, mention that they are not guaranteed. But make it a small disclaimer(1 line).

Stay professional and focused at all times.
"""

def generate_pie_chart_base64(portfolio_text):
    """Generate a pie chart from portfolio text and return as base64 string."""
    categories = []
    percentages = []

    lines = portfolio_text.split('\n')
    for line in lines:
        match = re.match(r"- (.+?): (\d+)%", line.strip())
        if match:
            category = match.group(1)
            percent = int(match.group(2))
            categories.append(category)
            percentages.append(percent)

    if categories and percentages:
        plt.figure(figsize=(6, 6))
        plt.pie(percentages, labels=categories, autopct='%1.1f%%', startangle=140)
        plt.title('Investment Portfolio Split')
        plt.axis('equal')
        
        # Save to BytesIO object
        buffer = BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        
        # Convert to base64
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        plt.close()
        
        # return img_base64
    
    return None

def portfolio_present(text):
    """Check if the response contains a portfolio split."""
    return "Recommended Portfolio Split:" in text

# User loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

# Serve static files
@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/')
def index():
    print(f"[DEBUG] Authenticated: {current_user.is_authenticated}, User: {getattr(current_user, 'email', None)}")
    if current_user.is_authenticated:
        return send_from_directory('.', 'index.html')
    return redirect('/login.html')


@app.route('/login.html')
def login_page():
    if current_user.is_authenticated:
        return redirect('/')
    return send_from_directory('.', 'login.html')

@app.route('/login')
def login():
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    redirect_uri = url_for('authorize', _external=True, _scheme="https")
    return google.authorize_redirect(redirect_uri, nonce=nonce)

@app.route('/authorize')
def authorize():
    try:
        token = google.authorize_access_token()
        nonce = session.get('nonce')
        userinfo = google.parse_id_token(token, nonce=nonce)
        
        session.pop('nonce', None)  # Clean up the nonce from session
        
        if userinfo:
            user_id = userinfo.get('sub')
            name = userinfo.get('name', '')
            email = userinfo.get('email', '')
            picture = userinfo.get('picture', '')
            
            # Create or update user in our storage
            if user_id not in users:
                users[user_id] = User(user_id, name, email, picture)
            
            # Login the user
            login_user(users[user_id])
            
            # Initialize user's chat storage if not exists
            if user_id not in chats:
                chats[user_id] = {}
            
            return redirect('/')
    except Exception as e:
        app.logger.error(f"OAuth error: {str(e)}")
        return redirect('/login.html')
    
    return redirect('/login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login.html')

# API endpoint to check login status
@app.route('/api/user/status')
def check_login_status():
    if current_user.is_authenticated:
        return jsonify({
            'logged_in': True,
            'user': {
                'id': current_user.id,
                'name': current_user.name,
                'email': current_user.email,
                'picture': current_user.picture
            }
        })
    return jsonify({'logged_in': False})

# Chat management APIs
@app.route('/api/chats', methods=['GET'])
@login_required
def get_chats():
    user_chats = chats.get(current_user.id, {})
    
    # Filter by last 7 days
    one_week_ago = datetime.now() - timedelta(days=7)
    recent_chats = []
    
    for chat_id, chat in user_chats.items():
        if chat.get('timestamp', datetime.now()) >= one_week_ago:
            recent_chats.append({
                'id': chat_id,
                'title': chat.get('title', 'New conversation'),
                'timestamp': chat.get('timestamp', datetime.now()).isoformat()
            })
    
    # Sort by timestamp descending
    recent_chats.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return jsonify({'chats': recent_chats})

@app.route('/api/chats', methods=['POST'])
@login_required
def create_chat():
    chat_id = str(uuid.uuid4())
    
    if current_user.id not in chats:
        chats[current_user.id] = {}
    
    chats[current_user.id][chat_id] = {
        'title': request.json.get('title', 'New conversation'),
        'messages': [],
        'timestamp': datetime.now()
    }
    
    return jsonify({
        'id': chat_id,
        'title': chats[current_user.id][chat_id]['title'],
        'timestamp': chats[current_user.id][chat_id]['timestamp'].isoformat()
    })

@app.route('/api/chats/<chat_id>', methods=['GET'])
@login_required
def get_chat(chat_id):
    user_chats = chats.get(current_user.id, {})
    chat = user_chats.get(chat_id)
    
    if not chat:
        return jsonify({'error': 'Chat not found'}), 404
    
    return jsonify({
        'id': chat_id,
        'title': chat.get('title', 'New conversation'),
        'messages': chat.get('messages', []),
        'timestamp': chat.get('timestamp', datetime.now()).isoformat()
    })

@app.route('/api/chats/<chat_id>', methods=['PATCH'])
@login_required
def update_chat(chat_id):
    user_chats = chats.get(current_user.id, {})
    chat = user_chats.get(chat_id)
    
    if not chat:
        return jsonify({'error': 'Chat not found'}), 404
    
    if 'title' in request.json:
        chat['title'] = request.json['title']
    
    return jsonify({
        'id': chat_id,
        'title': chat['title'],
        'timestamp': chat['timestamp'].isoformat()
    })

@app.route('/api/chats/<chat_id>', methods=['DELETE'])
@login_required
def delete_chat(chat_id):
    user_chats = chats.get(current_user.id, {})
    
    if chat_id in user_chats:
        del user_chats[chat_id]
        return jsonify({'status': 'success'})
    
    return jsonify({'error': 'Chat not found'}), 404

# API endpoint to get advisor response
@app.route('/api/advisor', methods=['POST'])
@login_required
def get_advisor_response():
    try:
        data = request.json
        user_input = data.get('message', '')
        chat_id = data.get('chat_id')
        
        if not user_input:
            return jsonify({'error': 'No message provided'}), 400
        
        if not chat_id or chat_id not in chats.get(current_user.id, {}):
            return jsonify({'error': 'Invalid chat ID'}), 400
        
        user_chat = chats[current_user.id][chat_id]
        
        # Initialize chat if it's new
        if not user_chat.get('messages'):
            user_chat['messages'] = []
            user_chat['context'] = [{"role": "system", "content": system_prompt}]
        
        # Add user message to chat history
        user_chat['messages'].append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        })
        
        # Update the timestamp
        user_chat['timestamp'] = datetime.now()
        
        # Prepare messages for Groq
        messages = user_chat.get('context', []).copy()
        
        # Add user-assistant exchanges
        for msg in user_chat['messages']:
            if msg['role'] in ['user', 'assistant']:
                messages.append({
                    "role": msg['role'],
                    "content": msg['content']
                })
        
        # Get response from Groq
        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=messages,
            temperature=0.5,
            max_tokens=800,
            top_p=0.9,
            stop=["User:", "Advisor:"]
        )

        advisor_output = response.choices[0].message.content
        
        # Add assistant response to chat history
        user_chat['messages'].append({
            "role": "assistant",
            "content": advisor_output,
            "timestamp": datetime.now().isoformat()
        })
        
        # Check if portfolio split is present and generate chart if needed
        chart_image = None
        has_portfolio = portfolio_present(advisor_output)
        if has_portfolio:
            chart_image = generate_pie_chart_base64(advisor_output)
        
        return jsonify({
            'response': advisor_output,
            'has_portfolio': has_portfolio,
            'chart_image': chart_image
        })
        
    except Exception as e:
        app.logger.error(f"Error in advisor API: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset', methods=['POST'])
@login_required
def reset_conversation():
    chat_id = request.json.get('chat_id')
    
    if not chat_id:
        return jsonify({'error': 'No chat ID provided'}), 400
    
    user_chats = chats.get(current_user.id, {})
    
    if chat_id in user_chats:
        user_chats[chat_id]['messages'] = []
        user_chats[chat_id]['context'] = [{"role": "system", "content": system_prompt}]
        return jsonify({'status': 'conversation reset'})
    
    return jsonify({'error': 'Chat not found'}), 404

if __name__ == '__main__':
    print("Starting Investment Advisor web server...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)