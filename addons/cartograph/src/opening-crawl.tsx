import { useEffect, useRef } from "react";

const CRAWL_MS = 22000;

const CRAWL_BODY = `Compiled memory, mapped as sky.

Atlas stores are not wikis of folders.
They are claim-bearing pages — experience,
decision, work — joined by relates_to
and atlas:// across a mesh of skills.

Open any Atlas-compatible skill.
Lock a star. Read what the work
already knows.

The map remembers so you don't
have to grep the dark.`;

export function OpeningCrawl({ onDone }: { onDone: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      onDone();
      return;
    }
    const t = window.setTimeout(onDone, CRAWL_MS);
    return () => window.clearTimeout(t);
  }, [onDone]);

  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext("2d");
    if (!ctx) return;
    const stars = Array.from({ length: 160 }, () => ({
      x: Math.random(),
      y: Math.random(),
      z: 0.2 + Math.random() * 0.8,
      vx: (Math.random() - 0.5) * 0.00015,
    }));
    let raf = 0;
    const draw = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = cvs.clientWidth;
      const h = cvs.clientHeight;
      if (cvs.width !== Math.floor(w * dpr) || cvs.height !== Math.floor(h * dpr)) {
        cvs.width = Math.floor(w * dpr);
        cvs.height = Math.floor(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const bg =
        getComputedStyle(document.documentElement).getPropertyValue("--color-bg").trim() ||
        "#05080e";
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);
      for (const s of stars) {
        s.x += s.vx;
        if (s.x < 0) s.x += 1;
        if (s.x > 1) s.x -= 1;
        const a = 0.25 + s.z * 0.7;
        ctx.fillStyle = `rgba(232,238,246,${a})`;
        ctx.beginPath();
        ctx.arc(s.x * w, s.y * h, s.z * 1.4, 0, Math.PI * 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div className="relative h-dvh overflow-hidden bg-bg text-crawl">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden />
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-32 bg-gradient-to-b from-bg to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-40 bg-gradient-to-t from-bg to-transparent" />

      <p className="crawl-foreword pointer-events-none absolute inset-x-6 top-[18%] z-20 text-center font-sans text-sm text-experience md:text-base">
        A long time ago, in a skill library far, far away…
      </p>

      <div className="crawl-sky absolute inset-x-0 top-[28%] bottom-24 z-20">
        <div className="crawl-lane">
          <div className="crawl-text px-6 text-center">
            <p className="font-mono text-[10px] tracking-[0.4em] text-accent uppercase">Cartograph</p>
            <h1 className="mt-3 font-display text-3xl font-semibold tracking-wide text-crawl italic md:text-4xl">
              Episode Atlas
            </h1>
            <p className="mx-auto mt-6 max-w-md whitespace-pre-line font-sans text-base leading-relaxed font-medium md:text-xl">
              {CRAWL_BODY}
            </p>
          </div>
        </div>
      </div>

      <div className="absolute inset-x-0 bottom-0 z-30 flex justify-center p-4">
        <button
          type="button"
          onClick={onDone}
          className="min-h-11 rounded-xl border border-border bg-surface/80 px-5 text-sm text-fg backdrop-blur-md"
        >
          Skip
        </button>
      </div>
    </div>
  );
}
