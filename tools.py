"""
Tool implementations for the PC agent.
Each tool is a plain Python function. Destructive ones are listed in
DESTRUCTIVE_TOOLS and will be intercepted by agent.py for confirmation
before they ever run.
"""

import os
import re
import subprocess
import psutil
import shutil
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

# ---- Tools considered destructive / irreversible ----
# Anything in here requires the user to explicitly confirm before running.
# NOTE: run_powershell is NOT listed here — it is handled separately via
# is_destructive_command() which inspects the command string for dangerous patterns.
DESTRUCTIVE_TOOLS = {"delete_file", "kill_process", "shutdown_or_restart"}

# Keywords that make an otherwise-normal powershell command destructive.
DESTRUCTIVE_PS_PATTERNS = [
    "remove-item", "del ", "rm ", "rd ", "rmdir", "format", "diskpart",
    "stop-process", "shutdown", "restart-computer", "reg delete",
    "clear-content", "erase", "attrib -r", "fsutil",
]

# Maximum characters returned from run_powershell to avoid overflowing model context.
PS_OUTPUT_MAX_CHARS = 4000


def is_destructive_command(command: str) -> bool:
    lowered = command.lower()
    return any(p in lowered for p in DESTRUCTIVE_PS_PATTERNS)


def run_powershell(command: str) -> str:
    """Run a PowerShell command and return stdout/stderr."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=60
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        combined = out if out else (err if err else "(no output)")
        if len(combined) > PS_OUTPUT_MAX_CHARS:
            combined = combined[:PS_OUTPUT_MAX_CHARS] + f"\n... [output truncated at {PS_OUTPUT_MAX_CHARS} chars]"
        return combined
    except Exception as e:
        return f"Error: {e}"


def open_application(app_name: str) -> str:
    """Launch an application by name (e.g. 'notepad', 'chrome', 'calc')."""
    try:
        os.startfile(app_name)  # Windows-only
        return f"Launched {app_name}"
    except Exception as e:
        try:
            subprocess.Popen(app_name, shell=True)
            return f"Launched {app_name}"
        except Exception as e2:
            return f"Error launching {app_name}: {e2}"


SENSITIVE_FILENAMES = {
    ".env", ".env.local", ".env.example", ".neon",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
}


def is_sensitive_path(p: Path) -> bool:
    try:
        resolved = p.resolve()
        if resolved.name.lower() in SENSITIVE_FILENAMES:
            return True
        for part in resolved.parts:
            if part.lower() in SENSITIVE_FILENAMES:
                return True
    except Exception:
        if p.name.lower() in SENSITIVE_FILENAMES:
            return True
    return False


def read_file(path: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"
        if is_sensitive_path(p):
            return f"Access denied: Reading {p.name} is blocked for security."
        if p.stat().st_size > 200_000:
            return "File too large to read inline (200KB limit)."
        return p.read_text(errors="replace")
    except Exception as e:
        return f"Error: {e}"


def write_file(path: str, content: str) -> str:
    try:
        p = Path(path)
        if is_sensitive_path(p):
            return f"Access denied: Writing to {p.name} is blocked for security."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error: {e}"


def list_directory(path: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"Path not found: {path}"
        entries = []
        for item in sorted(p.iterdir()):
            kind = "DIR " if item.is_dir() else "FILE"
            entries.append(f"{kind}  {item.name}")
        return "\n".join(entries) if entries else "(empty)"
    except Exception as e:
        return f"Error: {e}"


def delete_file(path: str) -> str:
    try:
        p = Path(path)
        if is_sensitive_path(p):
            return f"Access denied: Deleting {p.name} is blocked for security."
        if p.is_dir():
            shutil.rmtree(p)
            return f"Deleted directory {path}"
        p.unlink()
        return f"Deleted {path}"
    except Exception as e:
        return f"Error: {e}"


def list_processes() -> str:
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            info = p.info
            pid = info.get("pid")
            name = info.get("name") or "unknown"
            mem = info.get("memory_percent") or 0.0
            if pid is not None:
                procs.append((mem, pid, name))
        except Exception:
            continue
    procs.sort(key=lambda x: x[0], reverse=True)
    lines = [f"{pid:>6}  {name:<30} mem={mem:.1f}%" for mem, pid, name in procs[:60]]
    return "\n".join(lines) if lines else "(no processes)"


def kill_process(pid: int) -> str:
    try:
        p = psutil.Process(int(pid))
        name = p.name()
        p.terminate()
        return f"Terminated process {pid} ({name})"
    except Exception as e:
        return f"Error: {e}"


def system_info() -> str:
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    return (
        f"CPU: {cpu}%\n"
        f"RAM: {mem.percent}% used ({mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB)\n"
        f"Disk C: {disk.percent}% used ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)"
    )


def shutdown_or_restart(action: str) -> str:
    """action: 'shutdown' or 'restart'"""
    cmd = "shutdown /s /t 60" if action == "shutdown" else "shutdown /r /t 60"
    subprocess.run(cmd, shell=True)
    return f"System will {action} in 60 seconds. Run 'shutdown /a' to cancel."


def _clean_text(s: str) -> str:
    """Strip mojibake/replacement chars and normalize unicode to ASCII-safe output."""
    s = (s.replace("\ufffd", "").replace("\uffff", "").replace("\x00", "")
         .replace("\u201c", '"').replace("\u201d", '"')
         .replace("\u2018", "'").replace("\u2019", "'")
         .replace("\u2013", "-").replace("\u2014", "-")
         .replace("\u2122", "").replace("\u00ae", "").replace("\u00a9", "")
         .replace("\u2026", "...").replace("\u00a0", " "))
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    return s.strip()


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo and return titles, URLs, and snippets."""
    try:
        count = max(1, min(int(max_results), 10))
        results = list(DDGS().text(query, max_results=count))
        if not results:
            return f"No results found for query: '{query}'"
        formatted = []
        for i, r in enumerate(results, 1):
            title = _clean_text(r.get("title", "No Title"))
            url = r.get("href") or r.get("link", "")
            snippet = _clean_text(r.get("body") or r.get("snippet", ""))
            formatted.append(f"{i}. [{title}]({url})\n   {snippet}")
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Error during web search: {e}"


