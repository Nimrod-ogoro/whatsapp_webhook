import os
import json
import requests
import time
import logging
import threading
from flask import Flask, request, jsonify
from persist_queue import SQLiteQueue

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ------------------------------------------------------------------
#  FREE SQLite job queue (persists on disk, zero extra services)
# ------------------------------------------------------------------
JOB_DB = "/tmp/job_queue.db"          # survives container sleeps
q = SQLiteQueue(JOB_DB, auto_commit=True)

HF_SPACE_ASK = "https://nimroddev-rag-space-v2.hf.space/ask"
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "852540791274504")

# ------------------------------------------------------------------
#  WhatsApp reply helper
# ------------------------------------------------------------------
def _send_whatsapp_reply(to: str, body: str) -> None:
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        r.raise_for_status()
        logging.info("📤 WhatsApp reply status: %s  %s", r.status_code, r.text)
    except Exception as e:
        logging.exception("📤 WhatsApp send failed: %s", e)

# ------------------------------------------------------------------
#  background thread (runs inside same free container)
# ------------------------------------------------------------------
def _query_rag(question: str) -> str:
    for attempt in range(3):
        try:
            r = requests.post(HF_SPACE_ASK, json={"question": question}, timeout=60)
            r.raise_for_status()
            return r.json().get("answer", "No answer returned.")
        except Exception as e:
            logging.warning("RAG call %s – %s", attempt, e)
            time.sleep(5)
    return "😞 Our AI is asleep right now, please try later."

def _worker():
    while True:
        job = q.get()                      # blocks until job appears
        try:
            answer = _query_rag(job["question"])
            _send_whatsapp_reply(job["from_number"], answer)
        except Exception as e:
            logging.exception("Job failed: %s", e)

# start single background thread (dies with container)
worker_thread = threading.Thread(target=_worker, daemon=True)
worker_thread.start()

# ------------------------------------------------------------------
#  webhook – returns instantly
# ------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    logging.info("📩 Incoming: %s", data)

    if data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"):
        return jsonify(ok=True), 200

    msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
    text = msg["text"]["body"]
    from_number = msg["from"]

    q.put({"question": text, "from_number": from_number})
    return jsonify(ok=True), 200

@app.route("/", methods=["GET"])
def index():
    return "WhatsApp webhook OK", 200