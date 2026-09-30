"""
Windows Background Voice Service for G.I.D.E.O.N.
Uses native sounddevice + SpeechRecognition on Windows.
Listens to your microphone in the background.
Any conversation that includes "Gideon" triggers execution!

Hardened vs. original:
  - Full reconnect loop: mic disconnect / PortAudioError / crash → auto-retries in VOICE_RECONNECT_SEC
  - Max audio buffer cap (VOICE_MAX_BUF_SEC) to prevent runaway RAM growth on long speech
  - TTS process deduplication — kills old PowerShell TTS before starting a new one
  - Rotating structured log via Python logging → voice.log (500 KB, 2 backups) + stdout with timestamps
  - Device probe with graceful fallback on startup (no silent crash if mic missing)
  - Fixed speak_windows() f-string so text is properly sanitised before passing to PowerShell
  - All key constants overridable via .env:
      VOICE_SAMPLE_RATE, VOICE_BLOCK_SIZE, VOICE_SILENCE_SEC,
      VOICE_ENERGY, VOICE_MAX_BUF_SEC, VOICE_RECONNECT_SEC
"""

import logging
import math
import os
import re
import struct
import subprocess
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────────────────────
# Logging — writes to voice.log (rotating 500 KB, 2 backups) AND stdout
# ──────────────────────────────────────────────────────────────

_LOG_FILE = Path(__file__).with_name("voice.log")

_logger = logging.getLogger("gideon.voice")
_logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                          datefmt="%Y-%m-%d %H:%M:%S")

_fh = RotatingFileHandler(_LOG_FILE, maxBytes=500_000, backupCount=2, encoding="utf-8")
_fh.setFormatter(_fmt)
_logger.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
_logger.addHandler(_sh)

log = _logger


# ──────────────────────────────────────────────────────────────
# Constants (all overridable via .env)
# ──────────────────────────────────────────────────────────────

SAMPLE_RATE         = int(os.environ.get("VOICE_SAMPLE_RATE",     "16000"))
BLOCK_SIZE          = int(os.environ.get("VOICE_BLOCK_SIZE",      "1024"))
SILENCE_TIMEOUT_SEC = float(os.environ.get("VOICE_SILENCE_SEC",   "1.4"))
ENERGY_THRESHOLD    = float(os.environ.get("VOICE_ENERGY",        "320"))
MAX_BUFFER_SEC      = float(os.environ.get("VOICE_MAX_BUF_SEC",   "30"))   # discard if longer
RECONNECT_DELAY_SEC = float(os.environ.get("VOICE_RECONNECT_SEC", "5"))    # wait before retry


# ──────────────────────────────────────────────────────────────
# TTS — Windows SAPI via PowerShell (with process deduplication)
# ──────────────────────────────────────────────────────────────

_tts_proc: subprocess.Popen | None = None


def speak_windows(text: str) -> None:
    """Native Windows Speech Synthesis, preferring a British English voice.

    Terminates the previous TTS process before starting a new one to prevent
    stacking multiple PowerShell synthesis processes when Gideon replies quickly.
    """
    global _tts_proc
    try:
        # Kill previous TTS if still running
        if _tts_proc is not None:
            try:
                if _tts_proc.poll() is None:
                    _tts_proc.terminate()
            except Exception:
                pass
            _tts_proc = None

        # Sanitise: strip quotes and newlines so the PS string literal stays valid
        safe = text.replace('"', '').replace("'", "").replace("\n", " ")[:250]
        rate = int(os.environ.get("GIDEON_VOICE_RATE", "1"))

        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Rate = {rate}; "
            "$v = $s.GetInstalledVoices() | Where-Object { "
            "   $_.VoiceInfo.Culture.Name -like 'en-GB*' -or "
            "   $_.VoiceInfo.Name -like '*Hazel*' -or "
            "   $_.VoiceInfo.Name -like '*Sonia*' -or "
            "   $_.VoiceInfo.Name -like '*Libby*' -or "
            "   $_.VoiceInfo.Name -like '*Ryan*' "
            "} | Select-Object -First 1; "
            "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
            f"$s.Speak('{safe}')"
        )
        _tts_proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        log.warning("TTS error: %s", exc)


