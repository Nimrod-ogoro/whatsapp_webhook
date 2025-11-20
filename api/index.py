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

# -----------------------------------------------------------
# CONFIG
# -----------------------------------------------------------
JOB_DB = "/tmp/job_queue.db"

HF_SPACE = os.getenv("HF_SPACE")
if not HF_SPACE:
    raise RuntimeError("HF_SPACE env variable is not set")
HF_SPACE = HF_SPACE.strip()

VERIFY_SECRET = os.getenv("WEBHOOK_VERIFY", "").strip()
WHATSAPP_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

PHONE_ID = os.getenv("PHONE_NUMBER_ID")
if not PHONE_ID:
    raise RuntimeError("PHONE_NUMBER_ID env variable is not set")
PHONE_ID = PHONE_ID.strip()

SELF_URL = os.getenv("RENDER_WEBHOOK_HOST", "").strip()

# -----------------------------------------------------------
# SUPABASE
# -----------------------------------------------------------
SUPABASE_URL = os.getenv("VITE_SUPABASE_URL")
SUPABASE_KEY = os.getenv("VITE_SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("VITE_SUPABASE_URL or VITE_SUPABASE_KEY not set")

SUPABASE_URL = SUPABASE_URL.strip()
SUPABASE_KEY = SUPABASE_KEY.strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------------------------------------------
# QUEUE
# -----------------------------------------------------------
q = SQLiteQueue(JOB_DB, auto_commit=True, multithreading=True)

# -----------------------------------------------------------
# HELPERS
# -----------------------------------------------------------
def send_whatsapp(to: str, body: str) -> None:
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
    """
    Fix: HF Spaces sometimes fail SSL. Disable verify ONLY for calls to HF.
    """
    payload = {"from": phone, "text": text, "verify": VERIFY_SECRET}

    for attempt in range(3):
        try:
            r = httpx.post(
                HF_SPACE,
                json=payload,
                timeout=120,
                verify=False  # FIX: HuggingFace SSL cert mismatch
            )
            r.raise_for_status()
            return r.json().get("reply", "").strip() or "🤖 Amina had nothing to say."

        except Exception as e:
            logging.warning("HF call attempt %s failed: %s", attempt + 1, e)
            time.sleep(5)

    return "😞 Amina is currently unavailable."


def download_media(media_id: str) -> str:
    url = f"https://graph.facebook.com/v22.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = httpx.get(url, headers=headers, params={"phone_number_id": PHONE_ID}, timeout=20)
    r.raise_for_status()
    return r.json()["url"]


def save_message(phone: str, body: str, direction: str = "incoming") -> None:
    try:
        supabase.table("messages").insert({
            "phone": phone,
            "body": body,
            "direction": direction
        }).execute()

        supabase.table("customers").upsert({
            "phone": phone,
            "last_seen": time.strftime("%Y-%m-%d %H:%M:%S")
        }, on_conflict="phone").execute()
    except Exception as e:
        logging.exception("Failed to save message to Supabase: %s", e)

# -----------------------------------------------------------
# WORKER
# -----------------------------------------------------------
def worker():
    while True:
        job = q.get()
        try:
            answer = query_hf(job["phone"], job["text"])
            send_whatsapp(job["phone"], answer)

            save_message(job["phone"], job["text"], direction="incoming")
            save_message(job["phone"], answer, direction="outgoing")

        except Exception as e:
            logging.exception("Job failed: %s", e)

threading.Thread(target=worker, daemon=True).start()


# -----------------------------------------------------------
# KEEP ALIVE — FIXED SSL ERRORS
# -----------------------------------------------------------
def keepalive():
    """
    Keep HF Space awake.
    Disable SSL verification to bypass hostname mismatch.
    """
    base_url = HF_SPACE.split("/ask")[0]

    while True:
        try:
            r = httpx.get(base_url, timeout=30, verify=False)
            logging.info("keep-alive ping: %s", r.status_code)
        except Exception as e:
            logging.warning("keep-alive failed: %s", e)
        time.sleep(300)

threading.Thread(target=keepalive, daemon=True).start()


def self_keepalive():
    """
    Keep Render service alive.
    Render resets SSL so disable verify to avoid spam.
    """
    if not SELF_URL:
        return

    while True:
        try:
            r = httpx.get(SELF_URL, timeout=10, verify=False)
            logging.info("self-ping: %s", r.status_code)
        except Exception as e:
            logging.warning("self-ping failed: %s", e)
        time.sleep(60)

threading.Thread(target=self_keepalive, daemon=True).start()

# -----------------------------------------------------------
# WEBHOOK
# -----------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    logging.info("📩 Incoming: %s", data)

    entry = data.get("entry", [{}])[0]
    change = entry.get("changes", [{}])[0]
    value = change.get("value", {})

    if value.get("statuses"):
        return jsonify(ok=True), 200

    try:
        msg = value["messages"][0]
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





