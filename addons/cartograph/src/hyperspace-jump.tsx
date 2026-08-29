import { useEffect, useRef } from "react";

const JUMP_MS = 3400;

type Star = { x: number; y: number; z: number; s: number; hue: number };

function seed(n: number): Star[] {
  const out: Star[] = [];
  let h = 2166136261;
  const rand = () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
  };
  for (let i = 0; i < n; i++) {
    const a = rand() * Math.PI * 2;
    const r = 0.08 + rand() * 0.95;
    out.push({
      x: Math.cos(a) * r,
      y: Math.sin(a) * r * 0.62,
      z: rand(),
      s: 0.45 + rand() * 1.35,
      hue: rand(),
    });
  }
  return out;
}

function smooth(t: number) {
  const x = Math.max(0, Math.min(1, t));
  return x * x * (3 - 2 * x);
}

/** 0 still · 1 full stretch */
function warpAt(u: number) {
  if (u < 0.16) return smooth(u / 0.16);
  if (u < 0.55) return 1;
  if (u < 0.88) return 1 - smooth((u - 0.55) / 0.33);
  return 0;
}

function flashAt(u: number) {
  const d = Math.abs(u - 0.8) / 0.07;
  return Math.max(0, 1 - d * d);
}

export function HyperspaceJump({ onDone }: { onDone: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      done.current();
      return;
    }
    const t = window.setTimeout(() => done.current(), JUMP_MS);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext("2d");
    if (!ctx) return;
    const stars = seed(520);
    const t0 = performance.now();
    let raf = 0;
    let last = t0;

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const u = Math.min(1, (now - t0) / JUMP_MS);
      const warp = warpAt(u);
      const flash = flashAt(u);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = cvs.clientWidth;
      const h = cvs.clientHeight;
      if (cvs.width !== Math.floor(w * dpr) || cvs.height !== Math.floor(h * dpr)) {
        cvs.width = Math.floor(w * dpr);
        cvs.height = Math.floor(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      ctx.fillStyle = "#020308";
      ctx.fillRect(0, 0, w, h);
      const vg = ctx.createRadialGradient(w * 0.5, h * 0.5, 4, w * 0.5, h * 0.5, Math.max(w, h) * 0.7);
      vg.addColorStop(0, `rgba(40, 80, 140, ${0.18 + warp * 0.22})`);
      vg.addColorStop(0.45, "rgba(8, 14, 28, 0.4)");
      vg.addColorStop(1, "#020308");
      ctx.fillStyle = vg;
      ctx.fillRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      const focal = Math.min(w, h) * 0.55;
      const vz = (0.22 + warp * 3.4) * dt;

      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      for (const star of stars) {
        star.z -= vz * star.s;
        if (star.z <= 0.04) {
          star.z += 0.96;
          const a = Math.random() * Math.PI * 2;
          const r = 0.08 + Math.random() * 0.95;
          star.x = Math.cos(a) * r;
          star.y = Math.sin(a) * r * 0.62;
        }
        const z = Math.max(0.04, star.z);
        const sx = cx + (star.x / z) * focal;
        const sy = cy + (star.y / z) * focal;
        const trail = 0.012 + warp * (0.08 + star.s * 0.16);
        const z2 = Math.min(1.2, z + trail);
        const px = cx + (star.x / z2) * focal;
        const py = cy + (star.y / z2) * focal;
        const near = 1 - z;
        const a = (0.25 + near * 0.75) * (0.35 + warp * 0.65);
        const cyan = star.hue > 0.72;
        const col = cyan ? "180, 230, 255" : "232, 240, 255";
        if (warp > 0.05) {
          const g = ctx.createLinearGradient(px, py, sx, sy);
          g.addColorStop(0, `rgba(${col}, 0)`);
          g.addColorStop(0.55, `rgba(${col}, ${a * 0.45})`);
          g.addColorStop(1, `rgba(${col}, ${a})`);
          ctx.strokeStyle = g;
          ctx.lineWidth = 0.6 + star.s * (0.5 + warp * 1.8) * (0.4 + near);
          ctx.lineCap = "round";
          ctx.beginPath();
          ctx.moveTo(px, py);
          ctx.lineTo(sx, sy);
          ctx.stroke();
        } else {
          ctx.fillStyle = `rgba(${col}, ${a})`;
          ctx.beginPath();
          ctx.arc(sx, sy, 0.4 + star.s * 1.1 * (0.4 + near), 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.restore();

      if (flash > 0.02) {
        ctx.fillStyle = `rgba(236, 246, 255, ${0.55 * flash})`;
        ctx.fillRect(0, 0, w, h);
      }

      if (u < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div className="relative h-dvh overflow-hidden bg-bg">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden />
      <button
        type="button"
        onClick={() => done.current()}
        className="absolute right-4 bottom-4 z-10 min-h-11 rounded-full border border-border bg-surface/70 px-4 text-xs tracking-wide text-muted uppercase backdrop-blur-sm"
      >
        Skip
      </button>
    </div>
  );
}
