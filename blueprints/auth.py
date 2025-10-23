# blueprints/auth.py
from flask import Blueprint, request, jsonify, render_template
import datetime
import jwt
import bcrypt
import psycopg2
from db import get_db
from config import Config

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"error": "Missing fields"}), 400

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    with get_db(Config.DB_CONN_STR) as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed.decode()))
            conn.commit()
            return jsonify({"message": "User registered"}), 200
        except psycopg2.IntegrityError:
            return jsonify({"error": "Username already exists"}), 400

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"error": "Missing fields"}), 400

    with get_db(Config.DB_CONN_STR) as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        if not user or not bcrypt.checkpw(password.encode(), user['password'].encode()):
            return jsonify({"error": "Invalid credentials"}), 401

        expiration = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)
        token = jwt.encode({"user_id": user['id'], "exp": expiration}, Config.JWT_SECRET, algorithm="HS256")
        return jsonify({"token": token}), 200