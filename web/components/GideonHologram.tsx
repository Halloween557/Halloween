"use client";

import { useEffect, useRef, useState } from "react";

export type HologramState = "idle" | "listening" | "thinking" | "speaking";

interface GideonHologramProps {
  state?: HologramState;
  interactive?: boolean;
  onActivate?: () => void;
  audioActive?: boolean;
}

export default function GideonHologram({
  state = "idle",
  interactive = true,
  onActivate,
  audioActive = false,
}: GideonHologramProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const [minimized, setMinimized] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let time = 0;
    const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;

    const resize = () => {
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
    };

    resize();
    window.addEventListener("resize", resize);

    // Particle clouds for Time Vault hologram effect
    const particles = Array.from({ length: 42 }, () => ({
      theta: Math.random() * Math.PI * 2,
      phi: Math.random() * Math.PI,
      radius: 40 + Math.random() * 55,
      speed: (0.004 + Math.random() * 0.008) * (Math.random() > 0.5 ? 1 : -1),
      size: 1 + Math.random() * 2,
      pulseOffset: Math.random() * Math.PI * 2,
    }));

    const render = () => {
      time += 0.02;
      const width = canvas.width / dpr;
      const height = canvas.height / dpr;
      const cx = width / 2;
      const cy = height / 2 - 4;

      ctx.clearRect(0, 0, width, height);

      // Colors based on state
      let primaryColor = "rgba(56, 189, 248, "; // cyan
      let accentColor = "rgba(147, 197, 253, ";  // light blue
      let glowColor = "rgba(14, 165, 233, ";    // sky blue
      let speedMultiplier = 1.0;

      if (state === "listening") {
        primaryColor = "rgba(251, 191, 36, ";   // amber gold (Gideon listening to Barry)
        accentColor = "rgba(254, 240, 138, ";
        glowColor = "rgba(245, 158, 11, ";
        speedMultiplier = 1.3;
      } else if (state === "thinking") {
        primaryColor = "rgba(168, 85, 247, ";   // quantum purple / tachyon pulse
        accentColor = "rgba(216, 180, 254, ";
        glowColor = "rgba(147, 51, 234, ";
        speedMultiplier = 2.4;
      } else if (state === "speaking") {
        primaryColor = "rgba(45, 212, 191, ";   // luminous emerald teal
        accentColor = "rgba(153, 246, 228, ";
        glowColor = "rgba(20, 184, 166, ";
        speedMultiplier = 1.6;
      }

      // 1. Holographic Light Cone from Projector Base
      const beamGrad = ctx.createLinearGradient(cx, height, cx, cy);
      beamGrad.addColorStop(0, primaryColor + "0.22)");
      beamGrad.addColorStop(0.7, primaryColor + "0.05)");
      beamGrad.addColorStop(1, "rgba(0, 0, 0, 0)");

      ctx.beginPath();
      ctx.moveTo(cx - 65, height);
      ctx.lineTo(cx + 65, height);
      ctx.lineTo(cx + 105, cy - 20);
      ctx.lineTo(cx - 105, cy - 20);
      ctx.closePath();
      ctx.fillStyle = beamGrad;
      ctx.fill();

      // Scanline beam sweep
      const scanY = (height - ((time * 35) % height));
      ctx.strokeStyle = primaryColor + "0.35)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cx - 75, scanY);
      ctx.lineTo(cx + 75, scanY);
      ctx.stroke();

      // 2. Projector Ring Base
      ctx.strokeStyle = primaryColor + "0.45)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.ellipse(cx, height - 12, 58, 10, 0, 0, Math.PI * 2);
      ctx.stroke();

      ctx.strokeStyle = accentColor + "0.8)";
      ctx.beginPath();
      ctx.ellipse(cx, height - 12, 38, 6, 0, 0, Math.PI * 2);
      ctx.stroke();

      // 3. Central Core Plasma & Pulsing Eye
      const pulse = Math.sin(time * 3 * speedMultiplier) * 0.15 + 0.85;
      const coreRadius = 24 * pulse * (state === "speaking" ? 1.25 : 1.0);

      const coreGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreRadius * 2.2);
      coreGlow.addColorStop(0, accentColor + "0.95)");
      coreGlow.addColorStop(0.3, primaryColor + "0.6)");
      coreGlow.addColorStop(0.7, glowColor + "0.2)");
      coreGlow.addColorStop(1, "rgba(0,0,0,0)");

      ctx.fillStyle = coreGlow;
      ctx.beginPath();
      ctx.arc(cx, cy, coreRadius * 2.2, 0, Math.PI * 2);
      ctx.fill();

      // Central Gideon Pupil / Quantum Singularity
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(cx, cy, 4.5 * pulse, 0, Math.PI * 2);
      ctx.fill();

      // 4. Gyroscopic 3D Orbital Rings (Time Vault Hologram Matrix)
      const draw3DRing = (
        tiltX: number,
        tiltY: number,
        rotSpeed: number,
        radius: number,
        numDots: number,
        alpha: number
      ) => {
        const ringTime = time * rotSpeed * speedMultiplier;
        ctx.strokeStyle = primaryColor + alpha + ")";
        ctx.fillStyle = accentColor + (alpha + 0.2) + ")";
        ctx.lineWidth = 1.2;

        ctx.beginPath();
        for (let i = 0; i <= numDots; i++) {
          const angle = (i / numDots) * Math.PI * 2;
          // 3D parametric circle rotation
          const x0 = radius * Math.cos(angle);
          const y0 = radius * Math.sin(angle);
          const z0 = 0;

          // Rotate around X
          const y1 = y0 * Math.cos(tiltX) - z0 * Math.sin(tiltX);
          const z1 = y0 * Math.sin(tiltX) + z0 * Math.cos(tiltX);

          // Rotate around Y
          const x2 = x0 * Math.cos(tiltY + ringTime) + z1 * Math.sin(tiltY + ringTime);
          const z2 = -x0 * Math.sin(tiltY + ringTime) + z1 * Math.cos(tiltY + ringTime);

          // Perspective projection
          const fov = 160;
          const scale = fov / (fov + z2 * 0.45);
          const px = cx + x2 * scale;
          const py = cy + y1 * scale;

          if (i === 0) {
            ctx.moveTo(px, py);
          } else {
            ctx.lineTo(px, py);
          }

          // Node glints on ring
          if (i % 8 === 0) {
            ctx.save();
            ctx.beginPath();
            ctx.arc(px, py, 2 * scale, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
          }
        }
        ctx.closePath();
        ctx.stroke();
      };

      // Ring 1: Equatorial Gyro
      draw3DRing(0.35, 0.45, 0.6, 68, 64, 0.7);

      // Ring 2: Polar Precessing Gyro
      draw3DRing(1.15, -0.65, -0.75, 76, 64, 0.6);

      // Ring 3: Tilted Outer Horizon Ring
      draw3DRing(-0.75, 0.95, 0.4, 86, 72, 0.45);

      // 5. Audio Waveform Spikes (when Gideon speaks or user listens)
      if (state === "speaking" || state === "listening" || audioActive) {
        const barCount = 36;
        for (let i = 0; i < barCount; i++) {
          const angle = (i / barCount) * Math.PI * 2;
          const waveHeight =
            Math.abs(Math.sin(time * 6 + i * 0.8)) * (state === "speaking" ? 18 : 12) + 3;
          const innerR = 48;
          const outerR = innerR + waveHeight;

          const x1 = cx + Math.cos(angle) * innerR;
          const y1 = cy + Math.sin(angle) * (innerR * 0.55);
          const x2 = cx + Math.cos(angle) * outerR;
          const y2 = cy + Math.sin(angle) * (outerR * 0.55);

          ctx.strokeStyle = accentColor + "0.85)";
          ctx.lineWidth = 1.8;
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.stroke();
        }
      }

      // 6. Holographic Cloud Particles
      particles.forEach((p) => {
        p.theta += p.speed * speedMultiplier;
        const x = p.radius * Math.sin(p.phi) * Math.cos(p.theta);
        const y = p.radius * Math.cos(p.phi);
        const z = p.radius * Math.sin(p.phi) * Math.sin(p.theta);

        const fov = 170;
        const scale = fov / (fov + z * 0.5);
        const px = cx + x * scale;
        const py = cy + y * scale * 0.65;

        const pAlpha =
          (Math.sin(time * 2 + p.pulseOffset) * 0.35 + 0.65) *
          Math.max(0.15, (z + 80) / 160);

        ctx.fillStyle = accentColor + pAlpha + ")";
        ctx.beginPath();
        ctx.arc(px, py, p.size * scale, 0, Math.PI * 2);
        ctx.fill();
      });

      // 7. Tactical HUD Ring Markers
      ctx.strokeStyle = primaryColor + "0.35)";
      ctx.setLineDash([4, 12]);
      ctx.beginPath();
      ctx.arc(cx, cy, 96, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);

      animFrameRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      window.removeEventListener("resize", resize);
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [state, audioActive]);

  return (
    <div
      className={`gideon-hologram-card ${minimized ? "minimized" : ""}`}
      onClick={() => interactive && onActivate && onActivate()}
      title="Gideon Holographic AI Matrix (Click to engage)"
    >
      <div className="hologram-hud-top">
        <div className="gideon-brand">
          <span className="gideon-dot" />
          <span className="gideon-title">G.I.D.E.O.N.</span>
          <span className="gideon-subtitle">TIME VAULT // COGNITIVE CORE</span>
        </div>
        <div className="hologram-actions">
          <span className={`status-pill ${state}`}>
            {state === "idle" && "STANDBY"}
            {state === "listening" && "ACOUSTIC RECEPTOR"}
            {state === "thinking" && "NEURAL PROCESSING"}
            {state === "speaking" && "VOCAL EMISSION"}
          </span>
          <button
            type="button"
            className="mini-toggle-btn"
            onClick={(e) => {
              e.stopPropagation();
              setMinimized(!minimized);
            }}
            aria-label="Toggle hologram size"
          >
            {minimized ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {!minimized && (
        <div className="canvas-wrapper">
          <canvas ref={canvasRef} className="hologram-canvas" />
          <div className="hologram-telemetry-overlay">
            <span className="telemetry-item">STABILITY: 99.98%</span>
            <span className="telemetry-item">FREQUENCY: 1420.4 MHz</span>
            <span className="telemetry-item">DIRECTIVE: AUTONOMOUS</span>
          </div>
        </div>
      )}
    </div>
  );
}
