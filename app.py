from flask import Flask, request, jsonify, render_template, send_from_directory
import os
import re
import json
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from groq import Groq
from flask_cors import CORS

# Initialize Flask app
from flask import session
from uuid import uuid4

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Must come after app = Flask(...)
CORS(app)

conversation_history = {}

# Initialize Groq client
client = Groq(
    api_key="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"  # Replace with your actual Groq API Key
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
        
        return img_base64
    
    return None

def portfolio_present(text):
    """Check if the response contains a portfolio split."""
    return "Recommended Portfolio Split:" in text

# Serve static files (HTML, CSS, JS)
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# API endpoint to get advisor response
@app.route('/api/advisor', methods=['POST'])
def get_advisor_response():
    try:
        data = request.json
        user_input = data.get('message', '')
        
        if not user_input:
            return jsonify({'error': 'No message provided'}), 400
        
        # Manage session ID
        if 'session_id' not in session:
            session['session_id'] = str(uuid4())
        session_id = session['session_id']

        # Initialize conversation history
        if session_id not in conversation_history:
            conversation_history[session_id] = [{"role": "system", "content": system_prompt}]

        # Append current user message
        conversation_history[session_id].append({"role": "user", "content": user_input})

        messages = conversation_history[session_id]

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
        return jsonify({'error': str(e)}), 500


@app.route('/api/reset', methods=['POST'])
def reset_conversation():
    if 'session_id' in session:
        conversation_history.pop(session['session_id'], None)
    return jsonify({'status': 'conversation reset'})


if __name__ == '__main__':
    print("Starting Investment Advisor web server...")
    app.run(debug=True, port=5000)