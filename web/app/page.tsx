"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { sound, speakText, stopSpeaking } from "@/lib/audio";

// ─── Types ───────────────────────────────────────────────────────────────────
type ChatMessage = { id: string; role: string; content: string; created_at: string };
type DeviceState = { online: boolean; status: string; last_seen_at: string | null };
type AgentMemory = { id: string; category: string; key: string; content: string; created_at: string; updated_at: string };
type AgentState = "idle" | "listening" | "thinking" | "speaking";

const TOKEN_KEY = "pc-agent-token";

// ─── DreamCanvas — animated node network background ───────────────────────────
function DreamCanvas({ state }: { state: AgentState }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    let animId: number;
    let t = 0;

    const setSize = () => {
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      ctx.scale(dpr, dpr);
    };
    setSize();
    window.addEventListener("resize", setSize);

    // Nodes
    type Node = { x: number; y: number; vx: number; vy: number; r: number; pulse: number; hue: number };
    const W = () => window.innerWidth;
    const H = () => window.innerHeight;
    const nodes: Node[] = Array.from({ length: 55 }, () => ({
      x: Math.random() * W(),
      y: Math.random() * H(),
      vx: (Math.random() - 0.5) * 0.18,
      vy: (Math.random() - 0.5) * 0.18,
      r: 2 + Math.random() * 3.5,
      pulse: Math.random() * Math.PI * 2,
      hue: Math.random() > 0.5 ? 260 : 180, // purple or teal
    }));

    const render = () => {
      t += 0.008;
      const w = W(), h = H();
      ctx.clearRect(0, 0, w, h);

      // Speed multiplier by state
      const speed = state === "thinking" ? 3.5 : state === "listening" ? 2 : state === "speaking" ? 2.2 : 1;

      // Move nodes
      nodes.forEach(n => {
        n.x += n.vx * speed;
        n.y += n.vy * speed;
        n.pulse += 0.02 * speed;
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;
        n.x = Math.max(0, Math.min(w, n.x));
        n.y = Math.max(0, Math.min(h, n.y));
      });

      // Draw connections
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 160) {
            const alpha = (1 - dist / 160) * 0.22;
            const midHue = (a.hue + b.hue) / 2;
            ctx.strokeStyle = `hsla(${midHue}, 70%, 65%, ${alpha})`;
            ctx.lineWidth = 0.8;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }

      // Draw nodes
      nodes.forEach(n => {
        const glow = Math.sin(n.pulse) * 0.4 + 0.6;
        const radius = n.r * (1 + Math.sin(n.pulse) * 0.25);

        const grad = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, radius * 4);
        grad.addColorStop(0, `hsla(${n.hue}, 80%, 80%, ${glow * 0.9})`);
        grad.addColorStop(0.5, `hsla(${n.hue}, 70%, 60%, ${glow * 0.3})`);
        grad.addColorStop(1, `hsla(${n.hue}, 60%, 50%, 0)`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(n.x, n.y, radius * 4, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = `hsla(${n.hue}, 90%, 90%, ${glow})`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
        ctx.fill();
      });

      animId = requestAnimationFrame(render);
    };

    render();
    return () => {
      window.removeEventListener("resize", setSize);
      cancelAnimationFrame(animId);
    };
  }, [state]);

  return <canvas ref={ref} className="dream-canvas" />;
}

