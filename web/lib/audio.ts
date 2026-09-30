// Web Audio API Synthesizer for futuristic UI sound effects without external audio files

class SoundEngine {
  private ctx: AudioContext | null = null;
  private enabled: boolean = true;

  constructor() {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("pc-copilot-sound-enabled");
      if (stored !== null) {
        this.enabled = stored === "true";
      }
    }
  }

  private initCtx() {
    if (!this.ctx && typeof window !== "undefined") {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioCtx) {
        this.ctx = new AudioCtx();
      }
    }
    if (this.ctx && this.ctx.state === "suspended") {
      this.ctx.resume();
    }
  }

  public isEnabled(): boolean {
    return this.enabled;
  }

  public setEnabled(val: boolean) {
    this.enabled = val;
    if (typeof window !== "undefined") {
      localStorage.setItem("pc-copilot-sound-enabled", String(val));
    }
  }

  public playSend() {
    if (!this.enabled) return;
    try {
      this.initCtx();
      if (!this.ctx) return;

      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = "sine";
      const now = this.ctx.currentTime;
      osc.frequency.setValueAtTime(320, now);
      osc.frequency.exponentialRampToValueAtTime(720, now + 0.12);

      gain.gain.setValueAtTime(0.12, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.14);

      osc.connect(gain);
      gain.connect(this.ctx.destination);

      osc.start(now);
      osc.stop(now + 0.15);
    } catch {
      // ignore
    }
  }

  public playReceive() {
    if (!this.enabled) return;
    try {
      this.initCtx();
      if (!this.ctx) return;

      const now = this.ctx.currentTime;
      
      // Dual-tone harmonic chime
      [587.33, 880.00].forEach((freq, idx) => {
        if (!this.ctx) return;
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();

        osc.type = "sine";
        const delay = idx * 0.07;
        osc.frequency.setValueAtTime(freq, now + delay);

        gain.gain.setValueAtTime(0.08, now + delay);
        gain.gain.exponentialRampToValueAtTime(0.001, now + delay + 0.28);

        osc.connect(gain);
        gain.connect(this.ctx.destination);

        osc.start(now + delay);
        osc.stop(now + delay + 0.3);
      });
    } catch {
      // ignore
    }
  }

  public playWarning() {
    if (!this.enabled) return;
    try {
      this.initCtx();
      if (!this.ctx) return;

      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = "triangle";
      const now = this.ctx.currentTime;
      osc.frequency.setValueAtTime(440, now);
      osc.frequency.setValueAtTime(330, now + 0.1);

      gain.gain.setValueAtTime(0.15, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);

      osc.connect(gain);
      gain.connect(this.ctx.destination);

      osc.start(now);
      osc.stop(now + 0.36);
    } catch {
      // ignore
    }
  }

  public playClick() {
    if (!this.enabled) return;
    try {
      this.initCtx();
      if (!this.ctx) return;

      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = "sine";
      const now = this.ctx.currentTime;
      osc.frequency.setValueAtTime(900, now);

      gain.gain.setValueAtTime(0.05, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.04);

      osc.connect(gain);
      gain.connect(this.ctx.destination);

      osc.start(now);
      osc.stop(now + 0.05);
    } catch {
      // ignore
    }
  }
  public playGideonActivate() {
    if (!this.enabled) return;
    try {
      this.initCtx();
      if (!this.ctx) return;

      const now = this.ctx.currentTime;
      // Futuristic 3-tier quantum harmonic chord (Gideon awakening)
      [440, 659.25, 880, 1318.51].forEach((freq, idx) => {
        if (!this.ctx) return;
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();

        osc.type = "sine";
        const delay = idx * 0.045;
        osc.frequency.setValueAtTime(freq, now + delay);
        osc.frequency.exponentialRampToValueAtTime(freq * 1.05, now + delay + 0.35);

        gain.gain.setValueAtTime(0.08, now + delay);
        gain.gain.exponentialRampToValueAtTime(0.001, now + delay + 0.45);

        osc.connect(gain);
        gain.connect(this.ctx.destination);

        osc.start(now + delay);
        osc.stop(now + delay + 0.46);
      });
    } catch {
      // ignore
    }
  }
}

export const sound = new SoundEngine();
// Text to speech helper — Gideon British AI voice.
// Prefers the cloud ElevenLabs voice (consistent British accent on every device);
// falls back to the browser's British voices, then any English voice.

const TOKEN_KEY = "pc-agent-token";
let currentAudio: HTMLAudioElement | null = null;

function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, "Code block omitted.")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_#~]/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
}

async function cloudSpeak(text: string, onEnd?: () => void): Promise<boolean> {
  const token = window.sessionStorage.getItem(TOKEN_KEY) ?? "";
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) return false;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudio = audio;
    if (onEnd) {
      audio.onended = onEnd;
      audio.onerror = onEnd;
    }
    await audio.play();
    return true;
  } catch {
    return false;
  }
}

function browserSpeak(text: string, onEnd?: () => void) {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    onEnd?.();
    return;
  }

  // Brisk, clear British delivery (a touch quicker than plain speech)
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.06;
  utterance.pitch = 1.0;

  // Pick Gideon-style voice (British English preferred)
  const voices = window.speechSynthesis.getVoices();
  const gideonVoice =
    voices.find(
      (v) =>
        (v.lang === "en-GB" || v.lang.startsWith("en-GB")) &&
        (v.name.includes("Male") ||
          v.name.includes("Ryan") ||
          v.name.includes("George") ||
          v.name.includes("Daniel") ||
          v.name.includes("Female") ||
          v.name.includes("Natural") ||
          v.name.includes("Sonia") ||
          v.name.includes("Hazel") ||
          v.name.includes("Victoria") ||
          v.name.includes("Google") ||
          v.name.includes("Libby"))
    ) ||
    voices.find((v) => v.lang.startsWith("en-GB")) ||
    voices.find(
      (v) =>
        v.lang.startsWith("en") &&
        (v.name.includes("Natural") || v.name.includes("Google") || v.name.includes("Samantha"))
    ) ||
    voices.find((v) => v.lang.startsWith("en"));

  if (gideonVoice) {
    utterance.voice = gideonVoice;
  }

  if (onEnd) {
    utterance.onend = onEnd;
    utterance.onerror = onEnd;
  }

  window.speechSynthesis.speak(utterance);
}

export async function speakText(text: string, onEnd?: () => void) {
  if (typeof window === "undefined") return;
  stopSpeaking();
  const clean = stripMarkdown(text);
  if (!clean) return;

  if (!(await cloudSpeak(clean, onEnd))) {
    browserSpeak(clean, onEnd);
  }
}

export function stopSpeaking() {
  if (typeof window === "undefined") return;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}
