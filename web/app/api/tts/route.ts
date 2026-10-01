import { NextResponse } from "next/server";
import { checkAuth } from "@/lib/auth";
import { MsEdgeTTS, OUTPUT_FORMAT } from "msedge-tts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// ---------------------------------------------------------------------------
// Voice priority:
//   1. ElevenLabs (Daniel – UK male) — if ELEVEN_API_KEY set & quota available
//   2. Microsoft Edge TTS (en-GB-RyanNeural) — free, no quota, no API key
// ---------------------------------------------------------------------------

const ELEVEN_API_KEY = process.env.ELEVEN_API_KEY;
const ELEVEN_VOICE_ID =
  process.env.ELEVEN_VOICE_ID ?? "onwK4e9ZLuTAKqWW03F9"; // Daniel – UK male

// ── ElevenLabs ──────────────────────────────────────────────────────────────

async function elevenLabsTts(text: string): Promise<NextResponse | null> {
  if (!ELEVEN_API_KEY) return null;
  const models = ["eleven_multilingual_v2", "eleven_monolingual_v1"];
  for (const model of models) {
    try {
      const res = await fetch(
        `https://api.elevenlabs.io/v1/text-to-speech/${ELEVEN_VOICE_ID}`,
        {
          method: "POST",
          headers: {
            "xi-api-key": ELEVEN_API_KEY,
            "Content-Type": "application/json",
            Accept: "audio/mpeg",
          },
          body: JSON.stringify({
            text,
            model_id: model,
            voice_settings: { stability: 0.45, similarity_boost: 0.8, style: 0.2 },
          }),
        }
      );
      if (res.ok) {
        const audio = Buffer.from(await res.arrayBuffer());
        return new NextResponse(audio, {
          status: 200,
          headers: {
            "Content-Type": "audio/mpeg",
            "Cache-Control": "no-store",
            "X-TTS-Engine": "elevenlabs",
          },
        });
      }
      const err = await res.text().catch(() => "");
      console.warn(`[TTS] ElevenLabs ${model} failed (${res.status}):`, err);
    } catch (e) {
      console.warn("[TTS] ElevenLabs network error:", e);
    }
  }
  return null;
}

// ── Microsoft Edge TTS — en-GB-RyanNeural (free British male neural voice) ──

async function edgeTts(text: string): Promise<NextResponse | null> {
  try {
    const tts = new MsEdgeTTS();
    await tts.setMetadata(
      "en-GB-RyanNeural",
      OUTPUT_FORMAT.AUDIO_24KHZ_96KBITRATE_MONO_MP3
    );

    // Wrap in a Promise to collect the audio stream
    const audio = await new Promise<Buffer>((resolve, reject) => {
      try {
        const { audioStream } = tts.toStream(text);
        const chunks: Buffer[] = [];
        audioStream.on("data", (chunk: Buffer) => chunks.push(chunk));
        audioStream.on("end", () => resolve(Buffer.concat(chunks)));
        audioStream.on("error", reject);
      } catch (e) {
        reject(e);
      }
    });

    if (!audio || audio.length === 0) return null;

    return new NextResponse(new Uint8Array(audio), {
      status: 200,
      headers: {
        "Content-Type": "audio/mpeg",
        "Cache-Control": "no-store",
        "X-TTS-Engine": "edge-ryan-gb",
      },
    });
  } catch (e) {
    console.warn("[TTS] Edge TTS error:", e);
    return null;
  }
}

// ── Main handler ─────────────────────────────────────────────────────────────

export async function POST(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;

  const body = (await req.json().catch(() => ({}))) as { text?: string };
  const text = (body.text ?? "").trim().slice(0, 2000);
  if (!text) return NextResponse.json({ error: "no text" }, { status: 400 });

  // Try ElevenLabs first (best quality), then Edge TTS (always free)
  const result = (await elevenLabsTts(text)) ?? (await edgeTts(text));

  if (result) return result;

  return NextResponse.json({ error: "All TTS engines failed" }, { status: 500 });
}