// ─── VocalBars ────────────────────────────────────────────────────────────────
function VocalBars({ state }: { state: AgentState }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth;
    const H = canvas.offsetHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);

    const BARS = 48;
    let t = 0;
    let animId: number;
    const phases = Array.from({ length: BARS }, (_, i) => i * (Math.PI * 2 / BARS) + Math.random());

    const render = () => {
      t += 0.06;
      ctx.clearRect(0, 0, W, H);

      const barW = (W / BARS) * 0.65;
      const gap = W / BARS;

      for (let i = 0; i < BARS; i++) {
        const x = i * gap + gap / 2;
        let h = 0;

        if (state === "idle") {
          h = H * 0.06 + Math.sin(t * 0.8 + phases[i]) * H * 0.04;
        } else if (state === "listening") {
          h = H * 0.15 + Math.abs(Math.sin(t * 3.5 + phases[i] * 2.1)) * H * 0.72;
        } else if (state === "thinking") {
          const wave = Math.sin(t * 2 - i * 0.28);
          h = H * 0.12 + (wave * 0.5 + 0.5) * H * 0.65;
        } else if (state === "speaking") {
          h = H * 0.1 + Math.abs(Math.sin(t * 4.5 + phases[i] * 1.8)) * H * 0.80;
        }

        // Color based on state
        let c1: string, c2: string;
        if (state === "listening") {
          c1 = "rgba(251,191,36,0.95)"; c2 = "rgba(245,158,11,0.2)";
        } else if (state === "thinking") {
          c1 = "rgba(192,132,252,0.95)"; c2 = "rgba(147,51,234,0.2)";
        } else if (state === "speaking") {
          c1 = "rgba(94,234,212,0.95)"; c2 = "rgba(20,184,166,0.2)";
        } else {
          c1 = "rgba(148,163,184,0.5)"; c2 = "rgba(100,116,139,0.1)";
        }

        const grad = ctx.createLinearGradient(x, H, x, H - h);
        grad.addColorStop(0, c2);
        grad.addColorStop(1, c1);
        ctx.fillStyle = grad;

        const y = H - h;
        const rx = barW / 2;
        ctx.beginPath();
        ctx.moveTo(x - rx + rx, y);
        ctx.arcTo(x + rx, y, x + rx, y + h, rx);
        ctx.arcTo(x + rx, y + h, x - rx, y + h, rx);
        ctx.arcTo(x - rx, y + h, x - rx, y, rx);
        ctx.arcTo(x - rx, y, x + rx, y, rx);
        ctx.closePath();
        ctx.fill();
      }

      animId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animId);
  }, [state]);

  return <canvas ref={ref} className="vocal-bars-canvas" />;
}