def read_webpage(url: str, max_chars: int = 4000) -> str:
    """Fetch a web page, strip boilerplate, and return clean readable text."""
    if not (url.startswith("http://") or url.startswith("https://")):
        return "Error: URL must begin with http:// or https://"
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        response = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg", "iframe"]):
            tag.decompose()

        title = _clean_text(soup.title.string.strip() if (soup.title and soup.title.string) else "(No title)")
        lines = [_clean_text(line) for line in soup.get_text(separator="\n").splitlines()]
        body_text = "\n".join(line for line in lines if line)
        content = f"Title: {title}\nURL: {url}\n\n{body_text}"

        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n... [output truncated at {max_chars} chars]"
        return content
    except Exception as e:
        return f"Error reading webpage {url}: {e}"

# ---- WhatsApp Tools (connected via local whatsapp-bridge on port 3001) ----
WA_BRIDGE_URL = os.environ.get("WA_BRIDGE_URL", "http://127.0.0.1:3001")


def whatsapp_status() -> str:
    """Check WhatsApp bridge connection status."""
    try:
        r = httpx.get(f"{WA_BRIDGE_URL}/status", timeout=5)
        data = r.json()
        if data.get("ready"):
            return "WhatsApp is connected and active."
        if data.get("qr_pending"):
            return (
                "WhatsApp bridge is running, but phone is not linked yet. "
                "The user needs to scan the QR code displayed in the bridge terminal."
            )
        return f"WhatsApp status: {data}"
    except Exception as e:
        return f"WhatsApp bridge offline or unreachable ({e}). Start the bridge service on port 3001."


