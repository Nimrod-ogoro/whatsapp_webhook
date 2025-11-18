#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhatsApp → HF-Space webhook relay
With HUMAN-AGENT detector to avoid duplicate bot replies.
"""

import os, json, time, logging, threading, httpx
from flask import Flask, request, jsonify
from persistqueue import SQLiteQueue

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------- CONFIG ----------
JOB_DB         = "/tmp/job_queue.db"
HF_SPACE_URL   = os.getenv("HF_SPACE_URL", "https://nimroddev-ld-lamaki-bot.hf.space/whatsapp").strip()
VERIFY_SECRET  = os.getenv("WEBHOOK_VERIFY", "").strip()
WHATSAPP_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()
PHONE_ID       = os.getenv("PHONE_NUMBER_ID", "852540791274504").strip()

# ---------- QUEUE ----------
q = SQLiteQueue(JOB_DB, auto_commit=True, multithreading=True)

# ---------- HUMAN ACTIVITY MEMORY ----------
HUMAN_ACTIVE = {}       # phone -> last human timestamp
COOLDOWN_SEC = 30       # silence bot for 30 seconds


def mark_human(phone: str):
    HUMAN_ACTIVE[phone] = time.time()


def is_human_active(phone: str) -> bool:
    last = HUMAN_ACTIVE.get(phone, 0)
    return (time.time() - last) < COOLDOWN_SEC


# ---------- HELPERS ----------
def send_whatsapp(to: str, body: str) -> None:
    url = f"https://graph.facebook.com/v22.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
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
        logging.info("📤 sent to %s", to)
    except Exception as e:
        logging.exception("📤 send failed: %s", e)


def query_hf(phone: str, text: str) -> str:
    if is_human_active(phone):
        return "👨‍💼 A human agent is typing… please wait."

    payload = {"from": phone, "text": text, "verify": VERIFY_SECRET}

    for attempt in range(3):
        try:
            r = httpx.post(HF_SPACE_URL, json=payload, timeout=120)
            r.raise_for_status()
            return r.json().get("reply", "").strip() or \
                   "🤖 Amina had nothing to say – a human will jump in."
        except Exception as e:
            logging.warning("HF call %s failed: %s", attempt + 1, e)
            time.sleep(5)

    return "😞 Amina is currently unavailable, please wait for a human agent."


def download_media(media_id: str) -> str:
    url = f"https://graph.facebook.com/v22.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = httpx.get(url, headers=headers, params={"phone_number_id": PHONE_ID}, timeout=20)
    r.raise_for_status()
    return r.json()["url"]


# ---------- WORKER ----------
def worker():
    while True:
        job = q.get()
        try:
            if is_human_active(job["phone"]):
                logging.info("⛔ Human active, bot suppressed for %s", job["phone"])
                continue

            answer = query_hf(job["phone"], job["text"])
            send_whatsapp(job["phone"], answer)

        except Exception as e:
            logging.exception("job failed: %s", e)

threading.Thread(target=worker, daemon=True).start()


# ---------- KEEP-ALIVE ----------
def keepalive():
    base_url = HF_SPACE_URL.split("/whatsapp")[0]
    while True:
        try:
            r = httpx.get(base_url, timeout=30)
            logging.info("keep-alive ping: %s", r.status_code)
        except Exception as e:
            logging.warning("keep-alive failed: %s", e)
        time.sleep(300)

threading.Thread(target=keepalive, daemon=True).start()


# ---------- WEBHOOK ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    logging.info("📩 %s", data)

    entry = data.get("entry", [{}])[0]
    change = entry.get("changes", [{}])[0]
    value  = change.get("value", {})

    # OUTBOUND STATUS (ignore)
    if value.get("statuses"):
        return jsonify(ok=True), 200

    # TYPING INDICATOR (mark human active)
    if value.get("messages") and value["messages"][0].get("status") == "typing":
        phone = value["messages"][0]["from"]
        mark_human(phone)
        logging.info("✍ human typing: %s", phone)
        return jsonify(ok=True), 200

    # INBOUND MESSAGE
    try:
        msg   = value["messages"][0]
        phone = msg["from"]

        # If the message is from a HUMAN AGENT (your WA app)
        if msg.get("id", "").startswith("wamid.") and msg.get("from") == phone:
            mark_human(phone)
            logging.info("👨‍💼 human manually replied: %s", phone)
            return jsonify(ok=True), 200

        # Incoming text
        if msg.get("type") == "text":
            if not is_human_active(phone):
                q.put({"phone": phone, "text": msg["text"]["body"]})
            else:
                logging.info("⛔ Bot silenced, human active.")
        elif msg.get("type") == "voice":
            media_url = download_media(msg["voice"]["id"])
            q.put({"phone": phone, "text": f"[voice:{media_url}]"})
        else:
            logging.warning("unsupported type: %s", msg.get("type"))

        return jsonify(ok=True), 200

    except Exception as e:
        logging.exception("webhook error: %s", e)
        return jsonify(error=str(e)), 500


@app.route("/", methods=["GET"])
def health():
    return "Webhook OK", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
