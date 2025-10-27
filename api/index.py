# api/index.py – WhatsApp ↔️ HF-Space RAG Bridge (Flask)
from flask import Flask, request, jsonify
import os, requests, hmac, hashlib, logging, time

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ----------------- CREDS -----------------
ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
APP_SECRET   = os.getenv("META_APP_SECRET", "")
PHONE_ID     = os.getenv("META_PHONE_NUMBER_ID")
# FINAL ➜ correct HF-Space endpoint
HF_SPACE     = os.getenv("RAG_ENDPOINT", "https://nimroddev-rag-space-v2.hf.space/ask").strip().rstrip("/")
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "ldlamaki2025")

# ----------------- SIGNATURE -----------------
def verify_signature(payload: bytes, sig: str) -> bool:
    if not APP_SECRET:
        return True
    try:
        mac = hmac.new(APP_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={mac}", sig)
    except Exception:
        logging.exception("Signature check failed")
        return False

# ----------------- ROOT (health) -----------------
@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "service": "whatsapp-rag-bridge"}), 200

# ----------------- VERIFY WEBHOOK -----------------
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode  = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    logging.info(f"🔍 Verification: mode={mode}, token={token}, challenge={challenge}")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logging.info("✅ Webhook verified")
        return challenge, 200
    return "Forbidden", 403

# ----------------- WARM-UP HF -----------------
def _wait_for_hf_space(max_wait: int = 120):
    """Cold-start guard: ping HF until 200 or timeout."""
    for t in range(0, max_wait, 5):
        try:
            r = requests.get(HF_SPACE.replace("/ask", ""), timeout=10)
            if r.status_code == 200:
                logging.info("🌡️  HF-Space is warm")
                return
        except Exception as e:
            logging.info(f"🌡️  HF-Space cold ({t}s) – {e}")
        time.sleep(5)
    logging.warning("🌡️  HF-Space still cold – proceeding anyway")

# ----------------- HANDLE MESSAGE -----------------
@app.route("/webhook", methods=["POST"])
def webhook():
    logging.info("📦 FULL HEADERS: %s", dict(request.headers))
    logging.info("📦 RAW BODY: %s", request.get_data(as_text=True))
    signature = request.headers.get("X-Hub-Signature-256", "")
    if APP_SECRET and not verify_signature(request.get_data(), signature):
        return "Bad signature", 403

    data = request.get_json(silent=True) or {}
    logging.info(f"📩 Incoming: {data}")

    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError):
        return "OK", 200

    if msg.get("type") != "text":
        return "OK", 200

    from_number, text = msg["from"], msg["text"]["body"].strip()
    logging.info(f"💬 From {from_number}: {text}")

    # ---------- wait for HF to be warm (first msg only) ----------
    _wait_for_hf_space()

    # ---------- RAG query with retry ----------
    reply = "I'm having a brief technical issue—please try again in a moment."
    for attempt in range(1, 5):
        try:
            logging.info(f"🧠 Attempt {attempt} → {HF_SPACE}")
            r = requests.post(
                HF_SPACE,
                json={"question": text, "from_human": False},
                timeout=60          # 60 s cold-start tolerance
            )
            r.raise_for_status()
            answer = r.json().get("answer")
            if answer is None:               # human-agent window active
                logging.info("🤫 Human agent active – bot stays silent")
                return "OK", 200
            reply = answer or "I'm not sure how to answer that right now."
            logging.info(f"✅ RAG reply: {reply}")
            break
        except Exception as e:
            logging.warning(f"Attempt {attempt} failed: {e}")
            time.sleep(2 ** attempt)
    else:
        logging.error("🔥 All RAG attempts failed – using fallback")

    # ---------- WhatsApp reply ----------
    payload = {
        "messaging_product": "whatsapp",
        "to": from_number,
        "type": "text",
        "text": {"body": reply},
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

    try:
        resp = requests.post(
            f"https://graph.facebook.com/v22.0/852540791274504/messages",
            json=payload, headers=headers, timeout=200
        )
        logging.info(f"📤 WhatsApp reply status: {resp.status_code}  {resp.text[:100]}")
    except Exception:
        logging.exception("❌ WhatsApp send failed")

    return "OK", 200