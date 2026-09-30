import os
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from agent import Session

load_dotenv()

AGENT_TOKEN = os.environ.get("AGENT_TOKEN")
if not AGENT_TOKEN:
    raise RuntimeError("Set AGENT_TOKEN in your .env file before starting the server.")

app = FastAPI()
session = Session()  # single shared session; simple by design for a personal agent


class ChatRequest(BaseModel):
    message: str


def check_auth(authorization: str | None):
    if authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.post("/chat")
def chat(req: ChatRequest, authorization: str | None = Header(default=None)):
    check_auth(authorization)
    reply = session.handle_user_message(req.message)
    return {"reply": reply}


@app.get("/", response_class=HTMLResponse)
def index():
    # Minimal mobile-friendly chat page. Token is entered once and stored
    # in the browser's memory for the session (not localStorage, so it
    # clears when the tab closes).
    return """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PC Agent</title>
<style>
  body { font-family: -apple-system, sans-serif; margin:0; background:#111; color:#eee; }
  #log { padding:12px; padding-bottom:100px; }
  .msg { margin:8px 0; padding:10px 14px; border-radius:12px; max-width:85%; white-space:pre-wrap; }
  .user { background:#2563eb; margin-left:auto; }
  .bot { background:#2a2a2a; }
  #bar { position:fixed; bottom:0; left:0; right:0; display:flex; padding:10px; background:#111; border-top:1px solid #333; }
  #input { flex:1; padding:10px; border-radius:8px; border:none; font-size:16px; }
  #send { padding:10px 16px; margin-left:8px; border-radius:8px; border:none; background:#2563eb; color:white; }
  #tokenBar { padding:10px; }
  #tokenInput { width:70%; padding:8px; }
</style>
</head>
<body>
<div id="tokenBar">
  <input id="tokenInput" placeholder="Paste agent token" type="password">
  <button onclick="saveToken()">Connect</button>
</div>
<div id="log"></div>
<div id="bar" style="display:none">
  <input id="input" placeholder="Message your PC...">
  <button id="send" onclick="send()">Send</button>
</div>
<script>
let token = null;
function saveToken() {
  token = document.getElementById('tokenInput').value;
  document.getElementById('tokenBar').style.display = 'none';
  document.getElementById('bar').style.display = 'flex';
}
function addMsg(text, cls) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.textContent = text;
  document.getElementById('log').appendChild(d);
  window.scrollTo(0, document.body.scrollHeight);
}
async function send() {
  const inp = document.getElementById('input');
  const text = inp.value.trim();
  if (!text) return;
  addMsg(text, 'user');
  inp.value = '';
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
      body: JSON.stringify({message: text})
    });
    if (res.status === 401) { addMsg('Unauthorized - check your token.', 'bot'); return; }
    const data = await res.json();
    addMsg(data.reply, 'bot');
  } catch (e) {
    addMsg('Connection error: ' + e, 'bot');
  }
}
document.getElementById('input').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
</script>
</body>
</html>
"""
