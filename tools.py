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
DESTRUCTIVE_TOOLS = {"delete_file", "kill_process", "shutdown_or_restart", "email_send", "whatsapp_send_message", "close_window"}

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
    except FileNotFoundError:
        try:
            subprocess.Popen(app_name, shell=True)
            return f"Launched {app_name}"
        except FileNotFoundError:
            return f"Application not found: {app_name}"
        except Exception as e2:
            return f"Error launching {app_name}: {e2}"
    except Exception as e:
        return f"Error launching {app_name}: {e}"


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
        # Basic path validation to prevent directory traversal
        if ".." in path or path.startswith("/") or (len(path) > 1 and path[1] == ":"):
            return "Error: Invalid path. Relative paths within the current directory are required."
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
        # Basic path validation to prevent directory traversal
        if ".." in path or path.startswith("/") or (len(path) > 1 and path[1] == ":"):
            return "Error: Invalid path. Relative paths within the current directory are required."
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
        # Basic path validation to prevent directory traversal
        if ".." in path or path.startswith("/") or (len(path) > 1 and path[1] == ":"):
            return "Error: Invalid path. Relative paths within the current directory are required."
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
        # Basic path validation to prevent directory traversal
        if ".." in path or path.startswith("/") or (len(path) > 1 and path[1] == ":"):
            return "Error: Invalid path. Relative paths within the current directory are required."
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
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
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
    except psutil.NoSuchProcess:
        return f"Process {pid} not found (may have already terminated)."
    except psutil.AccessDenied:
        return f"Access denied: cannot terminate process {pid} (insufficient permissions)."
    except ValueError:
        return f"Invalid PID: {pid}"
    except Exception as e:
        return f"Error: {e}"


def system_info() -> str:
    try:
        cpu = psutil.cpu_percent(interval=0.5)
    except Exception:
        cpu = 0
    try:
        mem = psutil.virtual_memory()
    except Exception:
        mem = type('obj', (object,), {'percent': 0, 'used': 0, 'total': 1})()
    try:
        disk = psutil.disk_usage("C:\\")
    except Exception:
        disk = type('obj', (object,), {'percent': 0, 'used': 0, 'total': 1})()
    
    return (
        f"CPU: {cpu}%\n"
        f"RAM: {mem.percent}% used ({mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB)\n"
        f"Disk C: {disk.percent}% used ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)"
    )


def take_screenshot(filename: str = "screenshot.png") -> str:
    """Capture a screenshot of the primary monitor and save it to a file."""
    try:
        import pyautogui
        # Validate filename to prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            return "Error: Invalid filename. Only a simple filename (no path) is allowed."
        
        # Ensure .png extension
        if not filename.lower().endswith(".png"):
            filename = filename + ".png"
        
        # Capture screenshot
        screenshot = pyautogui.screenshot()
        screenshot.save(filename)
        return f"Screenshot saved to {filename}"
    except ImportError:
        return "Error: pyautogui package not installed. Run: python -m pip install pyautogui"
    except Exception as e:
        return f"Error taking screenshot: {e}"


def get_clipboard_text() -> str:
    """Read the current text content from the system clipboard."""
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            return "Clipboard is empty or contains non-text content."
        return text
    except ImportError:
        return "Error: pyperclip package not installed. Run: python -m pip install pyperclip"
    except Exception as e:
        return f"Error reading clipboard: {e}"