# ──────────────────────────────────────────────────────────────
# DB helpers — imported lazily inside functions so startup failures
# give a clean error message rather than a bare ImportError.
# ──────────────────────────────────────────────────────────────

def submit_command_to_agent(command_text: str) -> None:
    """Injects a user command into the Neon DB inbox for poller.py to execute."""
    from constants import DEFAULT_SESSION_ID
    from db import get_conn

    client_id = str(uuid.uuid4())
    try:
        with get_conn() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    WITH msg AS (
                        INSERT INTO messages (session_id, role, content, client_id)
                        VALUES (%s, 'user', %s, %s)
                        RETURNING id
                    )
                    INSERT INTO inbox (session_id, body, status)
                    VALUES (%s, %s, 'queued');
                    """,
                    (DEFAULT_SESSION_ID, command_text, client_id,
                     DEFAULT_SESSION_ID, command_text),
                )
        log.info("▶ Queued command: %r", command_text)
    except Exception as exc:
        log.error("DB injection error: %s", exc)


def clear_conversation_session() -> None:
    """Wipes conversation history and resets agent state."""
    from constants import DEFAULT_SESSION_ID
    from db import get_conn

    try:
        with get_conn() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM messages WHERE session_id = %s", (DEFAULT_SESSION_ID,))
                conn.execute("DELETE FROM agent_state WHERE session_id = %s", (DEFAULT_SESSION_ID,))
                conn.execute("DELETE FROM inbox WHERE session_id = %s", (DEFAULT_SESSION_ID,))
        log.info("Conversation cleared. Starting fresh.")
        speak_windows("Conversation cleared. Starting fresh.")
    except Exception as exc:
        log.error("Clear error: %s", exc)


# ──────────────────────────────────────────────────────────────
# Audio helpers
# ──────────────────────────────────────────────────────────────

def calculate_rms(block: bytes) -> float:
    """Calculate Root Mean Square audio volume."""
    count = len(block) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", block)
    sum_sq = sum(s * s for s in shorts)
    return math.sqrt(sum_sq / count)


def probe_input_device() -> dict | None:
    """Return the default input device info dict, or None if no mic available."""
    try:
        import sounddevice as sd  # type: ignore
        dev = sd.query_devices(kind="input")
        if dev:
            return dev
    except Exception as exc:
        log.warning("No input device found: %s", exc)
    return None


# ──────────────────────────────────────────────────────────────
# Core listen loop — one session; raises on mic loss / crash
# ──────────────────────────────────────────────────────────────

def _listen_once() -> None:
    """
    One listen session. Raises any exception (mic unplug, PortAudioError, etc.)
    so the reconnect wrapper in main() can restart automatically.
    """
    import sounddevice as sd  # type: ignore
    import speech_recognition as sr  # type: ignore

    dev = probe_input_device()
    if dev is None:
        raise RuntimeError("No microphone found — will retry.")

    log.info("Input device: %s", dev["name"])

    recognizer = sr.Recognizer()
    audio_buffer: list[bytes] = []
    is_speaking = False
    silence_start: float | None = None
    last_cmd = ""
    last_cmd_time = 0.0

    # Max buffer = MAX_BUFFER_SEC of 16-bit mono audio
    max_buffer_bytes = int(MAX_BUFFER_SEC * SAMPLE_RATE * 2)

    def audio_callback(indata, frames, time_info, status):
        nonlocal is_speaking, silence_start, audio_buffer

        if status:
            log.debug("PortAudio status: %s", status)

        raw_bytes = bytes(indata)
        rms = calculate_rms(raw_bytes)

        if rms > ENERGY_THRESHOLD:
            if not is_speaking:
                is_speaking = True
                audio_buffer = []
                log.debug("Voice detected…")
            total = sum(len(b) for b in audio_buffer)
            if total < max_buffer_bytes:
                audio_buffer.append(raw_bytes)
            silence_start = None
        elif is_speaking:
            audio_buffer.append(raw_bytes)
            if silence_start is None:
                silence_start = time.time()

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        channels=1,
        dtype="int16",
        callback=audio_callback,
    ):
        log.info("[+] Ambient Ear ACTIVE. Say anything with 'Gideon'…")

        while True:
            time.sleep(0.05)

            if not (is_speaking and silence_start is not None):
                continue
            if time.time() - silence_start < SILENCE_TIMEOUT_SEC:
                continue

            # ── Complete utterance captured ─────────────────────────────
            is_speaking = False
            silence_start = None
            full_audio = b"".join(audio_buffer)
            audio_buffer = []

            min_bytes = int(SAMPLE_RATE * 2 * 0.4)  # ~400 ms minimum
            if len(full_audio) < min_bytes:
                continue

            audio_data = sr.AudioData(full_audio, SAMPLE_RATE, 2)
            try:
                text = recognizer.recognize_google(audio_data)
                log.info('Heard: "%s"', text)
                lower = text.lower()

                if "gideon" not in lower:
                    continue

                clean = re.sub(
                    r"(?:(?:hey|ok|okay|hi|hello)\s+)?\bgideon\b[,\.?!:]*",
                    "",
                    text,
                    flags=re.IGNORECASE,
                ).strip()

                if not clean:
                    log.info("Wake word only — saying 'I am listening'.")
                    speak_windows("I am listening.")
                    continue

                # Detect clear / reset intent
                is_clear = bool(re.search(
                    r"(?:clear\s+(?:the\s+)?(?:chat|screen|history|conversation|messages?)"
                    r"|start\s+(?:a\s+)?new\s+conversation"
                    r"|new\s+(?:chat|conversation)"
                    r"|reset\s+(?:chat|conversation))",
                    clean, re.I,
                ))
                if is_clear:
                    clear_conversation_session()
                    continue

                # Suppress duplicate commands within 3.5 s
                now = time.time()
                if clean.lower() == last_cmd.lower() and (now - last_cmd_time) < 3.5:
                    log.debug("Duplicate command suppressed.")
                    continue
                last_cmd = clean
                last_cmd_time = now

                log.info("▶ Wake triggered: %r", clean)
                submit_command_to_agent(clean)

            except sr.UnknownValueError:
                pass  # speech segment had no recognisable words
            except sr.RequestError as exc:
                log.error("Speech recognition service error: %s", exc)


# ──────────────────────────────────────────────────────────────
# Reconnect wrapper — survives mic errors / crashes automatically
# ──────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  G.I.D.E.O.N. Windows Desktop Ambient Voice Listener")
    print("  Say 'Hey Gideon' or 'Gideon, [command]'")
    print("  'Gideon, clear chat' — start a new conversation")
    print(f"  Log file: {_LOG_FILE}")
    print("=" * 65)

    log.info(
        "Voice listener starting (sample_rate=%d, energy_threshold=%.0f, reconnect_delay=%.0fs)",
        SAMPLE_RATE, ENERGY_THRESHOLD, RECONNECT_DELAY_SEC,
    )
    speak_windows("Gideon ambient voice listener online.")

    attempt = 0
    while True:
        attempt += 1
        try:
            _listen_once()
            break  # only exits normally if KeyboardInterrupt inside; shouldn't reach here
        except KeyboardInterrupt:
            log.info("Stopped by user (Ctrl-C).")
            print("\nGideon voice service stopped.")
            break
        except Exception as exc:
            log.error(
                "Listener crashed (attempt %d): %s — reconnecting in %.0f s…",
                attempt, exc, RECONNECT_DELAY_SEC,
            )
            try:
                time.sleep(RECONNECT_DELAY_SEC)
            except KeyboardInterrupt:
                log.info("Stopped during reconnect delay.")
                print("\nGideon voice service stopped.")
                break


if __name__ == "__main__":
    main()
