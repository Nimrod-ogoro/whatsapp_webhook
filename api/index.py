from flask import Flask, request, jsonify
import os, requests, hmac, hashlib, logging

app = Flask(__name__)

# ---------- Meta credentials ----------
ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
APP_SECRET   = os.getenv("META_APP_SECRET")
PHONE_ID     = os.getenv("META_PHONE_NUMBER_ID")
HF_SPACE     = os.getenv("RAG_ENDPOINT", "https://nimroddev-rag-space.hf.space/ask")

# ---------- verify incoming signature ----------
def verify_signature(payload, sig):
    mac = hmac.new(APP_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={mac}", sig)

# ---------- webhook entry ----------
@app.post("/")
def webhook():
    # 1. verify request came from Meta
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.get_data(), signature):
        return "Bad signature", 403

    # 2. parse Meta payload
    data = request.get_json()
    entry = data.get("entry", [{}])[0]
    changes = entry.get("changes", [{}])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        return "OK", 200

    msg = messages[0]
    if msg.get("type") != "text":
        return "OK", 200  # ignore media for now

    from_number = msg["from"]
    text        = msg["text"]["body"].strip()

    # 3. hit your HF-Space RAG
    try:
        reply = requests.post(HF_SPACE, json={"question": text}, timeout=18).json()["answer"]
    except Exception as e:
        logging.exception("RAG error")
        reply = "I'm not sure, a human will follow up."

    # 4. send answer back via Meta Cloud API
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