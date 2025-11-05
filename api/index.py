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
#  Config
# ------------------------------------------------------------------
HF_SPACE_URL   = os.getenv("HF_SPACE_URL", "https://NimrodDev-rag-bot.hf.space/whatsapp")
VERIFY_SECRET  = os.getenv("WEBHOOK_VERIFY")          # shared with HF Space
WHATSAPP_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "852540791274504")

# ------------------------------------------------------------------
#  WhatsApp reply helper
# ------------------------------------------------------------------
def _send_whatsapp_reply(to: str, body: str) -> None:
    url   = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": str(to),
        "type": "text",
        "text": {"body": body[:4096]}  # ≤ 4096, never empty
    }
    # DEBUG: remove after first successful reply
    logging.info("📤 DEBUG payload: %s", json.dumps(payload, indent=2))
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        r.raise_for_status()
        logging.info("📤 WhatsApp reply: %s %s", r.status_code, r.text)
    except Exception as e:
        logging.exception("📤 WhatsApp send failed: %s", e)

# ------------------------------------------------------------------
#  RAG call with shared-secret verify field
# ------------------------------------------------------------------
def _query_rag(phone: str, question: str) -> str:
    payload = {"from": phone, "text": question, "verify": VERIFY_SECRET}
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
            # ensure we never send empty text
            answer = answer.strip() or "I couldn't find an answer – a human will join shortly."
            _send_whatsapp_reply(job["from_number"], answer)
        except Exception as e:
            logging.exception("Job failed: %s", e)

worker_thread = threading.Thread(target=_worker, daemon=True)
worker_thread.start()

# ------------------------------------------------------------------
#  WhatsApp media download helper
# ------------------------------------------------------------------
def _download_media_url(media_id: str) -> str:
    """Get temporary HTTPS URL for a WhatsApp media ID."""
    url = f"https://graph.facebook.com/v22.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = requests.get(url, headers=headers, params={"phone_number_id": PHONE_NUMBER_ID}, timeout=20)
    r.raise_for_status()
    return r.json()["url"]

# ------------------------------------------------------------------
#  Webhook endpoint (Render)
# ------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    logging.info("📩 Incoming: %s", data)

    # ignore delivery/read receipts
    if data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"):
        return jsonify(ok=True), 200

    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]

        # 1)  VOICE message -------------------------------------------------
        if msg.get("type") == "voice":
            audio_id = msg["voice"]["id"]
            audio_url = _download_media_url(audio_id)
            answer = _query_rag(from_number, audio_url)   # Space sees "media" field
            _send_whatsapp_reply(from_number, answer)

        # 2)  TEXT message --------------------------------------------------
        elif msg.get("type") == "text":
            text = msg["text"]["body"]
            q.put({"question": text, "from_number": from_number})

        # 3)  UNSUPPORTED ---------------------------------------------------
        else:
            logging.warning("Unsupported message type: %s", msg.get("type"))

        return jsonify(ok=True), 200
    except Exception as e:
        logging.exception("Webhook error: %s", e)
        return jsonify(error=str(e)), 500

@app.route("/", methods=["GET"])
def index():
    return "WhatsApp webhook (Amina-bot) OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))