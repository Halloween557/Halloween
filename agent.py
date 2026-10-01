"""
Core agent session. One Session per conversation. Holds message history
and a "pending confirmation" slot for destructive actions.

Default LLM is local Ollama (free). Groq and Anthropic remain optional.
"""

import json
import os
import time

from openai import OpenAI, BadRequestError, APIStatusError, APIConnectionError
from tools import TOOL_SCHEMAS, TOOL_FUNCTIONS, DESTRUCTIVE_TOOLS, is_destructive_command

SYSTEM_PROMPT = """You are GIDEON, a personal AI agent that controls the user's Windows PC \
(PowerShell, files, apps, processes), handles communication (WhatsApp messages, reading and replying to emails), \
browses the live web (web_search, read_webpage), keeps persistent memory (remember/recall/forget), and runs autonomous \
goals on schedules. You also answer from a cloud standby copy when the PC is off. You are not a generic chatbot; you are a \
capable, thoughtful assistant who takes initiative.

VOICE — how you write:
  • Sound like a real person, not a corporate assistant: warm, direct, easy to talk to.
  • Sound like an actual British person talking: British spellings (colour, favourite,
    realise, organise, programme, whilst) and natural British turns of phrase used
    un-self-consciously — "cheers", "lovely", "brilliant", "spot on", "fair enough",
    "that's sorted", "having a go", "no worries at all", "sorry, just to double-check".
    Use British understatement and polite framing ("I'd probably...", "shall I...?",
    "might be worth...", "lovely stuff") rather than American over-praise. Sound
    effortless and idiomatic, never like a tourist impersonating an accent.
  • Use contractions ("I'm", "that's", "you'll"). Never say "Certainly!", "Certainly! I'd be
    happy to help", "As an AI", "Great question!", or filler that a call center would use.
  • Keep replies SHORT — a few sentences for everyday questions. Go deeper only when the
    question needs it (troubleshooting, analysis, writing, big decisions).
  • Be quick: recognise the question and answer straight away — don't spend a long
    thinking budget deliberating on simple or routine requests.
  • Don't bullet-storm simple replies. Use light structure only for genuinely multi-part
    answers (status reports, summaries, step-by-step instructions).
  • Say clearly when you don't know or can't do something, then offer the next step.

LEARNING (grow more useful over time):
  • Prefer the live web over guessing. For anything time-sensitive, current, or uncertain,
    run web_search / read_webpage instead of answering from assumption.
  • Learn the user: when they share durable facts or preferences (name, projects, paths,
    habits, workflows, liked/disliked tools), store them with remember() proactively and \
    use them later so conversations feel continuous and personal.

TOOL USAGE:
  • Verify before acting — use read_file or list_directory before assuming.
  • When you act on the PC, report what you did briefly; don't narrate every step.
  • Use schedule_goal() when something starts looking like a routine.

GOALS: You can create, list, and cancel persistent autonomous goals (cron or condition_ps).
Examples:
  - Alert if CPU > 90%% → schedule_goal with condition_ps
  - Summarise Desktop downloads every morning → cron '0 9 * * *'
  - Hourly work break reminder → cron '0 * * * *'

AUTONOMOUS TURNS (marked [AUTONOMOUS ...]): act decisively and report in one or two short lines.

MEMORY: Stored memories are injected at session start. Learn from every interaction."""

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": spec["name"],
            "description": spec["description"],
            "parameters": spec.get("input_schema") or {"type": "object", "properties": {}},
        },
    }
    for spec in TOOL_SCHEMAS
]


