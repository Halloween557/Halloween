import { NextResponse } from "next/server";
import { checkAuth } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_KEY = process.env.ELEVEN_API_KEY;
const FIXED_VOICE = process.env.ELEVEN_VOICE_ID;
const MODELS = ["eleven_multilingual_v2", "eleven_monolingual_v1"];

// UK premade voices, tried in order until one synthesizes on this key.
// Daniel (British, male) is verified working; the rest are fallbacks for
// accounts with different voice sets.
const BRITISH_VOICES = [
  "onwK4e9ZLuTAKqWW03F9", // Daniel - UK male
  "AZnzlk1XvdacUQEj1gxn", // Domi - UK female
  "XrExE9yKIg1Wjnnl2kAx", // George - UK male
  "JS3qFdMiah4wzXGQlvfs", // Freya - UK female
];

let cachedVoiceId: string | null = null;

interface ElevenVoice {
  voice_id: string;
  name: string;
  category?: string;
  labels?: Record<string, string>;
  description?: string;
}

function britishScore(v: ElevenVoice): number {
  const hay = [
    v.name,
    v.labels?.accent ?? "",
    v.labels?.description ?? "",
    v.labels?.["language_region"] ?? "",
    v.labels?.language ?? "",
    v.description ?? "",
  ].join(" ").toLowerCase();
  let score = 0;
  if (hay.includes("british")) score += 4;
  if (hay.includes("en-gb") || hay.includes("english (uk)") || hay.includes("english (gb)")) score += 3;
  if (v.name.toLowerCase().includes("george") || v.name.toLowerCase().includes("callum") ||
      v.name.toLowerCase().includes("freya") || v.name.toLowerCase().includes("domi")) score += 2;
  if (v.category === "premade") score += 1;
  return score;
}

async function pickVoice(): Promise<string | null> {
  if (FIXED_VOICE) return FIXED_VOICE;
  if (!API_KEY) return null;
  try {
    const res = await fetch("https://api.elevenlabs.io/v1/voices", {
      headers: { "xi-api-key": API_KEY },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { voices?: ElevenVoice[] };
    const voices = data.voices ?? [];
    const candidates = voices
      .map((v) => ({ v, score: britishScore(v) }))
      .sort((a, b) => b.score - a.score);
    const best = candidates[0];
    return best && best.score > 0 ? best.v.voice_id : null;
  } catch {
    return null;
  }
}

async function synthesize(voiceId: string, text: string): Promise<NextResponse | null> {
  for (const model of MODELS) {
    try {
      const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`, {
        method: "POST",
        headers: {
          "xi-api-key": API_KEY!,
          "Content-Type": "application/json",
          Accept: "audio/mpeg",
        },
        body: JSON.stringify({
          text,
          model_id: model,
          voice_settings: { stability: 0.45, similarity_boost: 0.8, style: 0.2 },
        }),
      });
      if (res.ok) {
        const audio = Buffer.from(await res.arrayBuffer());
        return new NextResponse(audio, {
          status: 200,
          headers: { "Content-Type": "audio/mpeg", "Cache-Control": "no-store" },
        });
      }
      await res.text().catch(() => "");
    } catch {
      // try next model / voice
    }
  }
  return null;
}

export async function POST(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;
  if (!API_KEY) {
    return NextResponse.json({ error: "ELEVEN_API_KEY not configured" }, { status: 500 });
  }
  const body = (await req.json().catch(() => ({}))) as { text?: string; voice_id?: string };
  const text = (body.text ?? "").trim().slice(0, 2000);
  if (!text) return NextResponse.json({ error: "no text" }, { status: 400 });

  const candidates = [
    FIXED_VOICE,
    body.voice_id,
    cachedVoiceId,
    await pickVoice(),
    ...BRITISH_VOICES,
  ].filter((v): v is string => Boolean(v));

  let last: NextResponse | null = null;
  for (const voiceId of candidates) {
    last = await synthesize(voiceId, text);
    if (last) {
      cachedVoiceId = voiceId;
      return last;
    }
  }
  return NextResponse.json(
    { error: "no suitable TTS voice/model succeeded for this key" },
    { status: 500 },
  );
}