import { useEffect, useRef } from "react";

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
    const r = 0.06 + rand() * 0.98;
    out.push({
      x: Math.cos(a) * r,
      y: Math.sin(a) * r * 0.62,
      z: rand(),
      s: 0.4 + rand() * 1.4,
      hue: rand(),
    });
  }
  return out;
}

/** Persistent crawl / welcome / hyperspace field. `warp` 0 = still sky, 1 = full jump. */
export function StarSky({ warp, flash }: { warp: number; flash: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const warpRef = useRef(warp);
  const flashRef = useRef(flash);
  warpRef.current = warp;
  flashRef.current = flash;

  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext("2d");
    if (!ctx) return;
    const stars = seed(480);
    let raf = 0;
    let last = performance.now();

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const wAmt = warpRef.current;
      const flash = flashRef.current;
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
      const vg = ctx.createRadialGradient(w * 0.5, h * 0.48, 6, w * 0.5, h * 0.5, Math.max(w, h) * 0.72);
      vg.addColorStop(0, `rgba(36, 72, 128, ${0.14 + wAmt * 0.2})`);
      vg.addColorStop(0.5, "rgba(8, 14, 28, 0.35)");
      vg.addColorStop(1, "#020308");
      ctx.fillStyle = vg;
      ctx.fillRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      const focal = Math.min(w, h) * 0.55;
      const vz = (0.018 + wAmt * 3.35) * dt;

      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      for (const star of stars) {
        star.z -= vz * star.s;
        if (star.z <= 0.04) {
          star.z += 0.96;
          const a = Math.random() * Math.PI * 2;
          const r = 0.06 + Math.random() * 0.98;
          star.x = Math.cos(a) * r;
          star.y = Math.sin(a) * r * 0.62;
        }
        const z = Math.max(0.04, star.z);
        const sx = cx + (star.x / z) * focal;
        const sy = cy + (star.y / z) * focal;
        const trail = 0.01 + wAmt * (0.08 + star.s * 0.16);
        const z2 = Math.min(1.2, z + trail);
        const px = cx + (star.x / z2) * focal;
        const py = cy + (star.y / z2) * focal;
        const near = 1 - z;
        const a = (0.22 + near * 0.78) * (0.4 + wAmt * 0.6);
        const col = star.hue > 0.72 ? "180, 230, 255" : "232, 240, 255";
        if (wAmt > 0.04) {
          const g = ctx.createLinearGradient(px, py, sx, sy);
          g.addColorStop(0, `rgba(${col}, 0)`);
          g.addColorStop(0.5, `rgba(${col}, ${a * 0.4})`);
          g.addColorStop(1, `rgba(${col}, ${a})`);
          ctx.strokeStyle = g;
          ctx.lineWidth = 0.55 + star.s * (0.45 + wAmt * 1.85) * (0.35 + near);
          ctx.lineCap = "round";
          ctx.beginPath();
          ctx.moveTo(px, py);
          ctx.lineTo(sx, sy);
          ctx.stroke();
        } else {
          ctx.fillStyle = `rgba(${col}, ${0.28 + near * 0.7})`;
          ctx.beginPath();
          ctx.arc(sx, sy, 0.45 + star.s * 1.05 * (0.35 + near), 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.restore();

      if (flash > 0.02) {
        ctx.fillStyle = `rgba(236, 246, 255, ${0.55 * flash})`;
        ctx.fillRect(0, 0, w, h);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden />;
}