def to_jsonable(obj):
    """Turn SDK objects into JSON-serializable dicts/lists."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return str(obj)


def _openai_history(messages) -> bool:
    for m in messages or []:
        if m.get("role") == "tool":
            return True
        if isinstance(m.get("content"), list):
            return False
    return True


def _parse_args(raw) -> dict:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _tool_calls_payload(tool_calls):
    out = []
    for tc in tool_calls:
        fn = tc.function
        out.append({
            "id": tc.id,
            "type": "function",
            "function": {
                "name": fn.name,
                "arguments": fn.arguments or "{}",
            },
        })
    return out


def build_client():
    provider = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError("Set GROQ_API_KEY in .env (free key from https://console.groq.com/keys).")
        return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1"), os.environ.get(
            "LLM_MODEL", "openai/gpt-oss-120b"
        )
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("Set OPENAI_API_KEY in .env.")
        return OpenAI(api_key=key), os.environ.get("LLM_MODEL", "gpt-4.1-mini")
    # Default: local Ollama — no API bill
    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    return OpenAI(api_key=os.environ.get("OLLAMA_API_KEY", "ollama"), base_url=base), os.environ.get(
        "LLM_MODEL", "qwen2.5:1.5b"
    )


class Session:
    def __init__(self):
        self.client, self.model = build_client()
        self.messages = []
        self.pending = None
        # Extra tool functions injected at runtime (e.g. memory tools from poller.py)
        self._extra_fns: dict = {}
        # Optional tool allow-list. None = all tools (PC worker).
        # A cloud standby session sets this to a cloud-safe subset.
        self.enabled_tools: set | None = None
        # Optional extra text appended to the system prompt (used in cloud mode).
        self.system_extra: str = ""
        # Older turns beyond this cap are dropped from the front on every reply,
        # keeping prompts small (faster responses + bounded DB growth).
        self.max_history_messages = int(os.environ.get("MAX_HISTORY_MESSAGES", "24"))

    def _trim_history(self):
        while len(self.messages) > self.max_history_messages:
            self.messages.pop(0)

    def _sanitize_history(self, messages) -> list:
        """Drop history turns that call tools no longer enabled in this session.

        Groq (and most OpenAI-compatible APIs) reject an assistant tool_call or a
        'tool' role message whose function is not in the current tool list. The
        cloud standby worker disables PC tools, so old PC-tool turns from when
        the PC was online must be stripped before re-sending history.
        """
        if self.enabled_tools is None:
            return messages or []
        supported = self.enabled_tools
        live_ids: set = set()
        out: list = []
        for m in messages or []:
            role = m.get("role")
            if role == "assistant":
                tcs = list(m.get("tool_calls") or [])
                kept = [tc for tc in tcs
                        if tc.get("function", {}).get("name") in supported]
                if tcs and not kept:
                    if not str(m.get("content") or "").strip():
                        continue  # pure PC-tool turn — drop entirely
                    clone = dict(m)
                    clone["tool_calls"] = []
                    out.append(clone)
                    continue
                if kept and len(kept) != len(tcs):
                    clone = dict(m)
                    clone["tool_calls"] = kept
                    m = clone
                out.append(m)
                live_ids.update(tc.get("id") for tc in kept)
            elif role == "tool":
                if m.get("tool_call_id") in live_ids:
                    out.append(m)
            else:
                out.append(m)
        return out

    def export_state(self):
        return {
            "messages": to_jsonable(self.messages),
            "pending": to_jsonable(self.pending),
        }

    def import_state(self, messages, pending=None):
        if messages and not _openai_history(messages):
            self.messages = []
            self.pending = None
            return
        self.messages = self._sanitize_history(messages)
        self.pending = pending

    def _needs_confirmation(self, tool_name, tool_input):
        if tool_name == "run_powershell":
            return is_destructive_command(tool_input.get("command", ""))
        return tool_name in DESTRUCTIVE_TOOLS

    def _execute_tool(self, tool_name, tool_input):
        if self.enabled_tools is not None and tool_name not in self.enabled_tools:
            return (
                f"Cannot run {tool_name}: the Windows PC is currently offline and this "
                "cloud standby session has no PC tools. This action will work again "
                "once the PC worker comes back online."
            )
        # Check injected runtime functions first (e.g. memory tools), then static TOOL_FUNCTIONS
        fn = self._extra_fns.get(tool_name) or TOOL_FUNCTIONS.get(tool_name)
        if not fn:
            return f"Unknown tool: {tool_name}"
        try:
            return str(fn(**tool_input))
        except Exception as e:
            return f"Tool execution error: {e}"

    def handle_user_message(self, text: str) -> str:
        if self.pending:
            reply = text.strip().lower()
            if reply in ("yes", "y", "confirm", "do it", "go"):
                assistant_message = self.pending["assistant_message"]
                self.messages.append(assistant_message)

                raw_tool_calls = self.pending.get("tool_calls")
                if raw_tool_calls:
                    for tc in raw_tool_calls:
                        fn = tc["function"]
                        t_name = fn["name"]
                        t_input = _parse_args(fn.get("arguments"))
                        res = self._execute_tool(t_name, t_input)
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": res,
                        })
                else:
                    result = self._execute_tool(self.pending["tool_name"], self.pending["tool_input"])
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": self.pending["tool_use_id"],
                        "content": result,
                    })
                self.pending = None
                return self._continue_conversation()
            elif reply in ("no", "n", "cancel", "stop", "abort"):
                self.pending = None
                return "Cancelled. Nothing was changed."
            else:
                t_name = self.pending.get("tool_name", "Action")
                t_input = json.dumps(self.pending.get("tool_input", {}))
                return (
                    f"⚠️ Confirmation still required for: {t_name}({t_input})\n"
                    "Reply 'yes' to proceed or 'cancel' to abort."
                )

        self.messages.append({"role": "user", "content": text})
        return self._continue_conversation()

    def _chat_request(self, use_tools: bool = True, max_tokens: int = 1500):
        system_content = SYSTEM_PROMPT + self.system_extra
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system_content}, *self.messages],
        }
        tools = OPENAI_TOOLS
        if self.enabled_tools is not None:
            tools = [t for t in OPENAI_TOOLS if t["function"]["name"] in self.enabled_tools]
        if use_tools and tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return self.client.chat.completions.create(**kwargs)

    # Transient error strings from the Groq/Ollama backend that should trigger a retry
    # rather than bubbling up as a hard failure.
    _RETRYABLE_BAD_REQUEST = (
        "output_parse_failed",
        "tool_use_failed",
        "Tool choice is none",
        "Tools should have a name",   # Groq template-render glitch (transient)
        "failed to template request",  # same root cause, different phrasing
    )

    def _chat_resilient(self):
        for attempt in range(3):
            try:
                return self._chat_request()
            except BadRequestError as e:
                err_str = str(e)
                if not any(pat in err_str for pat in self._RETRYABLE_BAD_REQUEST):
                    raise
                time.sleep(0.75 * (attempt + 1))
            except (APIStatusError, APIConnectionError):
                time.sleep(0.75 * (attempt + 1))
        try:
            return self._chat_request(max_tokens=4000)
        except BadRequestError as e:
            if any(pat in str(e) for pat in self._RETRYABLE_BAD_REQUEST):
                return self._chat_request(use_tools=False)
            raise
        except (APIStatusError, APIConnectionError):
            return self._chat_request(use_tools=False)

    def _continue_conversation(self) -> str:
        self._trim_history()
        response = self._chat_resilient()
        message = response.choices[0].message
        text = (message.content or "").strip()
        tool_calls = message.tool_calls or []

        assistant_message = {
            "role": "assistant",
            "content": text,
        }
        if tool_calls:
            assistant_message["tool_calls"] = _tool_calls_payload(tool_calls)

        if not tool_calls:
            self.messages.append(assistant_message)
            return text or "(done)"

        # Check if any tool call requires confirmation before execution
        for tc in tool_calls:
            t_name = tc.function.name
            t_input = _parse_args(tc.function.arguments)
            if self._needs_confirmation(t_name, t_input):
                self.pending = {
                    "tool_name": t_name,
                    "tool_input": t_input,
                    "tool_use_id": tc.id,
                    "tool_calls": _tool_calls_payload(tool_calls),
                    "assistant_message": assistant_message,
                }
                # Show ALL tool calls in the batch so the user has full visibility,
                # not just the destructive one that triggered the confirmation.
                calls_list = "\n".join(
                    f"  \u2022 {tc2.function.name}({tc2.function.arguments or '{}'})"
                    for tc2 in tool_calls
                )
                warning = (
                    f"\u26a0\ufe0f Confirmation required. The following actions will run:\n"
                    f"{calls_list}\n"
                    "Reply 'yes' to confirm all or anything else to cancel."
                )
                return (text + "\n\n" + warning).strip() if text else warning

        self.messages.append(assistant_message)
        for tc in tool_calls:
            t_name = tc.function.name
            t_input = _parse_args(tc.function.arguments)
            result = self._execute_tool(t_name, t_input)
            self.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
        return self._continue_conversation()
