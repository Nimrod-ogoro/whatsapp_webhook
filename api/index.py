#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhatsApp → HF-Space webhook relay
Automatic replies only. No human-agent features.
Stores all messages in Supabase for dashboard access.
"""

import os, json, time, logging, threading, httpx
from flask import Flask, request, jsonify
from persistqueue import SQLiteQueue
from supabase import create_client, Client

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------- CONFIG ----------
JOB_DB         = "/tmp/job_queue.db"
HF_SPACE_URL   = os.getenv("HF_SPACE_URL", "https://nimroddev-ld-lamaki-bot.hf.space/whatsapp").strip()
VERIFY_SECRET  = os.getenv("WEBHOOK_VERIFY", "").strip()
WHATSAPP_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()
PHONE_ID       = os.getenv("PHONE_NUMBER_ID", "852540791274504").strip()
SELF_URL       = os.getenv("SELF_URL", "").strip()

# Supabase server (service role) client
SUPABASE_URL = os.getenv("SUPABASE_URL").strip()
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY").strip()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- QUEUE ----------
q = SQLiteQueue(JOB_DB, auto_commit=True, multithreading=True)

# ---------- HELPERS ----------
def send_whatsapp(to: str, body: str) -> None:
    """Send WhatsApp text message."""
    url = f"https://graph.facebook.com/v22.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": str(to),
        "type": "text",
        "text": {"body": body[:4096]}
    }
    try:
        r = httpx.post(url, headers=headers, json=payload, timeout=120)
        r.raise_for_status()
        logging.info("📤 Sent to %s", to)
    except Exception as e:
        logging.exception("📤 Send failed: %s", e)

def query_hf(phone: str, text: str) -> str:
    """Send user message to HF Space and return AI reply."""
    payload = {"from": phone, "text": text, "verify": VERIFY_SECRET}
    for attempt in range(3):
        try:
            r = httpx.post(HF_SPACE_URL, json=payload, timeout=120)
            r.raise_for_status()
            return r.json().get("reply", "").strip() or "🤖 Amina had nothing to say."
        except Exception as e:
            logging.warning("HF call attempt %s failed: %s", attempt + 1, e)
            time.sleep(5)
    return "😞 Amina is currently unavailable."

def download_media(media_id: str) -> str:
    """Resolve a WhatsApp media download URL."""
    url = f"https://graph.facebook.com/v22.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = httpx.get(url, headers=headers, params={"phone_number_id": PHONE_ID}, timeout=20)
    r.raise_for_status()
    return r.json()["url"]

def save_message(phone: str, body: str, direction: str = "incoming") -> None:
    """Save message to Supabase for frontend dashboard."""
    try:
        supabase.table("messages").insert({
            "phone": phone,
            "body": body,
            "direction": direction
        }).execute()

        # Update customers table with last_seen
        supabase.table("customers").upsert({
            "phone": phone,
            "last_seen": time.strftime("%Y-%m-%d %H:%M:%S")
        }, on_conflict="phone").execute()
    except Exception as e:
        logging.exception("Failed to save message to Supabase: %s", e)

# ---------- WORKER ----------
def worker():
    """Background worker: get jobs → call AI → send reply → save both."""
    while True:
        job = q.get()
        try:
            answer = query_hf(job["phone"], job["text"])
            send_whatsapp(job["phone"], answer)

            # Save incoming and outgoing messages
            save_message(job["phone"], job["text"], direction="incoming")
            save_message(job["phone"], answer, direction="outgoing")
        except Exception as e:
            logging.exception("Job failed: %s", e)

threading.Thread(target=worker, daemon=True).start()

# ---------- KEEP ALIVE ----------
def keepalive():
    """Ping HF Space to prevent sleeping."""
    base_url = HF_SPACE_URL.split("/whatsapp")[0]
    while True:
        try:
            r = httpx.get(base_url, timeout=30)
            logging.info("keep-alive ping: %s", r.status_code)
        except Exception as e:
            logging.warning("keep-alive failed: %s", e)
        time.sleep(300)

threading.Thread(target=keepalive, daemon=True).start()

def self_keepalive():
    """Ping own Render URL to keep alive (optional)."""
    if not SELF_URL:
        return
    while True:
        try:
            r = httpx.get(SELF_URL, timeout=10)
            logging.info("self-ping: %s", r.status_code)
        except Exception as e:
            logging.warning("self-ping failed: %s", e)
        time.sleep(60)

threading.Thread(target=self_keepalive, daemon=True).start()

# ---------- WEBHOOK ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive WhatsApp messages."""
    data = request.get_json(force=True)
    logging.info("📩 Incoming: %s", data)

    entry  = data.get("entry", [{}])[0]
    change = entry.get("changes", [{}])[0]
    value  = change.get("value", {})

    # Ignore outbound delivery status
    if value.get("statuses"):
        return jsonify(ok=True), 200

    try:
        msg   = value["messages"][0]
        phone = msg["from"]
        mtype = msg["type"]

        if mtype == "text":
            q.put({"phone": phone, "text": msg["text"]["body"]})

        elif mtype == "voice":
            media_url = download_media(msg["voice"]["id"])
            q.put({"phone": phone, "text": f"[voice:{media_url}]"})

        else:
            logging.warning("Unsupported message type: %s", mtype)

        return jsonify(ok=True), 200

    except Exception as e:
        logging.exception("Webhook error: %s", e)
        return jsonify(error=str(e)), 500

@app.route("/", methods=["GET"])
def health():
    return "Webhook OK", 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)




