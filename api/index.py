#!/usr/bin/env python3
import os
import json
import requests
import time
import logging
import threading
from flask import Flask, request, jsonify
from persistqueue import SQLiteQueue

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ------------------------------------------------------------------
#  Thread-safe job queue
# ------------------------------------------------------------------
JOB_DB = "/tmp/job_queue.db"
q = SQLiteQueue(JOB_DB, auto_commit=True, multithreading=True)

# ------------------------------------------------------------------
#  Config ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
# ------------------------------------------------------------------
HF_SPACE_URL = os.getenv("HF_SPACE_URL", "https://NimrodDev-rag-bot.hf.space/whatsapp")
VERIFY_SECRET = os.getenv("WEBHOOK_VERIFY")   # same secret you set in HF Space
WHATSAPP_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "852540791274504")

# ------------------------------------------------------------------
#  WhatsApp reply helper
# ------------------------------------------------------------------
def _send_whatsapp_reply(to: str, body: str) -> None:
    url = f"https://graph.facebook.com/v22.0/852540791274504/messages"
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
        logging.info("📤 WhatsApp reply: %s %s", r.status_code, r.text)
    except Exception as e:
        logging.exception("📤 WhatsApp send failed: %s", e)

# ------------------------------------------------------------------
#  RAG call WITH shared-secret verify field
# ------------------------------------------------------------------
def _query_rag(phone: str, question: str) -> str:
    payload = {
        "from": phone,
        "text": question,
        "verify": VERIFY_SECRET
    }
    for attempt in range(3):
        try:
            r = requests.post(HF_SPACE_URL, json=payload, timeout=90)
            r.raise_for_status()
            return r.json().get("reply", "No reply returned.")
        except Exception as e:
            logging.warning("RAG call attempt %s failed: %s", attempt + 1, e)
            time.sleep(5)
    return "😞 Amina is currently unavailable, please wait for a human agent."

# ------------------------------------------------------------------
#  Background worker
# ------------------------------------------------------------------
def _worker():
    while True:
        job = q.get()
        try:
            answer = _query_rag(job["from_number"], job["question"])
            _send_whatsapp_reply(job["from_number"], answer)
        except Exception as e:
            logging.exception("Job failed: %s", e)

worker_thread = threading.Thread(target=_worker, daemon=True)
worker_thread.start()

# ------------------------------------------------------------------
#  Webhook endpoint (Render)
# ------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    logging.info("📩 Incoming: %s", data)

    if data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"):
        return jsonify(ok=True), 200

    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        text = msg["text"]["body"]
        from_number = msg["from"]

        q.put({"question": text, "from_number": from_number})
        return jsonify(ok=True), 200
    except Exception as e:
        logging.exception("Webhook error: %s", e)
        return jsonify(error=str(e)), 500

@app.route("/", methods=["GET"])
def index():
    return "WhatsApp webhook (Amina-bot) OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
