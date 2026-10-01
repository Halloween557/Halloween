# Launch Guide — G.I.D.E.O.N. PC Agent (Gen26)

Everything runs from the **project root** (the folder containing `poller.py`):

```
C:\Users\d8ta2\Desktop\Gen26\files(1)
```

> Always open a terminal there first. Never launch from `C:\Windows\system32` —
> the scripts live in the project folder.

---

## 1. One-time setup

Each terminal must be opened in the project root.

**Install Python deps** (already done on this machine):
```powershell
python -m pip install -r requirements.txt
```
> Use `python -m pip …`, not `pip` — `pip` is not on PATH here.

**Environment files:**
- `.env`            — worker + voice listener (DATABASE_URL, LLM_PROVIDER, GROQ_API_KEY, AGENT_TOKEN, DEVICE_ID)
- `web\.env.local`  — web UI (DATABASE_URL, AGENT_TOKEN, GROQ_API_KEY)
- `AGENT_TOKEN` must be **identical** in both files (this is the login password for the chat page).

**Apply DB migrations** (creates all tables on Neon):
```powershell
python migrate.py
```
(Safe to re-run — uses `CREATE TABLE IF NOT EXISTS`.)

---

## 2. Recommended launch order

### a) PC Worker (REQUIRED for everything else to work)
This polls the Neon inbox, runs the LLM tool loop, goals, watchdog and reflection.
```powershell
python poller.py
```
Expected output:
```
PC agent AUTONOMOUS worker started (groq). Polling Neon + running goal engine...
```
> The chat page only shows **Online** while this is heartbeating.

### b) Web UI (the visual interface)
```powershell
cd web
npm run dev          # dev server  ->  http://localhost:3000
```
Production build instead:
```powershell
npm run build
npm start
```
Login with the **AGENT_TOKEN** from `.env`. Features: chat, voice input, wake-word
("Hey Gideon"), memories drawer, TTS, "Clear" button.

### c) WhatsApp Bridge (for WhatsApp on Phone)
```powershell
node whatsapp-bridge\index.js
```
On first launch, scan the QR code displayed in your terminal or open `http://localhost:3001/qr` on your browser to scan with your phone:
**WhatsApp > Linked Devices > Link a Device**.
Once authenticated, the credentials are saved to `.wwebjs_auth/`.

### d) Email Setup (Gmail / Outlook / IMAP / SMTP)
Add your credentials to `.env`:
```ini
EMAIL_ADDRESS=your.email@gmail.com
EMAIL_PASSWORD=your-app-password
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_SMTP_SERVER=smtp.gmail.com
```
Now you can ask Gideon:
- *"Check my unread emails"*
- *"Search emails from John"*
- *"Read email 102"*
- *"Send an email to sarah@example.com saying..."* (Gideon will show the draft and ask for confirmation before sending)

### e) Voice listener (optional, ambient microphone)
```powershell
python voice_listener.py
```
Expected output:
```
G.I.D.E.O.N. Windows Desktop Ambient Voice Listener
Microphone Array (Intel Smart ...)
[+] Ambient Ear ACTIVE. Say anything with 'Gideon'...
```
Say **"Hey Gideon"** or **"Gideon, [command]"**. Voice TTS uses Windows speech synthesis.

### f) Legacy bare-bones chat server (optional)
The old single-session FastAPI server with `AGENT_TOKEN` auth:
```powershell
uvicorn server:app --port 8000
```

---

## 3. Verifying the whole stack

| Check | What to expect |
|---|---|
| Web page | `http://localhost:3000` loads (G.I.D.E.O.N. login) |
| Status dot | Green **Online** (worker running) |
| Send a chat | Message appears, worker replies within a few seconds |
| `web\dev.log` | Proxy/Next.js errors (if any) |
| `voice.log` | Voice listener detection / "Voice detected..." |

---

## 4. Stopping services

```powershell
Get-Process node | Stop-Process        # stops npm dev/build server
# Python processes:
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId, CommandLine
Stop-Process -Id <PID>                 # choose the poller/voice PID
```

---