// ─── Main ─────────────────────────────────────────────────────────────────────
export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [device, setDevice] = useState<DeviceState | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [showMemories, setShowMemories] = useState(false);
  const [memories, setMemories] = useState<AgentMemory[]>([]);
  const [newMemKey, setNewMemKey] = useState("");
  const [newMemContent, setNewMemContent] = useState("");
  const [copiedIndex, setCopiedIndex] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [autoSpeak, setAutoSpeak] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);

  // Wake-word ("Hey Gideon") hands-free ambient ear states
  const [wakeWordEnabled, setWakeWordEnabled] = useState(false);
  const [isAwakened, setIsAwakened] = useState(false);
  const [awakenedNotice, setAwakenedNotice] = useState<string | null>(null);

  const wakeWordEnabledRef = useRef(wakeWordEnabled);
  wakeWordEnabledRef.current = wakeWordEnabled;
  const isAwakenedRef = useRef(isAwakened);
  isAwakenedRef.current = isAwakened;
  const speakingRef = useRef<string | null>(speakingId);
  speakingRef.current = speakingId;
  const wakeTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const recognitionRef = useRef<any>(null);

  const logRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lastBotMsgIdRef = useRef<string | null>(null);
  const spokenMsgIdsRef = useRef<Set<string>>(new Set());
  const hasInitializedMsgsRef = useRef(false);
  const lastSentMsgRef = useRef<{ text: string; time: number }>({ text: "", time: 0 });

  const autoSpeakRef = useRef(autoSpeak);
  autoSpeakRef.current = autoSpeak;

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const mediaStreamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    const stored = sessionStorage.getItem(TOKEN_KEY);
    if (stored) setToken(stored);
    setSoundEnabled(sound.isEnabled());
    const savedSpeak = localStorage.getItem("pc-copilot-auto-speak");
    if (savedSpeak !== null) setAutoSpeak(savedSpeak === "true");
    const savedWake = localStorage.getItem("pc-copilot-wake-word");
    if (savedWake !== null) setWakeWordEnabled(savedWake === "true");
  }, []);

  const refresh = useCallback(async (auth: string) => {
    try {
      const res = await fetch("/api/messages", { headers: { Authorization: `Bearer ${auth}` } });
      if (res.status === 401) { sessionStorage.removeItem(TOKEN_KEY); setToken(null); setError("Unauthorized."); return; }
      if (!res.ok) return;
      const data = await res.json();
      const newMsgs: ChatMessage[] = data.messages ?? [];
      if (newMsgs.length > 0) {
        const last = newMsgs[newMsgs.length - 1];
        if (last.role !== "user") {
          // On initial page load: register all historical messages so they are never re-spoken
          if (!hasInitializedMsgsRef.current) {
            hasInitializedMsgsRef.current = true;
            lastBotMsgIdRef.current = last.id;
            newMsgs.forEach(m => spokenMsgIdsRef.current.add(m.id));
          } else if (!spokenMsgIdsRef.current.has(last.id)) {
            // Strictly speak each bot response ONCE
            spokenMsgIdsRef.current.add(last.id);
            lastBotMsgIdRef.current = last.id;

            if (last.content.includes("WARNING:") || last.content.includes("Reply YES")) sound.playWarning();
            else sound.playReceive();

            if (autoSpeakRef.current) {
              setSpeakingId(last.id);
              speakText(last.content, () => setSpeakingId(null));
            }
          }
        }
      }
      setMessages(newMsgs);
      setDevice(data.device ?? null);
      setError("");
    } catch { /* silent */ }
  }, []);

  const refreshMemories = useCallback(async (auth: string) => {
    try {
      const res = await fetch("/api/memories", { headers: { Authorization: `Bearer ${auth}` } });
      if (res.ok) { const d = await res.json(); setMemories(d.memories ?? []); }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!token) return;
    refresh(token);
    refreshMemories(token);
    const id = setInterval(() => refresh(token), 1200);
    return () => clearInterval(id);
  }, [token, refresh, refreshMemories]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  function saveToken() {
    const v = tokenInput.trim();
    if (!v) return;
    if (v.startsWith("gsk_") || v.startsWith("sk-ant-")) { setError("That is an LLM API key — paste the AGENT_TOKEN UUID from .env."); return; }
    sessionStorage.setItem(TOKEN_KEY, v);
    setToken(v); setError(""); sound.playClick();
  }

  function disconnect() { stopSpeaking(); sessionStorage.removeItem(TOKEN_KEY); setToken(null); setMessages([]); sound.playClick(); }

  async function clearChat(skipConfirm = false) {
    if (!token) return;
    if (!skipConfirm && !confirm("Clear conversation and start fresh?")) return;
    stopSpeaking();
    setSpeakingId(null);
    sound.playClick();
    setAwakenedNotice("✦ Screen cleared — New conversation started");
    setTimeout(() => setAwakenedNotice(null), 3500);

    try {
      await fetch("/api/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }
      });
      setMessages([]);
      spokenMsgIdsRef.current.clear();
      lastBotMsgIdRef.current = null;
      if (skipConfirm) {
        speakText("Conversation cleared. How can I help you?");
      }
    } catch (e) {
      setError(`Failed to clear: ${e}`);
    }
  }

  async function send(text?: string) {
    if (!token || sending) return;
    const msg = (text ?? draft).trim();
    if (!msg) return;

    // Detect voice or text command to clear chat / start new conversation
    const isClearRequest = /^(?:(?:hey|ok|okay|hi|hello)\s+)?gideon[\s,:]*(?:please\s+)?(?:clear\s+(?:the\s+)?(?:chat|screen|history|conversation|messages?)|start\s+(?:a\s+)?new\s+conversation|new\s+(?:chat|conversation)|reset\s+(?:chat|conversation))$/i.test(msg) ||
                           /^(?:please\s+)?(?:clear\s+(?:the\s+)?(?:chat|screen|history|conversation|messages?)|start\s+(?:a\s+)?new\s+conversation|new\s+(?:chat|conversation)|reset\s+(?:chat|conversation))$/i.test(msg);

    if (isClearRequest) {
      if (!text) setDraft("");
      await clearChat(true);
      return;
    }

    // Deduplicate identical commands submitted within 3.5 seconds
    const now = Date.now();
    if (lastSentMsgRef.current.text.toLowerCase() === msg.toLowerCase() && (now - lastSentMsgRef.current.time) < 3500) {
      console.log("Prevented duplicate submission:", msg);
      return;
    }
    lastSentMsgRef.current = { text: msg, time: now };

    if (!text) { setDraft(""); if (textareaRef.current) textareaRef.current.style.height = "auto"; }
    setSending(true); sound.playSend();
    try {
      const res = await fetch("/api/messages", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ message: msg, client_id: crypto.randomUUID() }) });
      if (res.status === 401) { setError("Unauthorized."); return; }
      await refresh(token);
    } catch (e) { setError(`Error: ${e}`); }
    finally { setSending(false); }
  }

  const sendRef = useRef<(text?: string) => Promise<void>>(send);
  sendRef.current = send;

  // Speech Recognition Wake-word ("Hey Gideon") continuous ambient listener
  useEffect(() => {
    if (typeof window === "undefined") return;
    const SpeechRec = (window as unknown as { SpeechRecognition?: any; webkitSpeechRecognition?: any }).SpeechRecognition ||
                      (window as unknown as { webkitSpeechRecognition?: any }).webkitSpeechRecognition;
    if (!SpeechRec) {
      if (wakeWordEnabled) {
        setError("Speech recognition not supported in this browser. Please use Chrome or Edge.");
        setWakeWordEnabled(false);
      }
      return;
    }

    if (!wakeWordEnabled || !token) {
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch {}
        recognitionRef.current = null;
      }
      return;
    }

    let isDestroyed = false;
    let recognition: any = null;

    try {
      recognition = new SpeechRec();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";
      recognitionRef.current = recognition;

      recognition.onresult = (event: any) => {
        // Prevent Gideon from triggering on her own synthesized voice
        if (speakingRef.current !== null) return;

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const res = event.results[i];
          const transcript = res[0].transcript.trim();
          const isFinal = res.isFinal;
          const lower = transcript.toLowerCase();

          // Case A: Gideon was already awakened and listening for the follow-up command
          if (isAwakenedRef.current) {
            if (isFinal) {
              if (wakeTimeoutRef.current) clearTimeout(wakeTimeoutRef.current);
              setIsAwakened(false);
              isAwakenedRef.current = false;

              // Strip repeat "Gideon" prefix
              const clean = transcript
                .replace(/^(?:(?:hey|ok|okay|hi|hello)\s+)?gideon[\s,:]*/i, "")
                .trim();
              const finalCmd = clean || transcript;
              if (finalCmd.length > 1) {
                setAwakenedNotice(`✦ Gideon executing: "${finalCmd}"`);
                setTimeout(() => setAwakenedNotice(null), 4000);
                sendRef.current(finalCmd);
              }
            } else {
              setAwakenedNotice(`✦ Gideon hearing: "${transcript}..."`);
            }
            continue;
          }

          // Case B: Any conversation that mentions "Gideon"
          if (lower.includes("gideon")) {
            // Strip out "Gideon" and any greeting prefix
            const clean = transcript
              .replace(/(?:(?:hey|ok|okay|hi|hello)\s+)?\bgideon\b[,\.?!:]*/gi, "")
              .trim();

            if (clean.length > 2) {
              // Full command uttered together with Gideon in the same phrase
              if (isFinal) {
                sound.playGideonActivate();
                setAwakenedNotice(`✦ Gideon: "${clean}"`);
                setTimeout(() => setAwakenedNotice(null), 4000);
                sendRef.current(clean);
              } else {
                setAwakenedNotice(`✦ Gideon awakened: "${clean}..."`);
              }
            } else {
              // Spoke "Gideon" or "Hey Gideon" alone
              sound.playGideonActivate();
              setIsAwakened(true);
              isAwakenedRef.current = true;
              setAwakenedNotice("✦ Gideon awakened: Speak your command...");

              if (wakeTimeoutRef.current) clearTimeout(wakeTimeoutRef.current);
              wakeTimeoutRef.current = setTimeout(() => {
                setIsAwakened(false);
                isAwakenedRef.current = false;
                setAwakenedNotice(null);
              }, 8000);
            }
          }
        }
      };

      recognition.onerror = (e: any) => {
        if (e.error === "no-speech" || e.error === "network") return;
        if (e.error === "not-allowed") {
          setError("Microphone permission denied for wake-word.");
          setWakeWordEnabled(false);
        }
      };

      recognition.onend = () => {
        // Automatically restart to keep ambient listening active
        if (!isDestroyed && wakeWordEnabledRef.current) {
          setTimeout(() => {
            if (!isDestroyed && wakeWordEnabledRef.current) {
              try { recognition.start(); } catch {}
            }
          }, 300);
        }
      };

      recognition.start();
    } catch (err) {
      console.warn("SpeechRecognition start error:", err);
    }

    return () => {
      isDestroyed = true;
      if (recognition) {
        try { recognition.abort(); } catch {}
      }
      if (wakeTimeoutRef.current) clearTimeout(wakeTimeoutRef.current);
    };
  }, [wakeWordEnabled, token]);

  function toggleWakeWord() {
    const next = !wakeWordEnabled;
    setWakeWordEnabled(next);
    localStorage.setItem("pc-copilot-wake-word", String(next));
    if (next) {
      if (!autoSpeak) {
        setAutoSpeak(true);
        localStorage.setItem("pc-copilot-auto-speak", "true");
      }
      sound.playGideonActivate();
      setAwakenedNotice("✦ Ambient Ear: Active (Say 'Hey Gideon'...)");
      setTimeout(() => setAwakenedNotice(null), 3500);
    } else {
      sound.playClick();
      setIsAwakened(false);
      setAwakenedNotice(null);
    }
  }

  async function toggleRecording() {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      mediaStreamRef.current?.getTracks().forEach(t => t.stop());
      mediaStreamRef.current = null;
      setIsRecording(false); sound.playClick(); return;
    }
    if (!navigator?.mediaDevices?.getUserMedia) { setError("Microphone not available (HTTPS or localhost required)."); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      audioChunksRef.current = [];
      let mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "audio/mp4";
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      mediaRecorderRef.current = mr;
      mr.ondataavailable = e => { if (e.data?.size > 0) audioChunksRef.current.push(e.data); };
      mr.onstop = async () => {
        mediaStreamRef.current?.getTracks().forEach(t => t.stop()); mediaStreamRef.current = null;
        const blob = new Blob(audioChunksRef.current, { type: mime || "audio/webm" });
        if (blob.size < 800) return;
        setIsTranscribing(true);
        try {
          const form = new FormData(); form.append("file", blob, "rec.webm");
          const res = await fetch("/api/transcribe", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form });
          if (!res.ok) { const e = await res.json().catch(() => ({})); setError(e.error || "Transcription failed"); return; }
          const d = await res.json();
          if (d.text) { setDraft(p => p ? `${p} ${d.text.trim()}` : d.text.trim()); sound.playReceive(); }
        } catch (e) { setError(`Transcription error: ${e}`); }
        finally { setIsTranscribing(false); }
      };
      mr.start(250); setIsRecording(true); sound.playClick();
    } catch { setIsRecording(false); setError("Microphone access denied."); }
  }

  function toggleSoundFx() { const n = !soundEnabled; setSoundEnabled(n); sound.setEnabled(n); if (n) sound.playClick(); }
  function toggleAutoSpeak() { const n = !autoSpeak; setAutoSpeak(n); localStorage.setItem("pc-copilot-auto-speak", String(n)); if (!n) stopSpeaking(); sound.playClick(); }
  function handleSpeakMessage(msg: ChatMessage) {
    if (speakingId === msg.id) { stopSpeaking(); setSpeakingId(null); }
    else { setSpeakingId(msg.id); speakText(msg.content, () => setSpeakingId(null)); }
  }
  async function handleAddMemory() {
    if (!token || !newMemKey.trim() || !newMemContent.trim()) return;
    await fetch("/api/memories", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ key: newMemKey.trim(), content: newMemContent.trim(), category: "manual" }) });
    setNewMemKey(""); setNewMemContent(""); sound.playClick(); refreshMemories(token);
  }
  async function handleDeleteMemory(key: string) {
    if (!token) return;
    await fetch(`/api/memories?key=${encodeURIComponent(key)}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
    sound.playClick(); refreshMemories(token);
  }
  function copyToClipboard(text: string, id: string) { navigator.clipboard.writeText(text); setCopiedIndex(id); sound.playClick(); setTimeout(() => setCopiedIndex(null), 2000); }

  function renderContent(content: string, msgId: string) {
    const isConfirm = content.includes("Confirmation required") || (content.includes("Reply 'yes'") && content.includes("cancel"));
    const parts = content.split(/(```[\s\S]*?```)/g);
    return (
      <>
        {parts.map((part, idx) => {
          if (part.startsWith("```") && part.endsWith("```")) {
            const raw = part.slice(3, -3);
            const lb = raw.indexOf("\n");
            const lang = lb !== -1 ? raw.slice(0, lb).trim() : "";
            const code = lb !== -1 ? raw.slice(lb + 1) : raw;
            const bid = `${msgId}-${idx}`;
            return (
              <div key={idx} className="dn-code-block">
                <div className="dn-code-header">
                  <span className="dn-code-lang">{lang || "terminal"}</span>
                  <button type="button" className="dn-code-copy" onClick={() => copyToClipboard(code, bid)}>
                    {copiedIndex === bid ? "✓ Copied" : "Copy"}
                  </button>
                </div>
                <pre className="dn-code-pre"><code>{code}</code></pre>
              </div>
            );
          }
          return <span key={idx} style={{ whiteSpace: "pre-wrap" }}>{part}</span>;
        })}
        {isConfirm && (
          <div className="dn-confirm-banner">
            <span className="dn-confirm-icon">⚠</span>
            <span>Destructive action — confirm execution:</span>
            <div className="dn-confirm-btns">
              <button type="button" className="dn-btn-yes" onClick={() => send("yes")} disabled={sending}>Approve ✓</button>
              <button type="button" className="dn-btn-no" onClick={() => send("no")} disabled={sending}>Cancel ✗</button>
            </div>
          </div>
        )}
      </>
    );
  }

  // ─── Cognitive state ───────────────────────────────────────────────────────
  const agentState: AgentState = isRecording || isAwakened ? "listening" : sending || isTranscribing ? "thinking" : speakingId !== null ? "speaking" : "idle";

  // ─── Auth Screen ───────────────────────────────────────────────────────────
  if (!token) {
    return (
      <div className="dream-root">
        <DreamCanvas state="idle" />
        <div className="dream-auth">
          <div className="dream-auth-card">
            <div className="dream-auth-orb" />
            <h1 className="dream-auth-title">CONNECT TO YOUR AGENT</h1>
            <p className="dream-auth-sub">Paste the <code>AGENT_TOKEN</code> from your Windows <code>.env</code> file</p>
            <div className="dream-auth-row">
              <input
                id="tokenInput"
                type="password"
                className="dream-auth-input"
                placeholder="AGENT_TOKEN (UUID format)"
                value={tokenInput}
                onChange={e => setTokenInput(e.target.value)}
                onKeyDown={e => e.key === "Enter" && saveToken()}
                autoFocus
              />
              <button type="button" id="connectBtn" className="dream-auth-btn" onClick={saveToken}>
                Connect
              </button>
            </div>
            {error && <p className="dream-auth-error">{error}</p>}
          </div>
        </div>
      </div>
    );
  }

  // ─── Last seen ─────────────────────────────────────────────────────────────
  const lastSeen = device?.last_seen_at
    ? (() => { const d = Math.max(0, Math.floor((Date.now() - new Date(device.last_seen_at).getTime()) / 1000)); return d < 5 ? "Just now" : `${d}s ago`; })()
    : "Never";

  // ─── Main UI ───────────────────────────────────────────────────────────────
  return (
    <div className="dream-root">
      <DreamCanvas state={agentState} />

      {/* Floating Status Pill */}
      <header className="dream-header">
        <div className="dream-header-left">
          <div className={`dream-status-dot ${device?.online ? "online" : "offline"}`} />
          <span className="dream-agent-name">G·I·D·E·O·N</span>
          <span className="dream-divider" />
          <span className="dream-status-text">
            {device?.online ? `Online · ${lastSeen}` : `Offline · ${lastSeen}`}
          </span>
        </div>
        <div className="dream-header-right">
          <button
            id="wakeWordBtn"
            type="button"
            className={`dream-pill-btn wake-pill ${wakeWordEnabled ? "active" : ""}`}
            onClick={toggleWakeWord}
            title="Hands-free wake word: Say 'Hey Gideon' or 'Gideon, [command]'"
          >
            <span className={`dream-wake-pulse ${wakeWordEnabled ? "listening" : ""}`} />
            {wakeWordEnabled ? 'Ear: "Gideon" ON' : 'Ear: OFF'}
          </button>
          <button id="soundToggleBtn" type="button" className={`dream-pill-btn ${soundEnabled ? "active" : ""}`} onClick={toggleSoundFx} title="Toggle Sound FX">
            {soundEnabled ? "♪" : "♪̶"}
          </button>
          <button id="ttsToggleBtn" type="button" className={`dream-pill-btn ${autoSpeak ? "active" : ""}`} onClick={toggleAutoSpeak} title="Toggle Auto-Voice">
            {autoSpeak ? "Voice On" : "Voice Off"}
          </button>
          <button id="memoriesBtn" type="button" className={`dream-pill-btn ${showMemories ? "active" : ""}`} onClick={() => { sound.playClick(); setShowMemories(!showMemories); }}>
            Memories {memories.length > 0 && <span className="dream-mem-badge">{memories.length}</span>}
          </button>
          <button id="clearChatBtn" type="button" className="dream-pill-btn" onClick={() => clearChat()} title="Clear conversation">
            Clear
          </button>
          <button id="disconnectBtn" type="button" className="dream-pill-btn danger" onClick={disconnect} title="Disconnect">
            ✕
          </button>
        </div>
      </header>

      {/* Floating Awakened Banner */}
      {awakenedNotice && (
        <div className="dream-awakened-banner">
          <span className="dream-sparkle">✦</span>
          <span className="dream-awakened-text">{awakenedNotice}</span>
        </div>
      )}

      {/* Main layout */}
      <div className="dream-layout">

        {/* Chat Node Stream */}
        <div className="dream-chat-col">
          <div id="log" className="dream-chat-scroll" ref={logRef}>

            {messages.length === 0 ? (
              <div className="dream-welcome">
                <div className="dream-welcome-orb" />
                <h2 className="dream-welcome-title">Autonomous Dream Agent</h2>
                <p className="dream-welcome-sub">
                  A sovereign AI mind with persistent memory, goal engine, and full PC control.
                  Speak or type to engage the neural network.
                </p>
                <div className="dream-quick-grid">
                  {[
                    { icon: "⚡", label: "System Vitals", desc: "CPU, RAM, disk status", msg: "Check system health: CPU, RAM, and disk." },
                    { icon: "🧠", label: "Recall Memory", desc: "What do you remember?", msg: "What do you remember about me? List all memories." },
                    { icon: "🎯", label: "Set a Goal", desc: "Autonomous task engine", msg: "List my active autonomous goals." },
                    { icon: "📁", label: "Explore Files", desc: "Browse the Desktop", msg: "List files on my Desktop." },
                  ].map(q => (
                    <button key={q.label} type="button" className="dream-quick-card" onClick={() => send(q.msg)}>
                      <span className="dream-quick-icon">{q.icon}</span>
                      <div className="dream-quick-label">{q.label}</div>
                      <div className="dream-quick-desc">{q.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="dream-node-stream">
                {messages.map((msg, idx) => {
                  const isUser = msg.role === "user";
                  const isAutonomous = msg.content.startsWith("🤖 [Autonomous]");
                  const ts = new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
                  return (
                    <div key={msg.id} className={`dream-node-row ${isUser ? "user" : isAutonomous ? "autonomous" : "agent"}`}>
                      {/* Connector spine */}
                      {idx > 0 && <div className={`dream-node-spine ${isUser ? "user" : "agent"}`} />}

                      <div className={`dream-node-card ${isUser ? "user" : isAutonomous ? "autonomous" : "agent"}`}>
                        {/* Node dot */}
                        <div className={`dream-node-dot ${isUser ? "user" : isAutonomous ? "autonomous" : "agent"}`} />

                        {/* Role label */}
                        <div className="dream-node-meta">
                          <span className="dream-node-role">
                            {isUser ? "You" : isAutonomous ? "⚡ Autonomous" : "G.I.D.E.O.N."}
                          </span>
                          <span className="dream-node-ts">{ts}</span>
                        </div>

                        {/* Content */}
                        <div className="dream-node-content">
                          {renderContent(msg.content, msg.id)}
                        </div>

                        {/* Actions */}
                        {!isUser && (
                          <div className="dream-node-actions">
                            <button
                              type="button"
                              className={`dream-node-btn ${speakingId === msg.id ? "speaking" : ""}`}
                              onClick={() => handleSpeakMessage(msg)}
                              title={speakingId === msg.id ? "Stop speaking" : "Read aloud"}
                            >
                              {speakingId === msg.id ? "■ Stop" : "▶ Speak"}
                            </button>
                            <button
                              type="button"
                              className="dream-node-btn"
                              onClick={() => copyToClipboard(msg.content, msg.id)}
                            >
                              {copiedIndex === msg.id ? "✓" : "Copy"}
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}

                {sending && (
                  <div className="dream-node-row agent">
                    <div className="dream-thinking-node">
                      <div className="dream-thinking-dots">
                        <span /><span /><span />
                      </div>
                      <span className="dream-thinking-label">Processing neural query…</span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Error toast */}
          {error && (
            <div className="dream-error-toast">
              <span>⚠ {error}</span>
              <button type="button" onClick={() => setError("")}>✕</button>
            </div>
          )}

          {/* Input Dock with Vocal Bars */}
          <div className="dream-input-dock">
            <div className="dream-vocal-wrap">
              <VocalBars state={agentState} />
            </div>

            <div className="dream-input-row">
              <button
                id="micBtn"
                type="button"
                className={`dream-mic-btn ${isRecording ? "recording" : ""} ${isTranscribing ? "processing" : ""}`}
                onClick={toggleRecording}
                title={isRecording ? "Stop recording" : "Start voice input"}
              >
                {isTranscribing ? (
                  <span className="dream-mic-spin">◌</span>
                ) : isRecording ? (
                  <span className="dream-mic-stop">■</span>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                    <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
                  </svg>
                )}
              </button>

              <textarea
                ref={textareaRef}
                id="promptInput"
                className="dream-textarea"
                placeholder="Speak your intent to the network…"
                value={draft}
                rows={1}
                onChange={e => {
                  setDraft(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
                }}
                onKeyDown={e => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
                }}
              />

              <button
                id="sendBtn"
                type="button"
                className={`dream-send-btn ${sending ? "sending" : ""}`}
                onClick={() => send()}
                disabled={sending || !draft.trim()}
              >
                {sending ? (
                  <span className="dream-send-spin">◌</span>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                  </svg>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Memories Drawer */}
        {showMemories && (
          <aside className="dream-memories-panel">
            <div className="dream-mem-header">
              <span className="dream-mem-title">Neural Memory Bank</span>
              <button type="button" className="dream-mem-close" onClick={() => setShowMemories(false)}>✕</button>
            </div>

            <div className="dream-mem-add">
              <input className="dream-mem-input" placeholder="Memory key" value={newMemKey} onChange={e => setNewMemKey(e.target.value)} />
              <input className="dream-mem-input" placeholder="Content to remember" value={newMemContent} onChange={e => setNewMemContent(e.target.value)} onKeyDown={e => e.key === "Enter" && handleAddMemory()} />
              <button type="button" className="dream-mem-add-btn" onClick={handleAddMemory}>+ Encode</button>
            </div>

            <div className="dream-mem-list">
              {memories.length === 0 ? (
                <p className="dream-mem-empty">No memories encoded yet. Interact with the agent to build its knowledge.</p>
              ) : (
                memories.map(m => (
                  <div key={m.id} className="dream-mem-item">
                    <div className="dream-mem-item-top">
                      <span className="dream-mem-key">{m.key}</span>
                      <span className="dream-mem-cat">{m.category}</span>
                    </div>
                    <p className="dream-mem-val">{m.content}</p>
                    <button type="button" className="dream-mem-del" onClick={() => handleDeleteMemory(m.key)}>Forget</button>
                  </div>
                ))
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
