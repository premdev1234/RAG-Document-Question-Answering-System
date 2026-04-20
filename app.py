"""
app.py — Flask web server for the RAG application (v2 — production)
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any

try:
    from flask import Flask, request, jsonify, render_template  # type: ignore
except ImportError:
    raise ImportError("Flask is required. Run 'pip install flask'.")

from werkzeug.utils import secure_filename
from rag_pipeline import RAGPipeline

# ── Configuration ──
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "txt"}

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

log.info("Initialising RAG pipeline …")
pipeline = RAGPipeline()
log.info("RAG pipeline ready.")


# ── Routes ──
@app.route("/history", methods=["GET"])
def get_history():
    return jsonify({"history": pipeline.chat_history})


@app.route("/clear-history", methods=["POST"])
def clear_history():
    pipeline.chat_history.clear()
    return jsonify({"success": True})


def _err(message: str, status: int = 400):
    return jsonify({"success": False, "error": message}), status


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files or all(f.filename == "" for f in files):
        return _err("No files selected.")

    results, errors = [], []
    for file in files:
        filename = str(file.filename or "")
        if not filename or "." not in filename:
            continue
        ext = filename.rsplit(".", 1)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"Skipped '{file.filename}': Unsupported type.")
            continue

        path = UPLOAD_DIR / secure_filename(filename)
        file.save(path)
        try:
            results.append(pipeline.ingest_file(str(path)))
        except Exception as e:
            errors.append(f"Error '{filename}': {str(e)}")

    return jsonify(
        {
            "success": True,
            "processed": results,
            "errors": errors,
            "total": pipeline.store.size,
        }
    )


@app.route("/ingest-url", methods=["POST"])
def ingest_url():
    data: Dict[str, Any] = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    if not url:
        return _err("No URL.")
    try:
        return jsonify({"success": True, **pipeline.ingest_url(url)})
    except Exception as e:
        return _err(str(e))


@app.route("/ask", methods=["POST"])
def ask():
    data: Dict[str, Any] = request.get_json(silent=True) or {}
    question = str(data.get("question") or "").strip()
    if not question:
        return _err("Empty question.")
    try:
        top_k = int(data.get("top_k", 3))
        return jsonify({"success": True, **pipeline.answer(question, top_k=top_k)})
    except Exception as e:
        return _err(str(e), 503)


@app.route("/status", methods=["GET"])
def status():
    return jsonify(
        {"indexed": pipeline.store.size, "sources": pipeline.processed_sources}
    )


@app.route("/reset", methods=["POST"])
def reset():
    pipeline.reset()
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