## 5. Configuration reference (.env)

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` \| `groq` \| `openai` |
| `LLM_MODEL` | `openai/gpt-oss-120b` (groq) | pick any model shown at console.groq.com (e.g. `openai/gpt-oss-20b` or `qwen/qwen3.8-27b`) |
| `GROQ_API_KEY` | — | required when provider=groq |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434/v1` | local Ollama |
| `DATABASE_URL` | — | Neon connection string (required) |
| `AGENT_TOKEN` | — | chat page login; must match `web\.env.local` |
| `ELEVEN_API_KEY` | — | (web only) cloud TTS so Gideon speaks a consistent British accent on any device; falls back to browser voices if unset |
| `ELEVEN_VOICE_ID` | — | (web only) force a specific ElevenLabs voice instead of auto-picking a British one |
| `DEVICE_ID` | `pc-main` | device shown in the UI |
| `AUTONOMOUS_INTERVAL` | `10` | seconds between goal-engine checks |
| `REFLECTION_INTERVAL` | `1800` | seconds between self-reflection turns |
| `WATCHDOG_CPU` / `RAM` / `DISK` | `90` / `92` / `95` | alert thresholds (PC worker only) |
| `POLL_SECONDS` | `1` | inbox poll cadence (PC worker) |
| `MAX_HISTORY_MESSAGES` | `24` | older turns dropped from context per reply (speed + memory) |
| `CLOUD_TAKEOVER_SECONDS` | `25` | cloud standby takes over after PC has been quiet this many seconds |
| `CLOUD_MAX_JOB_AGE_SECONDS` | `180` | a `processing` inbox row older than this is treated as orphaned and ignored by the standby |
| `CLOUD_POLL_SECONDS` | `2` | poll cadence for the cloud standby worker |

---

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| `pip` is not recognized | Use `python -m pip …` |
| `can't open file '...voice_listener.py'` | You launched from the wrong folder — cd to the project root |
| Web shows **Offline** | Worker (`python poller.py`) not running, or `DATABASE_URL` mismatch between `.env` and `web\.env.local` |
| `401 Unauthorized` on login | `AGENT_TOKEN` differs between `.env` and `web\.env.local` |
| `400 … output_parse_failed / tool_use_failed` | Known Groq quirk with `gpt-oss-20b` — now auto-retried (agent.py). It delays a reply but does not crash the worker |
| Chat hangs after sending | Ensure worker is running and the inbox row is dequeued (`status='processing'/'done'` in Neon) |
| PC off → no replies | Deploy the cloud standby worker (see section 7) somewhere always-on |
| After editing `agent.py` / `tools.py` / system prompt | Restart `poller.py` to pick up changes |
| `migrate.py` errors | Confirm `DATABASE_URL` is a Neon connection string with `sslmode=require` |

---

*Generated for the Gen26 PC agent build. Voices, tools, goals, memory, and the web UI
share one Postgres database on Neon (`ep-empty-voice-a70kik5l`), so any component can be
restarted independently.*

---

## 7. Optional: cloud standby worker — chat keeps replying when the PC is off

`cloud_worker.py` is a second copy of the agent that runs on an **always-on hosted box**.
It watches the PC's heartbeat in Neon:

- While `poller.py` is alive (heartbeat fresh), the standby stays **silent** and the
  PC worker keeps doing everything (apps, files, PowerShell, …).
- Once the PC goes quiet for longer than `CLOUD_TAKEOVER_SECONDS` (default 25s), the
  standby **claims the queued messages and answers itself** — conversation history and
  memories are shared via Neon, so it picks up right where the PC left off.
- All **PC tools are disabled** in the cloud copy, so nothing can ever run on the wrong
  machine. It answers using the cloud LLM (Groq) + web search + memory + goals, and
  prefixes replies with ☁️ so you know the PC was off.
- It **never writes a heartbeat**, so the web UI still shows the true PC status.

### Deploy (pick any always-on host)

Any $3–6/mo VPS, Railway, Fly.io, or an Oracle "Always Free" VM works. The cloud copy
needs the whole repo folder (it imports the same `agent.py` / `db.py` / …), but only the
small package set in `cloud/requirements.txt`:

1. Push/clone the repo onto the host.
2. `python -m venv venv && . venv/bin/activate && pip install -r cloud/requirements.txt`
3. Create a `.env` on the host with **the same values as this PC's `.env`**:
   `LLM_PROVIDER=groq`, `GROQ_API_KEY`, `LLM_MODEL=openai/gpt-oss-20b`,
   `DATABASE_URL`, `DEVICE_ID=pc-main` (must match so it watches the right heartbeat).
4. Test once, then run it as a service:

   ```bash
   python cloud_worker.py --once     # process one queued job and exit (sanity check)
   python cloud_worker.py            # stay alive and poll forever
   ```

   For `systemd`:

   ```ini
   [Unit]
   Description=GIDEON cloud standby worker
   After=network-online.target
   [Service]
   WorkingDirectory=/path/to/repo
   EnvironmentFile=/path/to/repo/.env
   ExecStart=/path/to/repo/venv/bin/python cloud_worker.py
   Restart=always
   [Install]
   WantedBy=multi-user.target
   ```

5. Reply cadence on a VPS: near-instant (polls every 2s). On cron-only hosts you can run
   `python cloud_worker.py --once` on a schedule instead.