def set_clipboard_text(text: str) -> str:
    """Set the system clipboard to the provided text."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return f"Copied {len(text)} characters to clipboard."
    except ImportError:
        return "Error: pyperclip package not installed. Run: python -m pip install pyperclip"
    except Exception as e:
        return f"Error setting clipboard: {e}"


def list_windows() -> str:
    """List all visible windows with their titles and handles."""
    try:
        import pygetwindow as gw
        windows = gw.getAllWindows()
        if not windows:
            return "No windows found."
        
        lines = ["Active windows:"]
        for win in windows:
            title = win.title or "(Untitled)"
            if title:  # Only show windows with titles
                lines.append(f"- {title}")
        return "\n".join(lines)
    except ImportError:
        return "Error: pygetwindow package not installed. Run: python -m pip install pygetwindow"
    except Exception as e:
        return f"Error listing windows: {e}"


def minimize_window(title: str) -> str:
    """Minimize a window by its title (partial match)."""
    try:
        import pygetwindow as gw
        windows = gw.getWindowsWithTitle(title)
        if not windows:
            return f"No window found matching '{title}'"
        
        for win in windows:
            win.minimize()
        return f"Minimized {len(windows)} window(s) matching '{title}'"
    except ImportError:
        return "Error: pygetwindow package not installed. Run: python -m pip install pygetwindow"
    except Exception as e:
        return f"Error minimizing window: {e}"


def maximize_window(title: str) -> str:
    """Maximize a window by its title (partial match)."""
    try:
        import pygetwindow as gw
        windows = gw.getWindowsWithTitle(title)
        if not windows:
            return f"No window found matching '{title}'"
        
        for win in windows:
            win.maximize()
        return f"Maximized {len(windows)} window(s) matching '{title}'"
    except ImportError:
        return "Error: pygetwindow package not installed. Run: python -m pip install pygetwindow"
    except Exception as e:
        return f"Error maximizing window: {e}"


def close_window(title: str) -> str:
    """Close a window by its title (partial match). DESTRUCTIVE - requires user confirmation."""
    try:
        import pygetwindow as gw
        windows = gw.getWindowsWithTitle(title)
        if not windows:
            return f"No window found matching '{title}'"
        
        for win in windows:
            win.close()
        return f"Closed {len(windows)} window(s) matching '{title}'"
    except ImportError:
        return "Error: pygetwindow package not installed. Run: python -m pip install pygetwindow"
    except Exception as e:
        return f"Error closing window: {e}"


# ---- Google Calendar Tools ----
def _get_calendar_credentials():
    """Get Google Calendar API credentials from environment variables."""
    import json
    
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not credentials_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON must be configured in .env to use calendar tools.")
    
    try:
        return json.loads(credentials_json)
    except json.JSONDecodeError:
        raise ValueError("GOOGLE_CREDENTIALS_JSON must be valid JSON.")


def list_calendar_events(max_results: int = 10, days_ahead: int = 7) -> str:
    """List upcoming Google Calendar events."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from datetime import datetime, timedelta
        
        credentials_dict = _get_calendar_credentials()
        
        # Create credentials from dict
        credentials = Credentials.from_authorized_user_info(credentials_dict)
        
        # Build the service
        service = build('calendar', 'v3', credentials=credentials)
        
        # Calculate time range
        now = datetime.utcnow()
        time_max = now + timedelta(days=days_ahead)
        
        # Call the Calendar API
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now.isoformat() + 'Z',
            timeMax=time_max.isoformat() + 'Z',
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return f"No upcoming events found in the next {days_ahead} days."
        
        lines = [f"Found {len(events)} upcoming events in the next {days_ahead} days:"]
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            title = event.get('summary', '(No title)')
            lines.append(f"- {title} at {start}")
        
        return "\n".join(lines)
    except ValueError as e:
        return f"Calendar configuration error: {e}"
    except ImportError:
        return "Error: Google Calendar packages not installed. Run: python -m pip install google-api-python-client google-auth-oauthlib"
    except Exception as e:
        return f"Error listing calendar events: {e}"


# ---- Media Control Tools ----
def media_play_pause() -> str:
    """Toggle play/pause for the currently active media application."""
    try:
        import pywinauto.keyboard
        # Send Play/Pause media key (VK_MEDIA_PLAY_PAUSE = 0xB3)
        pywinauto.keyboard.send_keys('{VK_MEDIA_PLAY_PAUSE}')
        return "Toggled play/pause"
    except ImportError:
        return "Error: pywinauto package not installed. Run: python -m pip install pywinauto"
    except Exception as e:
        return f"Error toggling play/pause: {e}"


