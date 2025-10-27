import os
import json
import requests
import logging
from flask import Flask, request, jsonify
from rq import Queue
from redis import Redis

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ------------------------------------------------------------------
#  Redis connection – falls back to localhost for local dev
# ------------------------------------------------------------------
redis_conn = Redis.from_url(os.getenv("REDIS_URL", "redis://red-d3vqne3ipnbc739kspcg:6379"),
                            socket_connect_timeout=5,
                            socket_timeout=5)
q = Queue(connection=redis_conn, default_timeout=300)  # 5 min job limit

# ------------------------------------------------------------------
#  config
# ------------------------------------------------------------------
HF_SPACE_ASK = "https://nimroddev-rag-space-v2.hf.space/ask"
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# ------------------------------------------------------------------
#  background job – runs inside RQ worker
# ------------------------------------------------------------------
def _send_whatsapp_reply(to: str, body: str) -> None:
    url = f"https://graph.facebook.com/v18.0/852540791274504/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        r.raise_for_status()
        logging.info("📤 WhatsApp reply status: %s  %s", r.status_code, r.text)
    except Exception as e:
        logging.exception("📤 WhatsApp send failed: %s", e)


def _call_rag_and_reply(question: str, from_number: str) -> None:
    """
    Background job: wake HF space → query → send WhatsApp reply.
    """
    for attempt in range(3):
        try:
            logging.info("🧠 Attempt %s → %s", attempt + 1, HF_SPACE_ASK)
            r = requests.post(HF_SPACE_ASK,
                              json={"question": question, "from_human": False},
                              timeout=60)
            r.raise_for_status()
            answer = r.json().get("answer", "No answer returned.")
            break
        except Exception as e:
            logging.warning("RAG call %s – %s", attempt, e)
            time.sleep(5)
    else:
        answer = "😞 Our AI is asleep right now, please try later."

    _send_whatsapp_reply(from_number, answer)


# ------------------------------------------------------------------
#  webhook – returns instantly
# ------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    logging.info("📩 Incoming: %s", data)

    # ignore status updates
    if data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"):
        return jsonify(ok=True), 200

    msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
    text = msg["text"]["body"]
    from_number = msg["from"]

    q.enqueue(_call_rag_and_reply, text, from_number)
    return jsonify(ok=True), 200


# ------------------------------------------------------------------
#  health check
# ------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return "WhatsApp webhook OK", 200