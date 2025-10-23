# blueprints/documents.py
from flask import Blueprint, request, jsonify, send_file
import datetime
import requests
import pdfplumber
import os
from werkzeug.utils import secure_filename
from utils.auth import auth_required
from db import get_db
from config import Config
import psycopg2
from psycopg2.extras import DictCursor

documents_bp = Blueprint('documents', __name__)

@documents_bp.route('/documents/upload', methods=['POST'])
@auth_required
def upload_document():
    user_id = request.user_id
    if 'file' not in request.files:
        return jsonify({"error": "File required"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    filename = secure_filename(f"{user_id}_{file.filename}")
    path = os.path.join(Config.UPLOADS_DIR, filename)
    file.save(path)

    upload_date = datetime.datetime.now().isoformat()
    with get_db(Config.DB_CONN_STR) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO documents (user_id, filename, upload_date) VALUES (%s, %s, %s)", (user_id, filename, upload_date))
        conn.commit()

    return jsonify({"message": "Document uploaded", "filename": filename}), 200

@documents_bp.route('/documents', methods=['GET'])
@auth_required
def list_documents():
    user_id = request.user_id
    with get_db(Config.DB_CONN_STR) as conn:
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT id, filename, upload_date, analysis, signature, signed_date FROM documents WHERE user_id = %s", (user_id,))
        docs = cur.fetchall()
    return jsonify(docs), 200

@documents_bp.route('/documents/<doc_id>/analyze', methods=['POST'])
@auth_required
def analyze_document(doc_id):
    try:
        doc_id = int(doc_id)
    except ValueError:
        return jsonify({"error": "Invalid document ID"}), 400

    user_id = request.user_id
    with get_db(Config.DB_CONN_STR) as conn:
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT filename FROM documents WHERE id = %s AND user_id = %s", (doc_id, user_id))
        doc = cur.fetchone()
        if not doc:
            return jsonify({"error": "Document not found"}), 404

    path = os.path.join(Config.UPLOADS_DIR, doc['filename'])

    # Extract text from PDF
    try:
        with pdfplumber.open(path) as pdf:
            text = ' '.join(page.extract_text() or '' for page in pdf.pages)
    except Exception as e:
        return jsonify({"error": "Failed to extract text"}), 500

    # Call Ollama
    prompt = f"Summarize this document: {text[:2000]}"
    ollama_req = {"model": "llama3", "prompt": prompt, "stream": False}
    try:
        resp = requests.post(Config.OLLAMA_ENDPOINT, json=ollama_req)
        resp.raise_for_status()
        analysis = resp.json().get('response', '')
    except Exception as e:
        return jsonify({"error": "Failed to analyze"}), 500

    # Update DB
    with get_db(Config.DB_CONN_STR) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE documents SET analysis = %s WHERE id = %s", (analysis, doc_id))
        conn.commit()

    return jsonify({"analysis": analysis}), 200

@documents_bp.route('/documents/<doc_id>/sign', methods=['POST'])
@auth_required
def sign_document(doc_id):
    try:
        doc_id = int(doc_id)
    except ValueError:
        return jsonify({"error": "Invalid document ID"}), 400

    user_id = request.user_id
    data = request.json
    signature = data.get('signature')
    if not signature:
        return jsonify({"error": "Signature required"}), 400

    with get_db(Config.DB_CONN_STR) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM documents WHERE id = %s AND user_id = %s", (doc_id, user_id))
        if cur.fetchone() is None:
            return jsonify({"error": "Document not found"}), 404

        signed_date = datetime.datetime.now().isoformat()
        cur.execute("UPDATE documents SET signature = %s, signed_date = %s WHERE id = %s", (signature, signed_date, doc_id))
        conn.commit()

    return jsonify({"message": "Document signed"}), 200

@documents_bp.route('/documents/<doc_id>/download', methods=['GET'])
@auth_required
def download_document(doc_id):
    try:
        doc_id = int(doc_id)
    except ValueError:
        return jsonify({"error": "Invalid document ID"}), 400

    user_id = request.user_id
    with get_db(Config.DB_CONN_STR) as conn:
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT filename FROM documents WHERE id = %s AND user_id = %s", (doc_id, user_id))
        doc = cur.fetchone()
        if not doc:
            return jsonify({"error": "Document not found"}), 404

    path = os.path.join(Config.UPLOADS_DIR, doc['filename'])
    return send_file(path, as_attachment=True)