def media_next() -> str:
    """Skip to the next track."""
    try:
        import pywinauto.keyboard
        # Send Next media key (VK_MEDIA_NEXT_TRACK = 0xB0)
        pywinauto.keyboard.send_keys('{VK_MEDIA_NEXT_TRACK}')
        return "Skipped to next track"
    except ImportError:
        return "Error: pywinauto package not installed. Run: python -m pip install pywinauto"
    except Exception as e:
        return f"Error skipping to next track: {e}"


def media_previous() -> str:
    """Go to the previous track."""
    try:
        import pywinauto.keyboard
        # Send Previous media key (VK_MEDIA_PREV_TRACK = 0xB1)
        pywinauto.keyboard.send_keys('{VK_MEDIA_PREV_TRACK}')
        return "Went to previous track"
    except ImportError:
        return "Error: pywinauto package not installed. Run: python -m pip install pywinauto"
    except Exception as e:
        return f"Error going to previous track: {e}"


def set_volume(level: int) -> str:
    """Set system volume level (0-100)."""
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        
        if level < 0 or level > 100:
            return "Error: Volume level must be between 0 and 100"
        
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        
        # Set volume (0.0 to 1.0)
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        return f"Set system volume to {level}%"
    except ImportError:
        return "Error: pycaw package not installed. Run: python -m pip install pycaw"
    except Exception as e:
        return f"Error setting volume: {e}"


def get_volume() -> str:
    """Get current system volume level."""
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        
        # Get volume (0.0 to 1.0)
        level = volume.GetMasterVolumeLevelScalar()
        return f"Current system volume: {int(level * 100)}%"
    except ImportError:
        return "Error: pycaw package not installed. Run: python -m pip install pycaw"
    except Exception as e:
        return f"Error getting volume: {e}"


# ---- Smart Home Integration (Philips Hue) ----
def _get_hue_credentials():
    """Get Philips Hue bridge credentials from environment variables."""
    bridge_ip = os.environ.get("HUE_BRIDGE_IP")
    username = os.environ.get("HUE_USERNAME")
    
    if not bridge_ip or not username:
        raise ValueError("HUE_BRIDGE_IP and HUE_USERNAME must be configured in .env to use Hue tools.")
    
    return bridge_ip, username


def hue_list_lights() -> str:
    """List all Philips Hue lights with their current state."""
    try:
        import requests
        
        bridge_ip, username = _get_hue_credentials()
        url = f"http://{bridge_ip}/api/{username}/lights"
        
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        lights = response.json()
        if not lights:
            return "No Hue lights found."
        
        lines = [f"Found {len(lights)} Hue lights:"]
        for light_id, light_data in lights.items():
            name = light_data.get("name", "Unknown")
            state = light_data.get("state", {})
            on = state.get("on", False)
            brightness = state.get("bri", 0)
            brightness_pct = int((brightness / 254) * 100) if brightness else 0
            status = f"ON ({brightness_pct}%)" if on else "OFF"
            lines.append(f"- {name} (ID: {light_id}): {status}")
        
        return "\n".join(lines)
    except ValueError as e:
        return f"Hue configuration error: {e}"
    except ImportError:
        return "Error: requests package not installed. Run: python -m pip install requests"
    except Exception as e:
        return f"Error listing Hue lights: {e}"


def hue_set_light(light_id: str, on: bool = None, brightness: int = None) -> str:
    """Control a Philips Hue light (turn on/off, set brightness)."""
    try:
        import requests
        
        bridge_ip, username = _get_hue_credentials()
        url = f"http://{bridge_ip}/api/{username}/lights/{light_id}/state"
        
        payload = {}
        if on is not None:
            payload["on"] = on
        if brightness is not None:
            if brightness < 0 or brightness > 100:
                return "Error: Brightness must be between 0 and 100"
            payload["bri"] = int((brightness / 100) * 254)
        
        if not payload:
            return "Error: No changes specified (provide on or brightness)"
        
        response = requests.put(url, json=payload, timeout=5)
        response.raise_for_status()
        
        return f"Successfully updated Hue light {light_id}"
    except ValueError as e:
        return f"Hue configuration error: {e}"
    except ImportError:
        return "Error: requests package not installed. Run: python -m pip install requests"
    except Exception as e:
        return f"Error setting Hue light: {e}"


