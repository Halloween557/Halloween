# PC Agent

A personal AI agent that controls your Windows PC — open apps, run commands,
manage files, check system status — reachable from your phone over HTTPS.

The chat UI lives on **Vercel**. Conversation state and a command inbox live in
**Neon**. A small **Windows worker** on this PC polls Neon, talks to a **local Ollama**
model (free), and runs the tools. Your phone never connects to your PC directly.

**Read the Safety Notes at the bottom before you run this.**

---

## How it fits together

1. Phone browser → Vercel (`your-app.vercel.app`)
2. Vercel writes your message into Neon (`messages` + `inbox`)
3. The PC worker claims the inbox row, runs the local model + tools, writes the reply
4. The phone page polls Vercel and shows the reply

The PC must be on, and `python poller.py` must be running. If the worker is down,
the UI shows **PC offline** and messages wait in the inbox.

**Optional 24/7 standby:** [`cloud_worker.py`](cloud_worker.py) is a second worker you
can host for free/cheap on an always-on box (VPS, Railway, Fly.io…). It stays silent
while the PC is alive, then answers messages itself with cloud-only tools (Groq LLM +
web search + memory) once the PC's heartbeat goes stale — so you get replies even when
the PC is off. PC-touching tools are disabled there. See **LAUNCH.md section 7**.

---

## 1. Install prerequisites

1. **Python 3.11+** — https://www.python.org/downloads/windows/ (check "Add to PATH")
2. **Ollama** — https://ollama.com/download (local models, no API bill)
3. A **Neon** project — https://console.neon.tech (free tier is enough)
4. A **Vercel** account — https://vercel.com (Hobby is enough)

You do **not** need Tailscale or a public port on the PC. The worker only makes
outbound connections to Neon.

## 2. Free local AI (Ollama)

The worker defaults to **Ollama** on this PC. There is no per-message bill.

1. Install Ollama if needed, then pull a model (this PC already has `qwen2.5:1.5b`):

   ```powershell
   ollama pull qwen2.5:1.5b
   ```

   For better tool use (larger download): `ollama pull qwen2.5:7b` then set `LLM_MODEL=qwen2.5:7b` in `.env`.

2. Leave Ollama running (it usually starts with Windows).

Optional **free cloud** instead of Ollama: get a Groq key at https://console.groq.com/keys (free tier, rate-limited) and set `LLM_PROVIDER=groq`, `GROQ_API_KEY=...`, `LLM_MODEL=openai/gpt-oss-120b` (pick any model your key can reach at console.groq.com).

## 3. Set up the Windows worker

Open PowerShell in this folder and run:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and fill in:

- `LLM_PROVIDER` — `ollama` (default, free)
- `LLM_MODEL` — e.g. `qwen2.5:1.5b`
- `AGENT_TOKEN` — a long random string. Generate one with:

  ```powershell
  powershell -Command "[guid]::NewGuid().ToString()"
  ```

- `DATABASE_URL` — Neon connection string (dashboard → Connect)

Apply the schema:

```powershell
python migrate.py
```

Start the worker (leave this window open):

```powershell
python poller.py
```

## 4. Deploy the chat app on Vercel

In the Vercel dashboard:

1. Import this repository (or `vercel` from the `web/` folder)
2. Set **Root Directory** to `web`
3. Add environment variables (same names as `web/.env.example`):
   - `DATABASE_URL` — Neon **pooled** URI (the host contains `-pooler`)
   - `AGENT_TOKEN` — **exactly** the same token as the PC `.env`
4. Deploy

Local web preview (optional):

```powershell
cd web
copy .env.example .env.local
# edit .env.local
npm install
npm run dev
```

Open http://localhost:3000

## 5. Connect from your phone

1. Open `https://<your-vercel-app>.vercel.app`
2. Paste `AGENT_TOKEN`, tap Connect
3. Chat — e.g. "what's using the most memory right now" or "open notepad"

## 6. (Optional) Run the worker on logon

1. Task Scheduler → Create Task
2. Trigger: At log on
3. Action: Start a program
   - Program: `C:\path\to\pc-agent\venv\Scripts\python.exe`
   - Arguments: `poller.py`
   - Start in: `C:\path\to\pc-agent`
4. Check "Run whether user is logged on or not" if you want it while locked

## 7. Optional local FastAPI UI

[`server.py`](server.py) still serves the old in-memory chat on port 8787. It does
not use Neon or Vercel. Prefer the worker + Vercel path for remote access. Do not
port-forward 8787.

---

## How confirmation works

Actions like deleting files, killing processes, running commands that look
destructive (delete/format/shutdown/etc.), or restarting the PC will make the
agent stop and ask first:

> ⚠️ This will run: delete_file({"path": "C:\\old\\report.docx"})
> Reply 'yes' to confirm or anything else to cancel.

Reply `yes` to proceed, anything else cancels it. Everything else (opening
apps, reading files, checking status, listing processes) runs immediately
without asking.

You can tighten or loosen this in `tools.py` — edit `DESTRUCTIVE_TOOLS` and
`DESTRUCTIVE_PS_PATTERNS`. Pending confirmations are stored in Neon so they
survive a worker restart.

## Cost

- **Ollama**: free, runs on this PC (electricity only)
- **Vercel Hobby** and **Neon free** cover the remote chat
- Optional Groq free tier if you set `LLM_PROVIDER=groq` (rate limits, no card for the basic key)

---

## ⚠️ Safety notes — read this

- **This gives an AI real control of your PC.** The confirmation step covers
  obviously destructive actions, but a model can still make mistakes on
  "safe" actions (e.g. writing a file to the wrong place). Don't point it at
  work-critical files you can't afford to lose without backups.
- **`AGENT_TOKEN` is the only thing standing between "just you" and anyone who
  finds your Vercel URL.** Keep `.env` private, never commit it, never share
  the token. Set the same token on Vercel and on the PC.
- **Do not port-forward the old FastAPI port.** The worker only talks outbound
  to Neon. Vercel never receives model API keys and never runs PowerShell.
- **This is a personal single-user tool.** There is one shared conversation.
- **The PC must be awake** with the worker running for tools to execute.
- **Back up anything important** before giving this agent free rein over
  your file system.