def whatsapp_list_chats(limit: int = 15) -> str:
    """List recent WhatsApp chats with last message and unread count."""
    try:
        r = httpx.get(f"{WA_BRIDGE_URL}/chats?limit={limit}", timeout=10)
        if r.status_code != 200:
            return f"WhatsApp Bridge error ({r.status_code}): {r.text}"
        data = r.json()
        chats = data.get("chats", [])
        if not chats:
            return "No recent WhatsApp chats found."
        lines = [f"Found {len(chats)} WhatsApp chats:"]
        for c in chats:
            unread = f" [{c['unreadCount']} unread]" if c.get("unreadCount") else ""
            last = c.get("lastMessage")
            last_snippet = f" | Last: '{last.get('body', '')}'" if last and last.get("body") else ""
            lines.append(f"- {c['name']} (ID: {c['id']}){unread}{last_snippet}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing WhatsApp chats: {e}"


def whatsapp_search_chats(query: str) -> str:
    """Search WhatsApp chats or contacts by name or phone number."""
    try:
        r = httpx.get(f"{WA_BRIDGE_URL}/search", params={"q": query}, timeout=10)
        if r.status_code != 200:
            return f"WhatsApp Bridge error ({r.status_code}): {r.text}"
        data = r.json()
        results = data.get("results", [])
        if not results:
            return f"No WhatsApp chats found matching '{query}'."
        lines = [f"Found {len(results)} matches for '{query}':"]
        for c in results:
            lines.append(f"- {c['name']} (ID: {c['id']})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching WhatsApp chats: {e}"


def whatsapp_read_messages(chat_id: str, limit: int = 10) -> str:
    """Read recent messages from a specific WhatsApp chat."""
    try:
        r = httpx.get(f"{WA_BRIDGE_URL}/chats/{chat_id}/messages?limit={limit}", timeout=10)
        if r.status_code != 200:
            return f"WhatsApp Bridge error ({r.status_code}): {r.text}"
        data = r.json()
        chat_name = data.get("chatName", chat_id)
        messages = data.get("messages", [])
        if not messages:
            return f"No messages found in chat with {chat_name}."
        lines = [f"Recent messages in chat with {chat_name}:"]
        for m in messages:
            sender = "Me" if m.get("fromMe") else chat_name
            body = m.get("body", "(media/empty)")
            t = m.get("time", "")[:19].replace("T", " ")
            lines.append(f"[{t}] {sender}: {body}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading WhatsApp messages: {e}"


def whatsapp_send_message(chat_id: str, message: str) -> str:
    """Send a WhatsApp message to a chat ID or contact."""
    try:
        r = httpx.post(f"{WA_BRIDGE_URL}/send", json={"chatId": chat_id, "message": message}, timeout=15)
        if r.status_code != 200:
            return f"WhatsApp Bridge error ({r.status_code}): {r.text}"
        data = r.json()
        return f"Successfully sent WhatsApp message to {data.get('chatName', chat_id)}: '{message}'"
    except Exception as e:
        return f"Error sending WhatsApp message: {e}"


# ---- Memory tools (injected at runtime by poller.py with DB context) ----
# These schemas are registered with the LLM so it knows the tools exist.
# The actual implementations are closures created in poller.py and injected
# into Session._extra_fns — they are NOT in TOOL_FUNCTIONS below.

MEMORY_TOOL_SCHEMAS = [
    {
        "name": "remember",
        "description": (
            "Persistently store a fact, user preference, or workflow note that should "
            "be remembered across conversations. Use a short descriptive key (e.g. "
            "'preferred_browser', 'work_folder', 'daily_backup_cmd')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short identifier for the memory"},
                "content": {"type": "string", "description": "The information to remember"},
                "category": {
                    "type": "string",
                    "description": "Optional category label (e.g. 'preference', 'workflow', 'fact')",
                    "default": "general",
                },
            },
            "required": ["key", "content"],
        },
    },
    {
        "name": "recall",
        "description": (
            "Retrieve stored memories. Omit all parameters to list every memory. "
            "Provide 'key' to look up one specific memory. "
            "Provide 'category' to filter by category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Exact key to retrieve (optional)"},
                "category": {"type": "string", "description": "Filter by category (optional)"},
            },
        },
    },
    {
        "name": "forget",
        "description": "Delete a stored memory by its key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key of the memory to delete"},
            },
            "required": ["key"],
        },
    },
]


