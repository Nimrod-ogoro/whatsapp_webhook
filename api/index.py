from flask import Flask, request, jsonify
import os
import requests
import hmac
import hashlib
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ---------- Meta credentials ----------
ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
APP_SECRET   = os.getenv("META_APP_SECRET")
PHONE_ID     = os.getenv("META_PHONE_NUMBER_ID")
HF_SPACE     = os.getenv("RAG_ENDPOINT", "https://nimroddev-rag-space.hf.space/ask")
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "ldlamaki2025")

# ---------- verify incoming signature ----------
def verify_signature(payload, sig):
    if not APP_SECRET:
        return True  # Skip verification for local testing
    mac = hmac.new(APP_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={mac}", sig)

# ---------- Meta verification (GET) ----------
@app.get("/")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logging.info("Webhook verified successfully ✅")
        return challenge, 200
    logging.warning("Webhook verification failed ❌")
    return "Forbidden", 403

# ---------- webhook entry (POST) ----------
@app.post("/")
def webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")
    if APP_SECRET and not verify_signature(request.get_data(), signature):
        logging.warning("❌ Invalid signature")
        return "Bad signature", 403

    data = request.get_json()
    logging.info(f"📩 Incoming message: {data}")

    entry = data.get("entry", [{}])[0]
    changes = entry.get("changes", [{}])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        return "OK", 200

    msg = messages[0]
    if msg.get("type") != "text":
        logging.info("Ignoring non-text message.")
        return "OK", 200

    from_number = msg["from"]
    text = msg["text"]["body"].strip()

    # ---------- Ask your RAG model ----------
    try:
        logging.info(f"🧠 Asking RAG model: {text}")
        res = requests.post(HF_SPACE, json={"question": text}, timeout=25)
        res.raise_for_status()
        reply = res.json().get("answer", "I’m not sure how to answer that.")
    except Exception as e:
        logging.exception("🔥 Error talking to RAG model")
        reply = "Hmm... I had a little trouble understanding that. A human will follow up."

    # ---------- Send back via WhatsApp ----------
    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": from_number,
        "type": "text",
        "text": {"body": reply}
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        logging.info(f"📤 Sent message status: {resp.status_code}")
    except Exception:
        logging.exception("Failed to send reply to WhatsApp")

    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
