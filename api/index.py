# app.py — WhatsApp ↔️ FastAPI RAG Bridge (Flask)

from flask import Flask, request, jsonify
import os
import requests
import hmac
import hashlib
import logging

# ----------------- SETUP -----------------
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ----------------- META CREDS -----------------
ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
APP_SECRET   = os.getenv("META_APP_SECRET", "")
PHONE_ID     = os.getenv("META_PHONE_NUMBER_ID")
HF_SPACE     = os.getenv("RAG_ENDPOINT", "https://nimroddev-rag-space.hf.space/ask")
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "ldlamaki2025")

# ----------------- SIGNATURE CHECK -----------------
def verify_signature(payload: bytes, sig: str) -> bool:
    """Verify X-Hub-Signature-256 header from Meta"""
    if not APP_SECRET:  # Skip check if APP_SECRET not set (useful for local dev)
        return True
    try:
        mac = hmac.new(APP_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={mac}", sig)
    except Exception as e:
        logging.exception("Error verifying signature")
        return False

# ----------------- VERIFY WEBHOOK (GET) -----------------
@app.get("/")
def verify_webhook():
    """Meta webhook verification handshake"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    logging.info(f"🔍 Verification request: mode={mode}, token={token}, challenge={challenge}")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logging.info("✅ Webhook verified successfully")
        return challenge, 200

    logging.warning("❌ Webhook verification failed (token mismatch)")
    return "Forbidden", 403

# ----------------- HANDLE MESSAGES (POST) -----------------
@app.post("/")
def webhook():
    """Handle incoming WhatsApp messages"""
    signature = request.headers.get("X-Hub-Signature-256", "")

    if APP_SECRET and not verify_signature(request.get_data(), signature):
        logging.warning("❌ Invalid signature - dropping request")
        return "Bad signature", 403

    data = request.get_json(silent=True) or {}
    logging.info(f"📩 Incoming data: {data}")

    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
    except Exception:
        logging.warning("Malformed payload - ignoring")
        return "OK", 200

    if not messages:
        return "OK", 200

    msg = messages[0]
    if msg.get("type") != "text":
        logging.info("Ignoring non-text message")
        return "OK", 200

    from_number = msg["from"]
    text = msg["text"]["body"].strip()
    logging.info(f"💬 Received from {from_number}: {text}")

    # ----------------- Ask your RAG model -----------------
    try:
        logging.info(f"🧠 Querying RAG model at {HF_SPACE}")
        res = requests.post(HF_SPACE, json={"question": text}, timeout=25)
        res.raise_for_status()
        reply = res.json().get("answer", "I’m not sure how to answer that right now.")
    except Exception as e:
        logging.exception("🔥 RAG model request failed")
        reply = "Hmm... I had trouble understanding that. A human will follow up soon."

    # ----------------- Send back via WhatsApp -----------------
    payload = {
        "messaging_product": "whatsapp",
        "to": from_number,
        "type": "text",
        "text": {"body": reply},
    }
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages",
            json=payload,
            headers=headers,
            timeout=10,
        )
        logging.info(f"📤 Sent message status: {resp.status_code}")
    except Exception:
        logging.exception("❌ Failed to send message via WhatsApp")

    return "OK", 200


# ----------------- RUN APP -----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logging.info(f"🚀 Flask app running on port {port}")
    app.run(host="0.0.0.0", port=port)
