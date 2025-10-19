import os, re
from urllib.parse import quote
from flask import Flask, request
import requests
from dotenv import load_dotenv

load_dotenv()
VERIFY_TOKEN = os.getenv("WABA_VERIFY_TOKEN", "")
WABA_TOKEN   = os.getenv("WABA_TOKEN", "")
PHONE_ID     = os.getenv("WABA_PHONE_ID", "")
CSE_ENDPOINT = os.getenv("CSE_ENDPOINT", "").rstrip("/")
PORT         = int(os.getenv("PORT", "8080"))

GRAPH_BASE = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
HEADERS = {"Authorization": f"Bearer {WABA_TOKEN}", "Content-Type": "application/json"}

app = Flask(__name__)

def is_price_query(text: str) -> bool:
    text = text.lower()
    return any(t in text for t in ["precio", "vale", "cuánto", "coste", "cuesta", "€", "eur"])

def build_query(user_text: str) -> str:
    # Simplifica: quita “precio/vale/cuánto/coste/cuesta”
    t = re.sub(r"(?i)\b(precio|vale|cu[aá]nto|coste|cuesta)\b", "", user_text)
    t = t.replace(" de ", " ").strip()
    return t

def call_cse(query: str, top_n: int = 3):
    try:
        url = f"{CSE_ENDPOINT}?format=json&q={quote(query)}"
        r = requests.get(url, timeout=7)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            return []
        return data.get("items", [])[:top_n]
    except Exception:
        return []

def send_whatsapp(to: str, text: str):
    if not to or not text:
        return
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(GRAPH_BASE, headers=HEADERS, json=payload, timeout=10)

@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "forbidden", 403

@app.post("/webhook")
def incoming():
    data = request.get_json(force=True, silent=True) or {}
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    from_ = msg.get("from")
                    if msg.get("type") == "text":
                        body = (msg.get("text") or {}).get("body", "").strip()
                        if is_price_query(body):
                            q = build_query(body)
                            items = call_cse(q, top_n=3)
                            if not items:
                                send_whatsapp(from_, f"No he encontrado precios para: {q}")
                            else:
                                lines = [f"Resultados para: {q}"]
                                for i, it in enumerate(items, 1):
                                    title = it.get("title","")[:80]
                                    host  = it.get("host","")
                                    link  = it.get("link","")
                                    snippet = it.get("snippet","")
                                    m = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*€", snippet)
                                    price = f" · {m.group(0)}" if m else ""
                                    lines.append(f"{i}. {title}{price}\n{host}\n{link}")
                                send_whatsapp(from_, "\n\n".join(lines))
                        else:
                            send_whatsapp(from_, "Pídeme el precio: por ejemplo, 'precio mochila conejo jellycat'")
        return "ok", 200
    except Exception:
        return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
