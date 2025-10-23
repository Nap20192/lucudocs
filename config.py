# config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key'
    DB_CONN_STR = os.environ.get('DB_CONN_STR') or "dbname=lucudocs user=postgres password=1234 host=localhost port=5432"
    UPLOADS_DIR = "./uploads"
    OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
    JWT_SECRET = "your-secret-key"  # Move from app