def shutdown_or_restart(action: str) -> str:
    """action: 'shutdown' or 'restart'"""
    cmd = "shutdown /s /t 60" if action == "shutdown" else "shutdown /r /t 60"
    subprocess.run(cmd, shell=True)
    return f"System will {action} in 60 seconds. Run 'shutdown /a' to cancel."


def _clean_text(s: str) -> str:
    """Strip mojibake/replacement chars and normalize unicode to clean text."""
    if not s:
        return ""
    s = (s.replace("\ufffd", "").replace("\uffff", "").replace("\x00", "")
         .replace("\u201c", '"').replace("\u201d", '"')
         .replace("\u2018", "'").replace("\u2019", "'")
         .replace("\u2013", "-").replace("\u2014", "-")
         .replace("\u2122", "").replace("\u00ae", "").replace("\u00a9", "")
         .replace("\u2026", "...").replace("\u00a0", " "))
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    # Remove surrogate or non-printable astral characters that break Windows console
    s = re.sub(r"[^\x00-\x7F\u00A0-\u024F\u1E00-\u1EFF]", " ", s)
    return re.sub(r" +", " ", s).strip()


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
    except (ConnectionError, TimeoutError) as e:
        return f"Network error during web search: {e}"
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
    except httpx.HTTPStatusError as e:
        return f"HTTP error reading webpage {url}: {e.response.status_code}"
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        return f"Network error reading webpage {url}: {e}"
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
    except httpx.ConnectError:
        return f"WhatsApp bridge offline or unreachable. Start the bridge service on port 3001."
    except httpx.TimeoutException:
        return f"WhatsApp bridge timed out. Check if the bridge is running on port 3001."
    except Exception as e:
        return f"WhatsApp bridge error: {e}. Start the bridge service on port 3001."