# ---- Goal / Autonomous tool schemas (injected at runtime by poller.py) ----
# Implementations live in autonomous.py and are injected via Session._extra_fns.
GOAL_TOOL_SCHEMAS = [
    {
        "name": "schedule_goal",
        "description": (
            "Create a persistent autonomous goal that the agent will execute on a schedule "
            "or when a condition is met. Examples: monitor disk space hourly, summarize downloads "
            "every morning, alert when CPU exceeds 90%%. Use cron (standard 5-field expression) "
            "or condition_ps (a PowerShell one-liner returning True/False)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title":        {"type": "string", "description": "Short name for the goal"},
                "description":  {"type": "string", "description": "What the agent should do when triggered"},
                "cron":         {"type": "string", "description": "Cron schedule, e.g. '0 9 * * *' for daily 9am"},
                "condition_ps": {"type": "string", "description": "PowerShell expression that returns $true to trigger"},
                "priority":     {"type": "integer", "description": "Priority 1-10 (10=highest), default 5"},
            },
            "required": ["title", "description"],
        },
    },
    {
        "name": "list_goals",
        "description": "List all active autonomous goals with their schedules, conditions, and run counts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_goal",
        "description": "Cancel an active autonomous goal by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {"goal_id": {"type": "string", "description": "UUID of the goal to cancel"}},
            "required": ["goal_id"],
        },
    },
    {
        "name": "complete_goal",
        "description": "Mark an autonomous goal as completed.",
        "input_schema": {
            "type": "object",
            "properties": {"goal_id": {"type": "string", "description": "UUID of the goal to complete"}},
            "required": ["goal_id"],
        },
    },
]


# ---- Tool schemas exposed to the LLM ----
# Memory and goal tool schemas are prepended so the model sees them.
# Their implementations are injected at runtime (see poller.py).
TOOL_SCHEMAS = MEMORY_TOOL_SCHEMAS + GOAL_TOOL_SCHEMAS + [
    {
        "name": "run_powershell",
        "description": "Run a PowerShell command on the PC and return its output. Use for anything not covered by a more specific tool.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The PowerShell command to run"}},
            "required": ["command"],
        },
    },
    {
        "name": "open_application",
        "description": "Open/launch an application by name, e.g. 'notepad', 'chrome', 'calc', 'explorer'.",
        "input_schema": {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the text contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write (create or overwrite) a text file with given content.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and folders inside a directory.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "delete_file",
        "description": "Permanently delete a file or folder. DESTRUCTIVE - requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "list_processes",
        "description": "List running processes with PID, name, and memory usage.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "kill_process",
        "description": "Terminate a running process by PID. DESTRUCTIVE - requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {"pid": {"type": "integer"}},
            "required": ["pid"],
        },
    },
    {
        "name": "system_info",
        "description": "Get current CPU, RAM, and disk usage.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "shutdown_or_restart",
        "description": "Shut down or restart the PC after a 60s delay. DESTRUCTIVE - requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["shutdown", "restart"]}},
            "required": ["action"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the live web using DuckDuckGo to find current information, documentation, news, or URLs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search terms or query"},
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-10, default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_webpage",
        "description": "Fetch a webpage URL, strip advertisements/scripts, and return readable text content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The full HTTP or HTTPS URL to read"},
                "max_chars": {
                    "type": "integer",
                    "description": "Max characters to return (default 4000)",
                    "default": 4000,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "whatsapp_status",
        "description": "Check if Gideon's WhatsApp bridge is connected, or if a QR scan is needed.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "whatsapp_list_chats",
        "description": "List recent WhatsApp chats with contact/group names, IDs, unread count, and last message snippet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of chats to retrieve (default 15)",
                    "default": 15,
                },
            },
        },
    },
    {
        "name": "whatsapp_search_chats",
        "description": "Search WhatsApp chats and contacts by name or phone number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Contact name or phone number to find",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "whatsapp_read_messages",
        "description": "Read recent conversation messages from a specific WhatsApp chat ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "The WhatsApp chat ID (e.g. from whatsapp_list_chats or whatsapp_search_chats)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to retrieve (default 10)",
                    "default": 10,
                },
            },
            "required": ["chat_id"],
        },
    },
    {
        "name": "whatsapp_send_message",
        "description": "Send a WhatsApp message to a specific contact or chat ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "The recipient's WhatsApp chat ID or phone number",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to send",
                },
            },
            "required": ["chat_id", "message"],
        },
    },
]

TOOL_FUNCTIONS = {
    "run_powershell": run_powershell,
    "open_application": open_application,
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "delete_file": delete_file,
    "list_processes": list_processes,
    "kill_process": kill_process,
    "system_info": system_info,
    "shutdown_or_restart": shutdown_or_restart,
    "web_search": web_search,
    "read_webpage": read_webpage,
    "whatsapp_status": whatsapp_status,
    "whatsapp_list_chats": whatsapp_list_chats,
    "whatsapp_search_chats": whatsapp_search_chats,
    "whatsapp_read_messages": whatsapp_read_messages,
    "whatsapp_send_message": whatsapp_send_message,
}

