#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhatsApp → HF-Space webhook relay
Automatic replies only.
Stores all messages in Supabase for dashboard access.
"""

import os, json, time, logging, threading, httpx
from flask import Flask, request, jsonify
from persistqueue import SQLiteQueue
from supabase import create_client, Client

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
JOB_DB = "/tmp/job_queue.db"

def safe_env(name: str, required=False, default=""):
    val = os.getenv(name)
    if val is None:
        if required:
            raise RuntimeError(f"Missing env variable: {name}")
        return default
    return val.strip()

HF_SPACE = safe_env("HF_SPACE", required=True)
VERIFY_SECRET = safe_env("WEBHOOK_VERIFY", default="")
WHATSAPP_TOKEN = safe_env("META_ACCESS_TOKEN", required=True)
PHONE_ID = safe_env("PHONE_NUMBER_ID", required=True)
SELF_URL = safe_env("RENDER_WEBHOOK_HOST", default="")

# ---------------------------------------------------------
# SUPABASE
# ---------------------------------------------------------
SUPABASE_URL = safe_env("VITE_SUPABASE_URL", required=True)
SUPABASE_KEY = safe_env("VITE_SUPABASE_KEY", required=True)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------
# QUEUE
# ---------------------------------------------------------
q = SQLiteQueue(JOB_DB, auto_commit=True, multithreading=True)

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
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
    payload = {
        "from": phone,
        "text": text,
        "verify": VERIFY_SECRET
    }

    for attempt in range(3):
        try:
            # POST to HF webhook endpoint
            r = httpx.post(HF_SPACE, json=payload, timeout=120)
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
    return r.json().get("url")


def save_message(phone: str, body: str, direction: str = "incoming") -> None:
    try:
        # First, ensure the customer exists
        supabase.table("customers").upsert({
            "phone": phone,
            "last_seen": time.strftime("%Y-%m-%d %H:%M:%S")
        }, on_conflict="phone").execute()

        # Then, insert the message
        supabase.table("messages").insert({
            "phone": phone,
            "body": body,
            "direction": direction
        }).execute()

    except Exception as e:
        logging.exception("Failed to save message to Supabase: %s", e)


# ---------------------------------------------------------
# WORKER
# ---------------------------------------------------------
def worker():
    while True:
        job = q.get()
        try:
            # Save incoming message first
            save_message(job["phone"], job["text"], "incoming")

            # Query HF AI
            answer = query_hf(job["phone"], job["text"])

            # Send reply
            send_whatsapp(job["phone"], answer)

            # Save outgoing message
            save_message(job["phone"], answer, "outgoing")
        except Exception as e:
            logging.exception("Job failed: %s", e)


threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------
# KEEP ALIVE
# ---------------------------------------------------------
def keepalive():
    base = HF_SPACE.split("/")[0]
    while True:
        try:
            httpx.get(base, timeout=30)
        except:
            pass
        time.sleep(300)


threading.Thread(target=keepalive, daemon=True).start()


def self_keepalive():
    if not SELF_URL:
        return
    while True:
        try:
            httpx.get(SELF_URL, timeout=10)
        except:
            pass
        time.sleep(60)


threading.Thread(target=self_keepalive, daemon=True).start()


# ---------------------------------------------------------
# WEBHOOK
# ---------------------------------------------------------
@app.post("/webhook")
def webhook():
    data = request.get_json(force=True)
    logging.info("📩 Incoming: %s", data)

    entry  = data.get("entry", [{}])[0]
    change = entry.get("changes", [{}])[0]
    value  = change.get("value", {})

    # Delivery reports
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


@app.get("/")
def health():
    return "Webhook OK", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)