def whatsapp_list_contacts(limit: int = 30, query: str = "") -> str:
    """List WhatsApp contacts saved on your phone with names, phone numbers, and IDs."""
    try:
        r = httpx.get(f"{WA_BRIDGE_URL}/contacts", timeout=12)
        if r.status_code != 200:
            return f"WhatsApp Bridge error ({r.status_code}): {r.text}"
        data = r.json()
        contacts = data.get("contacts", [])
        if not contacts:
            return "No saved WhatsApp contacts found."

        if query:
            q = query.lower().strip()
            contacts = [
                c for c in contacts
                if q in (c.get("name") or "").lower() or q in (c.get("number") or "").lower()
            ]
            if not contacts:
                return f"No WhatsApp contacts found matching '{query}'."

        seen = set()
        unique = []
        for c in contacts:
            name = (c.get("name") or "").strip()
            num = (c.get("number") or "").strip()
            cid = c.get("id") or (f"{num}@c.us" if num else "")
            key = cid or name
            if key and key not in seen:
                seen.add(key)
                unique.append(c)

        unique = unique[:limit]
        lines = [f"Found {len(unique)} WhatsApp contacts:"]
        for c in unique:
            name = c.get("name") or "Unknown"
            num = c.get("number") or ""
            cid = c.get("id") or ""
            saved = " (Saved Contact)" if c.get("isMyContact") else ""
            lines.append(f"- {name}: {num} [ID: {cid}]{saved}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing WhatsApp contacts: {e}"


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


def whatsapp_call(recipient: str) -> str:
    """Initiate a WhatsApp voice/VoIP call to a contact name or phone number.
    On mobile, this triggers a direct native WhatsApp VoIP call.
    Resolves contact names and phone numbers via WhatsApp contacts.
    """
    cleaned = recipient.replace("on whatsapp", "").replace("via whatsapp", "").replace("whatsapp", "").strip()
    target_number = ""
    contact_name = cleaned

    digits_only = re.sub(r"[\s\-\(\)\.]", "", cleaned)
    if re.match(r"^\+?[0-9]{5,16}$", digits_only):
        target_number = digits_only if digits_only.startswith("+") else ("+" + digits_only if len(digits_only) > 8 else digits_only)
        # Attempt to find if there is an associated name in WhatsApp contacts
        try:
            r = httpx.get(f"{WA_BRIDGE_URL}/contacts", timeout=5)
            if r.status_code == 200:
                contacts = r.json().get("contacts", [])
                num_clean = digits_only.replace("+", "")
                for c in contacts:
                    c_num = (c.get("number") or c.get("id") or "").split("@")[0]
                    if num_clean.endswith(c_num) or c_num.endswith(num_clean) or (len(num_clean) >= 7 and num_clean[-7:] in c_num):
                        found_name = c.get("name") or c.get("pushname")
                        if found_name:
                            contact_name = found_name
                            break
        except Exception:
            pass
    else:
        try:
            r = httpx.get(f"{WA_BRIDGE_URL}/contacts", timeout=10)
            if r.status_code == 200:
                contacts = r.json().get("contacts", [])
                q = cleaned.lower()
                for c in contacts:
                    name = (c.get("name") or c.get("pushname") or "").lower()
                    num = c.get("number") or ""
                    cid = c.get("id") or ""
                    if q in name or name in q:
                        contact_name = c.get("name") or c.get("pushname") or cleaned
                        target_number = num or cid.split("@")[0]
                        if target_number and not target_number.startswith("+") and len(target_number) > 8:
                            target_number = "+" + target_number
                        break
        except Exception:
            pass

    action_tag = f"[ACTION:CALL_WHATSAPP:name={contact_name};phone={target_number}]"
    if target_number:
        return f"{action_tag}\nCalling {contact_name} on WhatsApp ({target_number}). Triggering WhatsApp call..."
    else:
        return f"{action_tag}\nCalling {contact_name} on WhatsApp. Triggering WhatsApp call..."


def make_phone_call(recipient: str) -> str:
    """Initiate a phone call to a contact name or phone number.
    By default, routes calls to WhatsApp voice/VoIP.
    If cellular or standard dialer is explicitly requested, opens the system dialer.
    """
    lower = recipient.lower()
    is_explicit_cellular = any(w in lower for w in ["cellular", "cell call", "sim", "dialer", "regular call", "normal call"])
    if not is_explicit_cellular:
        return whatsapp_call(recipient)

    cleaned = recipient.strip()
    target_number = ""
    contact_name = cleaned

    # Check if recipient is already a phone number
    digits_only = re.sub(r"[\s\-\(\)\.]", "", cleaned)
    if re.match(r"^\+?[0-9]{5,16}$", digits_only):
        target_number = digits_only
    else:
        # Search WhatsApp contacts for matching name
        try:
            r = httpx.get(f"{WA_BRIDGE_URL}/contacts", timeout=10)
            if r.status_code == 200:
                contacts = r.json().get("contacts", [])
                q = cleaned.lower()
                for c in contacts:
                    name = (c.get("name") or c.get("pushname") or "").lower()
                    num = c.get("number") or ""
                    cid = c.get("id") or ""
                    if q in name or name in q:
                        contact_name = c.get("name") or c.get("pushname") or cleaned
                        target_number = num or cid.split("@")[0]
                        if target_number and not target_number.startswith("+") and len(target_number) > 8:
                            target_number = "+" + target_number
                        break
        except Exception:
            pass

    if not target_number:
        return f"Could not find a phone number for '{recipient}'. Please specify the phone number directly (e.g. 'call +123456789')."

    tel_uri = f"tel:{target_number}"

    # If running on Windows PC, trigger default system dialer / Phone Link
    try:
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", tel_uri], shell=True)
    except Exception:
        pass

    return f"[ACTION:CALL:{tel_uri}]\nCalling {contact_name} ({target_number}). Opening phone dialer..."


# ---- Email Tools (IMAP / SMTP) ----
def _get_email_credentials():
    address = os.environ.get("EMAIL_ADDRESS")
    password = os.environ.get("EMAIL_PASSWORD")
    imap_server = os.environ.get("EMAIL_IMAP_SERVER", "imap.gmail.com")
    smtp_server = os.environ.get("EMAIL_SMTP_SERVER", "smtp.gmail.com")
    imap_port = int(os.environ.get("EMAIL_PORT_IMAP", "993"))
    smtp_port = int(os.environ.get("EMAIL_PORT_SMTP", "587"))

    if not address or not password:
        raise ValueError("EMAIL_ADDRESS and EMAIL_PASSWORD must be configured in .env to use email tools.")
    return address, password, imap_server, smtp_server, imap_port, smtp_port


def email_list_unread(limit: int = 5) -> str:
    """List recent unread emails with sender, subject, date, and email ID."""
    import imaplib
    import email
    from email.header import decode_header

    try:
        address, password, imap_server, _, imap_port, _ = _get_email_credentials()
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(address, password)
        mail.select("INBOX")

        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
            return "No unread emails found in INBOX."

        email_ids = messages[0].split()
        email_ids = email_ids[-max(1, min(int(limit), 20)):]  # take the most recent
        email_ids.reverse()

        results = [f"Found {len(email_ids)} unread email(s):"]

        for eid in email_ids:
            res, msg_data = mail.fetch(eid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if res != "OK":
                continue
            raw_header = msg_data[0][1]
            msg = email.message_from_bytes(raw_header)

            # Decode Subject
            subject, encoding = decode_header(msg.get("Subject", "(No Subject)"))[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8", errors="replace")

            sender = msg.get("From", "(Unknown Sender)")
            date_str = msg.get("Date", "")
            id_str = eid.decode() if isinstance(eid, bytes) else str(eid)

            results.append(f"- [ID: {id_str}] From: {sender}\n  Subject: {subject}\n  Date: {date_str}")

        mail.logout()
        return "\n".join(results)
    except ValueError as e:
        return f"Email configuration error: {e}"
    except imaplib.IMAP4.error as e:
        return f"IMAP error: {e}"
    except Exception as e:
        return f"Error listing unread emails: {e}"


def email_read(email_id: str) -> str:
    """Read full details and text body of an email by its ID."""
    import imaplib
    import email
    from email.header import decode_header

    try:
        address, password, imap_server, _, imap_port, _ = _get_email_credentials()
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(address, password)
        mail.select("INBOX")

        res, msg_data = mail.fetch(email_id.encode() if isinstance(email_id, str) else email_id, "(RFC822)")
        if res != "OK" or not msg_data or not msg_data[0]:
            mail.logout()
            return f"Could not find email with ID: {email_id}"

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject, encoding = decode_header(msg.get("Subject", "(No Subject)"))[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding or "utf-8", errors="replace")

        sender = msg.get("From", "(Unknown Sender)")
        to = msg.get("To", "(Unknown Recipient)")
        date_str = msg.get("Date", "")

        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get("Content-Disposition"))
                if ctype == "text/plain" and "attachment" not in cdispo:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
                elif ctype == "text/html" and not body and "attachment" not in cdispo:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html_text = payload.decode(charset, errors="replace")
                        soup = BeautifulSoup(html_text, "html.parser")
                        body = soup.get_text(separator="\n").strip()
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")

        mail.logout()

        clean_body = _clean_text(body)
        if len(clean_body) > 3500:
            clean_body = clean_body[:3500] + "\n... [body truncated at 3500 chars]"

        return (
            f"Email ID: {email_id}\n"
            f"From: {_clean_text(sender)}\n"
            f"To: {_clean_text(to)}\n"
            f"Date: {date_str}\n"
            f"Subject: {_clean_text(subject)}\n\n"
            f"--- Content ---\n{clean_body if clean_body else '(Empty body)'}"
        )
    except ValueError as e:
        return f"Email configuration error: {e}"
    except imaplib.IMAP4.error as e:
        return f"IMAP error: {e}"
    except Exception as e:
        return f"Error reading email {email_id}: {e}"


def email_search(query: str, limit: int = 5) -> str:
    """Search inbox emails by keyword, sender, or subject."""
    import imaplib
    import email
    from email.header import decode_header

    try:
        address, password, imap_server, _, imap_port, _ = _get_email_credentials()
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(address, password)
        mail.select("INBOX")

        # Sanitize query to prevent IMAP injection
        clean_q = query.replace('"', '').replace('\\', '').strip()[:100]
        if not clean_q:
            return "Error: Search query is empty after sanitization."
        
        # Search in SUBJECT, FROM, or TEXT
        search_criteria = f'(OR (OR SUBJECT "{clean_q}" FROM "{clean_q}") BODY "{clean_q}")'
        status, messages = mail.search(None, search_criteria)

        if status != "OK" or not messages[0]:
            # Fallback simple search
            status, messages = mail.search(None, f'TEXT "{clean_q}"')

        if status != "OK" or not messages[0]:
            mail.logout()
            return f"No emails found matching query: '{query}'"

        email_ids = messages[0].split()
        email_ids = email_ids[-max(1, min(int(limit), 20)):]
        email_ids.reverse()

        results = [f"Found {len(email_ids)} email(s) matching '{query}':"]

        for eid in email_ids:
            res, msg_data = mail.fetch(eid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if res != "OK":
                continue
            raw_header = msg_data[0][1]
            msg = email.message_from_bytes(raw_header)

            subject, encoding = decode_header(msg.get("Subject", "(No Subject)"))[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8", errors="replace")

            sender = msg.get("From", "(Unknown Sender)")
            date_str = msg.get("Date", "")
            id_str = eid.decode() if isinstance(eid, bytes) else str(eid)

            results.append(f"- [ID: {id_str}] From: {sender}\n  Subject: {subject}\n  Date: {date_str}")

        mail.logout()
        return "\n".join(results)
    except ValueError as e:
        return f"Email configuration error: {e}"
    except imaplib.IMAP4.error as e:
        return f"IMAP error: {e}"
    except Exception as e:
        return f"Error searching emails: {e}"


def email_send(to_email: str, subject: str, body: str) -> str:
    """Send an email via SMTP. DESTRUCTIVE - requires user confirmation."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        address, password, _, smtp_server, _, smtp_port = _get_email_credentials()

        msg = MIMEMultipart()
        msg["From"] = address
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        server = smtplib.SMTP(smtp_server, smtp_port, timeout=20)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(address, password)
        server.sendmail(address, [to_email], msg.as_string())
        server.quit()

        return f"Successfully sent email to {to_email} with subject: '{subject}'"
    except ValueError as e:
        return f"Email configuration error: {e}"
    except smtplib.SMTPAuthenticationError:
        return "SMTP authentication failed. Check your email credentials."
    except smtplib.SMTPException as e:
        return f"SMTP error: {e}"
    except Exception as e:
        return f"Error sending email: {e}"


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
        "name": "take_screenshot",
        "description": "Capture a screenshot of the primary monitor and save it to a PNG file in the current directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Output filename (default 'screenshot.png'). Only a simple filename, no path allowed.",
                    "default": "screenshot.png",
                },
            },
        },
    },
    {
        "name": "get_clipboard_text",
        "description": "Read the current text content from the system clipboard.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_clipboard_text",
        "description": "Set the system clipboard to the provided text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to copy to the clipboard",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_windows",
        "description": "List all visible windows with their titles.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "minimize_window",
        "description": "Minimize a window by its title (partial match).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Window title to minimize (partial match supported)",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "maximize_window",
        "description": "Maximize a window by its title (partial match).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Window title to maximize (partial match supported)",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "close_window",
        "description": "Close a window by its title (partial match). DESTRUCTIVE - requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Window title to close (partial match supported)",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_calendar_events",
        "description": "List upcoming Google Calendar events for the next few days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of events to return (default 10)",
                    "default": 10,
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days ahead to look for events (default 7)",
                    "default": 7,
                },
            },
        },
    },
    {
        "name": "media_play_pause",
        "description": "Toggle play/pause for the currently active media application (Spotify, YouTube, etc.).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "media_next",
        "description": "Skip to the next track in the currently active media application.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "media_previous",
        "description": "Go to the previous track in the currently active media application.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_volume",
        "description": "Set the system master volume level (0-100).",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "integer",
                    "description": "Volume level from 0 to 100",
                },
            },
            "required": ["level"],
        },
    },
    {
        "name": "get_volume",
        "description": "Get the current system master volume level.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "hue_list_lights",
        "description": "List all Philips Hue lights with their current state (on/off, brightness).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "hue_set_light",
        "description": "Control a Philips Hue light (turn on/off, set brightness 0-100).",
        "input_schema": {
            "type": "object",
            "properties": {
                "light_id": {
                    "type": "string",
                    "description": "The light ID (e.g., '1', '2', etc.)",
                },
                "on": {
                    "type": "boolean",
                    "description": "Turn the light on (true) or off (false)",
                },
                "brightness": {
                    "type": "integer",
                    "description": "Brightness level from 0 to 100",
                },
            },
            "required": ["light_id"],
        },
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
        "name": "whatsapp_list_contacts",
        "description": "List WhatsApp contacts saved on your phone with names, phone numbers, and WhatsApp IDs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of contacts to retrieve (default 30)",
                    "default": 30,
                },
                "query": {
                    "type": "string",
                    "description": "Optional search filter by contact name or phone number",
                },
            },
        },
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
    {
        "name": "email_list_unread",
        "description": "Check and list recent unread emails with sender, subject, date, and ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of unread emails to retrieve (default 5)",
                    "default": 5,
                },
            },
        },
    },
    {
        "name": "email_read",
        "description": "Read the full contents and text body of an email by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to read (from email_list_unread or email_search)",
                },
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "email_search",
        "description": "Search inbox emails by keyword, sender name/address, or subject.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query (e.g. sender name, topic, or keyword)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "email_send",
        "description": "Send an email or reply to an address. DESTRUCTIVE - requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to_email": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "The full text message content to send",
                },
            },
            "required": ["to_email", "subject", "body"],
        },
    },
    {
        "name": "make_phone_call",
        "description": "Initiate a regular phone call to a phone number or contact name. Resolves contact numbers via WhatsApp contacts and opens the phone dialer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "The contact name (e.g. 'Mom', 'Alex') or phone number (e.g. '+1234567890', '0412345678') to call",
                },
            },
            "required": ["recipient"],
        },
    },
    {
        "name": "whatsapp_call",
        "description": "Initiate a direct WhatsApp voice/VoIP call to a contact name or phone number on mobile. Use this when the user asks to call someone on WhatsApp.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "The contact name (e.g. 'Mom', 'Alex') or phone number to call via WhatsApp",
                },
            },
            "required": ["recipient"],
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
    "take_screenshot": take_screenshot,
    "get_clipboard_text": get_clipboard_text,
    "set_clipboard_text": set_clipboard_text,
    "list_windows": list_windows,
    "minimize_window": minimize_window,
    "maximize_window": maximize_window,
    "close_window": close_window,
    "list_calendar_events": list_calendar_events,
    "media_play_pause": media_play_pause,
    "media_next": media_next,
    "media_previous": media_previous,
    "set_volume": set_volume,
    "get_volume": get_volume,
    "hue_list_lights": hue_list_lights,
    "hue_set_light": hue_set_light,
    "shutdown_or_restart": shutdown_or_restart,
    "web_search": web_search,
    "read_webpage": read_webpage,
    "whatsapp_status": whatsapp_status,
    "whatsapp_list_contacts": whatsapp_list_contacts,
    "whatsapp_list_chats": whatsapp_list_chats,
    "whatsapp_search_chats": whatsapp_search_chats,
    "whatsapp_read_messages": whatsapp_read_messages,
    "whatsapp_send_message": whatsapp_send_message,
    "make_phone_call": make_phone_call,
    "whatsapp_call": whatsapp_call,
    "email_list_unread": email_list_unread,
    "email_read": email_read,
    "email_search": email_search,
    "email_send": email_send,
}

