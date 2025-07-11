from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import requests
import json
import sqlite3
import datetime
from functools import wraps
import hashlib
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # Generate a secure secret key

# Database setup
def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect('leetcode_tracker.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            leetcode_username TEXT UNIQUE NOT NULL,
            email TEXT,
            college_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Daily stats table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date DATE,
            easy_solved INTEGER DEFAULT 0,
            medium_solved INTEGER DEFAULT 0,
            hard_solved INTEGER DEFAULT 0,
            total_solved INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(user_id, date)
        )
    ''')
    
    conn.commit()
    conn.close()

def fetch_leetcode_stats(username):
    """
    Fetch LeetCode statistics for a given username using alfa-leetcode-api
    Returns a dictionary with problem counts or None if user not found
    """
    url = f"https://alfa-leetcode-api.onrender.com/{username}/solved"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        print(f"API Response: {data}")
        
        if not data:
            print("Empty response from API")
            return None
        
        stats = {
            "easy": data.get('easySolved', 0),
            "medium": data.get('mediumSolved', 0),
            "hard": data.get('hardSolved', 0),
            "total": data.get('solvedProblem', 0)
        }
        
        print(f"Parsed stats: {stats}")
        return stats
        
    except requests.RequestException as e:
        print(f"Request error: {e}")
        return None
    except (KeyError, ValueError) as e:
        print(f"Data parsing error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None

def require_login(f):
    """Decorator to require login for protected routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def save_daily_stats(user_id, stats):
    """Save daily statistics for a user"""
    conn = sqlite3.connect('leetcode_tracker.db')
    cursor = conn.cursor()
    
    today = datetime.date.today()
    
    cursor.execute('''
        INSERT OR REPLACE INTO daily_stats 
        (user_id, date, easy_solved, medium_solved, hard_solved, total_solved)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, today, stats['easy'], stats['medium'], stats['hard'], stats['total']))
    
    conn.commit()
    conn.close()

def get_user_stats_history(user_id, days=30):
    """Get user's statistics history for specified number of days"""
    conn = sqlite3.connect('leetcode_tracker.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT date, easy_solved, medium_solved, hard_solved, total_solved
        FROM daily_stats
        WHERE user_id = ? AND date >= date('now', '-{} days')
        ORDER BY date DESC
    '''.format(days), (user_id,))
    
    results = cursor.fetchall()
    conn.close()
    
    return [
        {
            'date': row[0],
            'easy': row[1],
            'medium': row[2],
            'hard': row[3],
            'total': row[4]
        }
        for row in results
    ]

def get_leaderboard(period='all'):
    """Get leaderboard for specified period"""
    conn = sqlite3.connect('leetcode_tracker.db')
    cursor = conn.cursor()
    
    if period == 'daily':
        cursor.execute('''
            SELECT u.username, u.leetcode_username, ds.total_solved
            FROM users u
            JOIN daily_stats ds ON u.id = ds.user_id
            WHERE ds.date = date('now')
            ORDER BY ds.total_solved DESC
            LIMIT 10
        ''')
    elif period == 'weekly':
        cursor.execute('''
            SELECT u.username, u.leetcode_username, MAX(ds.total_solved) as max_solved
            FROM users u
            JOIN daily_stats ds ON u.id = ds.user_id
            WHERE ds.date >= date('now', '-7 days')
            GROUP BY u.id
            ORDER BY max_solved DESC
            LIMIT 10
        ''')
    else:  # all time
        cursor.execute('''
            SELECT u.username, u.leetcode_username, MAX(ds.total_solved) as max_solved
            FROM users u
            JOIN daily_stats ds ON u.id = ds.user_id
            GROUP BY u.id
            ORDER BY max_solved DESC
            LIMIT 10
        ''')
    
    results = cursor.fetchall()
    conn.close()
    
    return [
        {
            'username': row[0],
            'leetcode_username': row[1],
            'total_solved': row[2]
        }
        for row in results
    ]

@app.route('/')
def index():
    """Main page - redirect to dashboard if logged in, otherwise to login"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login/Register page"""
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username', '').strip()
        leetcode_username = data.get('leetcode_username', '').strip()
        email = data.get('email', '').strip()
        college_id = data.get('college_id', '').strip()
        
        if not username or not leetcode_username:
            return jsonify({"error": "Username and LeetCode username are required"}), 400
        
        # Verify LeetCode username exists
        stats = fetch_leetcode_stats(leetcode_username)
        if stats is None:
            return jsonify({"error": "LeetCode username not found"}), 404
        
        # Check if user exists
        conn = sqlite3.connect('leetcode_tracker.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM users WHERE username = ? OR leetcode_username = ?', 
                      (username, leetcode_username))
        existing_user = cursor.fetchone()
        
        if existing_user:
            # Login existing user
            user_id = existing_user[0]
            session['user_id'] = user_id
            session['username'] = username
            
            # Save current stats
            save_daily_stats(user_id, stats)
            
            conn.close()
            return jsonify({"success": "Login successful"})
        else:
            # Register new user
            cursor.execute('''
                INSERT INTO users (username, leetcode_username, email, college_id)
                VALUES (?, ?, ?, ?)
            ''', (username, leetcode_username, email, college_id))
            
            user_id = cursor.lastrowid
            session['user_id'] = user_id
            session['username'] = username
            
            # Save initial stats
            save_daily_stats(user_id, stats)
            
            conn.commit()
            conn.close()
            return jsonify({"success": "Registration successful"})
    
    return render_template('index.html')

@app.route('/dashboard')
@require_login
def dashboard():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/api/stats')
@require_login
def api_stats():
    """API endpoint to get user's current stats"""
    user_id = session['user_id']
    
    # Get user's LeetCode username
    conn = sqlite3.connect('leetcode_tracker.db')
    cursor = conn.cursor()
    cursor.execute('SELECT leetcode_username FROM users WHERE id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return jsonify({"error": "User not found"}), 404
    
    leetcode_username = result[0]
    
    # Fetch fresh stats
    stats = fetch_leetcode_stats(leetcode_username)
    if stats:
        save_daily_stats(user_id, stats)
    
    # Get history
    history = get_user_stats_history(user_id, 30)
    
    return jsonify({
        "current_stats": stats,
        "history": history
    })

@app.route('/api/leaderboard')
@require_login
def api_leaderboard():
    """API endpoint to get leaderboard"""
    period = request.args.get('period', 'all')
    leaderboard = get_leaderboard(period)
    return jsonify(leaderboard)

@app.route('/api/chart_data')
@require_login
def api_chart_data():
    """API endpoint to get chart data"""
    period = request.args.get('period', 'monthly')
    user_id = session['user_id']
    
    days_map = {
        'daily': 1,
        'weekly': 7,
        'monthly': 30
    }
    
    days = days_map.get(period, 30)
    history = get_user_stats_history(user_id, days)
    
    return jsonify(history)

@app.route('/logout')
def logout():
    """Logout route"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/fetch_stats', methods=['POST'])
def fetch_stats():
    """
    Legacy API endpoint for backward compatibility
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        username = data.get('username', '').strip()
        
        if not username:
            return jsonify({"error": "Username is required"}), 400
        
        print(f"Fetching stats for username: {username}")
        
        stats = fetch_leetcode_stats(username)
        
        if stats is None:
            return jsonify({"error": "User not found or API error"}), 404
        
        return jsonify({
            "username": username,
            "stats": stats
        })
        
    except Exception as e:
        print(f"Flask route error: {e}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)