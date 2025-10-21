from flask import Flask, request
import os
import requests

app = Flask(__name__)
URL = os.getenv("RAG_ENDPOINT", "http://localhost:7860/ask")

@app.post("/")
def w():
	q = request.values.get("Body", "").strip()
	if not q:
		return "", 200, {"Content-Type": "text/xml"}
	try:
		r = requests.post(URL, json={"question": q}, timeout=18).json().get("answer", "")
	except Exception:
		r = "I'm not sure, a human will follow up."
	body = f"<Response><Message>{r}</Message></Response>"
	return body, 200, {"Content-Type": "text/xml"}