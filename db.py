# db.py
import psycopg2
import psycopg2.extras
import bcrypt

def get_db(conn_str):
    return psycopg2.connect(conn_str)

def init_db(conn_str):
    with get_db(conn_str) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                password TEXT
            );
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                filename TEXT,
                upload_date TEXT,
                analysis TEXT,
                signature TEXT,
                signed_date TEXT
            );
        """)
        conn.commit()

        # Add dummy users if they don't exist
        dummy_users = [
            ('dummyuser1', 'dummypass1'),
            ('dummyuser2', 'dummypass2'),
            ('dummyuser3', 'dummypass3'),
        ]
        for username, password in dummy_users:
            cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
            if cur.fetchone() is None:
                hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed))
                conn.commit()