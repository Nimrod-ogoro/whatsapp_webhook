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
    mac = hmac.new(APP_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={mac}", sig)

# ---------- Meta verification (GET) ----------
@app.get("/")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# ---------- webhook entry (POST) ----------
@app.post("/")
def webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.get_data(), signature):
        return "Bad signature", 403

    data = request.get_json()
    entry = data.get("entry", [{}])[0]
    changes = entry.get("changes", [{}])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        return "OK", 200

    msg = messages[0]
    if msg.get("type") != "text":
        return "OK", 200

    from_number = msg["from"]
    text = msg["text"]["body"].strip()

    try:
        reply = requests.post(HF_SPACE, json={"question": text}, timeout=18).json()["answer"]
    except Exception as e:
        logging.exception("RAG error")
        reply = "I'm not sure, a human will follow up."

    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": from_number,
        "type": "text",
        "text": {"body": reply}
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, json=payload, timeout=10)

    return "OK", 200