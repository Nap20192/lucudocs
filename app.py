from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_cors import CORS
import os
import datetime
import jwt
import bcrypt
import psycopg2
import psycopg2.extras
import requests
import pdfplumber
from werkzeug.utils import secure_filename
import time

# config.py and db.py assumed to be as previously defined; adjust if needed
from config import Config
from db import init_db, get_db

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = app.config['SECRET_KEY']
    CORS(app)

    # Initialize database
    init_db(app.config['DB_CONN_STR'])

    # Auth routes
    @app.route('/register', methods=['GET', 'POST'])
    def register_page():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            if not username or not password:
                flash('Missing fields', 'error')
                return redirect(url_for('register_page'))
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
            with get_db(app.config['DB_CONN_STR']) as conn:
                cur = conn.cursor()
                try:
                    cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed.decode()))
                    conn.commit()
                    flash('User registered successfully')
                    return redirect(url_for('login_page'))
                except psycopg2.IntegrityError:
                    flash('Username already exists', 'error')
                    conn.rollback()
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login_page():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            if not username or not password:
                flash('Missing fields', 'error')
                return redirect(url_for('login_page'))
            with get_db(app.config['DB_CONN_STR']) as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cur.fetchone()
                if user and bcrypt.checkpw(password.encode(), user['password'].encode()):
                    session['user_id'] = user['id']
                    flash('Logged in successfully')
                    return redirect(url_for('dashboard'))
                else:
                    flash('Invalid credentials', 'error')
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.pop('user_id', None)
        flash('Logged out successfully')
        return redirect(url_for('index'))

    # Document routes
    @app.route('/upload', methods=['POST'])
    def upload_document():
        if 'user_id' not in session:
            flash('Please log in', 'error')
            return redirect(url_for('login_page'))
        user_id = session['user_id']
        if 'file' not in request.files:
            flash('File required', 'error')
            return redirect(url_for('dashboard'))
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(url_for('dashboard'))
        
        # Retain exact original filename (no sanitization for MVP; use with caution in production)
        filename = file.filename
        path = os.path.join(app.config['UPLOADS_DIR'], filename)
        
        # Handle overwrites by appending timestamp
        base, ext = os.path.splitext(filename)
        counter = 1
        original_path = path
        while os.path.exists(path):
            timestamp = int(time.time())
            filename = f"{base} ({timestamp}){ext}"
            path = os.path.join(app.config['UPLOADS_DIR'], filename)
            counter += 1
        
        file.save(path)
        upload_date = datetime.datetime.now().isoformat()
        with get_db(app.config['DB_CONN_STR']) as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO documents (user_id, filename, upload_date) VALUES (%s, %s, %s)", (user_id, filename, upload_date))
            conn.commit()
        flash(f'Document "{filename}" uploaded successfully')
        return redirect(url_for('dashboard'))

    @app.route('/analyze/<int:doc_id>', methods=['POST'])
    def analyze_document(doc_id):
        if 'user_id' not in session:
            flash('Please log in', 'error')
            return redirect(url_for('login_page'))
        user_id = session['user_id']
        with get_db(app.config['DB_CONN_STR']) as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("SELECT filename FROM documents WHERE id = %s AND user_id = %s", (doc_id, user_id))
            doc = cur.fetchone()
            if not doc:
                flash('Document not found', 'error')
                return redirect(url_for('dashboard'))
        path = os.path.join(app.config['UPLOADS_DIR'], doc['filename'])
        try:
            with pdfplumber.open(path) as pdf:
                text = ' '.join(page.extract_text() or '' for page in pdf.pages)
        except Exception:
            flash('Failed to extract text', 'error')
            return redirect(url_for('dashboard'))
        prompt = f"Summarize this document: {text[:2000]}"
        ollama_req = {"model": "llama3", "prompt": prompt, "stream": False}
        try:
            resp = requests.post(app.config['OLLAMA_ENDPOINT'], json=ollama_req)
            resp.raise_for_status()
            analysis = resp.json().get('response', '')
        except Exception:
            flash('Failed to analyze', 'error')
            return redirect(url_for('dashboard'))
        with get_db(app.config['DB_CONN_STR']) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE documents SET analysis = %s WHERE id = %s", (analysis, doc_id))
            conn.commit()
        flash('Document analyzed successfully')
        return redirect(url_for('dashboard'))

    @app.route('/sign/<int:doc_id>', methods=['POST'])
    def sign_document(doc_id):
        if 'user_id' not in session:
            flash('Please log in', 'error')
            return redirect(url_for('login_page'))
        user_id = session['user_id']
        signature = request.form.get('signature')
        if not signature:
            flash('Signature required', 'error')
            return redirect(url_for('dashboard'))
        with get_db(app.config['DB_CONN_STR']) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM documents WHERE id = %s AND user_id = %s", (doc_id, user_id))
            if cur.fetchone() is None:
                flash('Document not found', 'error')
                return redirect(url_for('dashboard'))
            signed_date = datetime.datetime.now().isoformat()
            cur.execute("UPDATE documents SET signature = %s, signed_date = %s WHERE id = %s", (signature, signed_date, doc_id))
            conn.commit()
        flash('Document signed successfully')
        return redirect(url_for('dashboard'))

    @app.route('/download/<int:doc_id>')
    def download_document(doc_id):
        if 'user_id' not in session:
            flash('Please log in', 'error')
            return redirect(url_for('login_page'))
        user_id = session['user_id']
        with get_db(app.config['DB_CONN_STR']) as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("SELECT filename FROM documents WHERE id = %s AND user_id = %s", (doc_id, user_id))
            doc = cur.fetchone()
            if not doc:
                flash('Document not found', 'error')
                return redirect(url_for('dashboard'))
        path = os.path.join(app.config['UPLOADS_DIR'], doc['filename'])
        return send_file(path, as_attachment=True)

    @app.route('/pdf/<int:doc_id>')
    def serve_pdf(doc_id):
        if 'user_id' not in session:
            flash('Please log in', 'error')
            return redirect(url_for('login_page'))
        user_id = session['user_id']
        with get_db(app.config['DB_CONN_STR']) as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("SELECT filename FROM documents WHERE id = %s AND user_id = %s", (doc_id, user_id))
            doc = cur.fetchone()
            if not doc:
                flash('Document not found', 'error')
                return redirect(url_for('dashboard'))
        path = os.path.join(app.config['UPLOADS_DIR'], doc['filename'])
        return send_file(path, mimetype='application/pdf')

    @app.route('/document/<int:doc_id>')
    def view_document(doc_id):
        if 'user_id' not in session:
            flash('Please log in', 'error')
            return redirect(url_for('login_page'))
        user_id = session['user_id']
        with get_db(app.config['DB_CONN_STR']) as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("""
                SELECT id, filename, upload_date, analysis, signature, signed_date 
                FROM documents WHERE id = %s AND user_id = %s
            """, (doc_id, user_id))
            doc = cur.fetchone()
            if not doc:
                flash('Document not found', 'error')
                return redirect(url_for('dashboard'))
        return render_template('document.html', doc=doc)

    @app.route('/delete/<int:doc_id>', methods=['POST'])
    def delete_document(doc_id):
        if 'user_id' not in session:
            flash('Please log in', 'error')
            return redirect(url_for('login_page'))
        user_id = session['user_id']
        with get_db(app.config['DB_CONN_STR']) as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("SELECT filename FROM documents WHERE id = %s AND user_id = %s", (doc_id, user_id))
            doc = cur.fetchone()
            if not doc:
                flash('Document not found', 'error')
                return redirect(url_for('dashboard'))
            
            # Delete file from disk
            path = os.path.join(app.config['UPLOADS_DIR'], doc['filename'])
            try:
                os.remove(path)
            except OSError:
                pass  # File might not exist or permission issue; continue
            
            # Delete from DB
            cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
            conn.commit()
        
        flash('Document deleted successfully')
        return redirect(url_for('dashboard'))

    @app.route('/dashboard')
    def dashboard():
        if 'user_id' not in session:
            flash('Please log in', 'error')
            return redirect(url_for('login_page'))
        user_id = session['user_id']
        with get_db(app.config['DB_CONN_STR']) as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("SELECT id, filename, upload_date, analysis, signature, signed_date FROM documents WHERE user_id = %s", (user_id,))
            docs = cur.fetchall()
        return render_template('dashboard.html', docs=docs)

    @app.route('/')
    def index():
        return render_template('index.html')

    return app

if __name__ == '__main__':
    app = create_app()
    os.makedirs(app.config['UPLOADS_DIR'], exist_ok=True)
    app.run(debug=True, port=5000)