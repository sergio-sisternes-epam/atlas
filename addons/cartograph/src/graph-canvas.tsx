import { useEffect, useRef, useState, type ReactNode } from "react";
import { LocateFixed, Maximize2, Minimize2, Minus, Plus } from "lucide-react";
import type { GraphEdge, GraphNode, NodeKind } from "./atlas/types";
import { layoutUniverse } from "./atlas/universe";

type SimNode = GraphNode & {
  lon: number;
  lat: number;
  shell: number;
  targetShell: number;
  mass: number;
  galaxy: string;
  born: number;
  wx: number;
  wy: number;
  wz: number;
  sx: number;
  sy: number;
  depth: number;
  r: number;
};

type Vec3 = { x: number; y: number; z: number };

type Cam = {
  x: number;
  y: number;
  k: number;
  targetK: number | null;
  yaw: number;
  pitch: number;
  vYaw: number;
  vPitch: number;
  pivot: Vec3;
};

type Scene = {
  sim: SimNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  query: string;
  cam: Cam;
  spin: null | {
    pointerId: number;
    x: number;
    y: number;
    yaw: number;
    pitch: number;
    moved: boolean;
    hitId: string | null;
  };
  hover: string | null;
  w: number;
  h: number;
  t: number;
  reduce: boolean;
  pointers: Map<number, { x: number; y: number }>;
  pinch: null | { dist: number; k: number; mx: number; my: number; cx: number; cy: number };
};

const KIND_CORE: Record<NodeKind, string> = {
  experience: "#d4e4ff",
  decision: "#8ec8c0",
  work: "#e8f2ff",
  lesson: "#b8d4c8",
  recipe: "#c4d4e8",
  index: "#f0f4fa",
  page: "#7d8eaa",
  knowledge: "#d4e4ff",
  raw: "#7d8eaa",
  module: "#8ec8c0",
};

const KIND_GLOW: Record<NodeKind, string> = {
  experience: "rgba(130, 180, 255, 0.5)",
  decision: "rgba(80, 200, 190, 0.45)",
  work: "rgba(170, 210, 255, 0.55)",
  lesson: "rgba(120, 190, 160, 0.4)",
  recipe: "rgba(140, 170, 210, 0.42)",
  index: "rgba(170, 210, 255, 0.55)",
  page: "rgba(110, 140, 190, 0.28)",
  knowledge: "rgba(130, 180, 255, 0.5)",
  raw: "rgba(110, 140, 190, 0.28)",
  module: "rgba(80, 200, 190, 0.42)",
};

const MIN_K = 0.22;
const MAX_K = 20;

type BgStar = { lon: number; lat: number; mag: number; tw: number };
const BG_STARS: BgStar[] = Array.from({ length: 280 }, (_, i) => {
  let h = 2166136261 ^ (i * 2654435761);
  const rand = () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
  };
  return {
    lon: rand() * Math.PI * 2,
    lat: Math.acos(2 * rand() - 1),
    mag: 0.25 + rand() * 0.85,
    tw: rand() * Math.PI * 2,
  };
});

function drawStarfield(ctx: CanvasRenderingContext2D, s: Scene) {
  const { w, h, cam, t } = s;
  const cx = w / 2 + cam.x * 0.08;
  const cy = h / 2 + cam.y * 0.08;
  const far = Math.max(w, h) * 0.72;
  const cyaw = Math.cos(cam.yaw * 0.35);
  const syaw = Math.sin(cam.yaw * 0.35);
  const cp = Math.cos(cam.pitch * 0.35);
  const sp = Math.sin(cam.pitch * 0.35);
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const star of BG_STARS) {
    const r = far;
    const x0 = r * Math.sin(star.lat) * Math.cos(star.lon);
    const y0 = r * Math.cos(star.lat);
    const z0 = r * Math.sin(star.lat) * Math.sin(star.lon);
    const x1 = x0 * cyaw - z0 * syaw;
    const z1 = x0 * syaw + z0 * cyaw;
    const y2 = y0 * cp - z1 * sp;
    const z2 = y0 * sp + z1 * cp;
    if (z2 > far * 0.15) continue;
    const twinkle = 0.55 + 0.45 * Math.sin(t * 1.4 + star.tw);
    const size = 0.5 + star.mag * 1.35;
    const alpha = (0.18 + star.mag * 0.55) * twinkle;
    ctx.fillStyle = `rgba(190, 220, 255, ${alpha})`;
    ctx.beginPath();
    ctx.arc(cx + x1 * 0.55, cy + y2 * 0.55, size, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function homeCam(): Cam {
  return {
    x: 0,
    y: 0,
    k: 1,
    targetK: null,
    yaw: 0.55,
    pitch: 0.72,
    vYaw: 0,
    vPitch: 0,
    pivot: { x: 0, y: 0, z: 0 },
  };
}

function globeR(s: Scene) {
  return Math.min(s.w, s.h) * 0.54;
}

function nodeWorld(n: SimNode, R: number): Vec3 {
  const r = R * n.shell;
  return {
    x: r * Math.sin(n.lat) * Math.cos(n.lon),
    y: r * Math.cos(n.lat),
    z: r * Math.sin(n.lat) * Math.sin(n.lon),
  };
}

function mainNode(nodes: SimNode[]): SimNode | undefined {
  if (!nodes.length) return undefined;
  return nodes.reduce((best, n) => (n.mass > best.mass ? n : best));
}

function starRadius(degree: number, kind: NodeKind): number {
  const links = Math.max(0, degree);
  const byLinks = 0.7 + Math.log1p(links) * 1.45;
  const kindPad =
    kind === "raw" || kind === "page" ? 0 : kind === "index" || kind === "work" ? 0.6 : 0.25;
  return Math.min(8.5, byLinks + kindPad);
}

function applyZoom(s: Scene, nextK: number, sx: number, sy: number) {
  s.cam.targetK = null;
  const prev = s.cam.k || 1;
  const k = Math.min(MAX_K, Math.max(MIN_K, nextK));
  const worldX = (sx - s.w / 2 - s.cam.x) / prev;
  const worldY = (sy - s.h / 2 - s.cam.y) / prev;
  s.cam.k = k;
  s.cam.x = sx - s.w / 2 - worldX * k;
  s.cam.y = sy - s.h / 2 - worldY * k;
}

function pointerDist(a: { x: number; y: number }, b: { x: number; y: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function projectGlobe(s: Scene) {
  const R = globeR(s);
  const focal = R * 2.15;
  const cyaw = Math.cos(s.cam.yaw);
  const syaw = Math.sin(s.cam.yaw);
  const cp = Math.cos(s.cam.pitch);
  const sp = Math.sin(s.cam.pitch);
  const { pivot, x: panX, y: panY, k } = s.cam;

  for (const n of s.sim) {
    const w = nodeWorld(n, R);
    const x0 = w.x - pivot.x;
    const y0 = w.y - pivot.y;
    const z0 = w.z - pivot.z;
    const x1 = x0 * cyaw - z0 * syaw;
    const z1 = x0 * syaw + z0 * cyaw;
    const y2 = y0 * cp - z1 * sp;
    const z2 = y0 * sp + z1 * cp;
    const scale = focal / (focal + z2);
    n.wx = x1;
    n.wy = y2;
    n.wz = z2;
    n.sx = s.w / 2 + panX + x1 * scale * k;
    n.sy = s.h / 2 + panY + y2 * scale * k;
    n.depth = focal + z2 > 0 ? scale : 0.15;
  }
}

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  query: string;
  onSelect: (id: string | null) => void;
  focused?: boolean;
  onToggleFocus?: () => void;
};

export function GraphCanvas({
  nodes,
  edges,
  selectedId,
  query,
  onSelect,
  focused,
  onToggleFocus,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [zoomPct, setZoomPct] = useState(100);
  const state = useRef<Scene>({
    sim: [],
    edges: [],
    selectedId: null,
    query: "",
    cam: homeCam(),
    spin: null,
    hover: null,
    w: 800,
    h: 600,
    t: 0,
    reduce: false,
    pointers: new Map(),
    pinch: null,
  });

  const syncZoom = () => setZoomPct(Math.round(state.current.cam.k * 100));

  const zoomBy = (factor: number) => {
    const s = state.current;
    applyZoom(s, s.cam.k * factor, s.w / 2, s.h / 2);
    syncZoom();
  };

  const resetCam = () => {
    state.current.cam = homeCam();
    syncZoom();
  };

  useEffect(() => {
    const s = state.current;
    const byId = new Map(s.sim.map((n) => [n.id, n]));
    const laid = layoutUniverse(nodes, edges);
    s.sim = laid.map((n) => {
      const prev = byId.get(n.id);
      return {
        ...n,
        lon: n.lon,
        lat: n.lat,
        targetShell: n.targetShell,
        shell: prev?.shell ?? 0.012,
        mass: n.mass,
        galaxy: n.galaxy,
        born: prev?.born ?? s.t,
        wx: prev?.wx ?? 0,
        wy: prev?.wy ?? 0,
        wz: prev?.wz ?? 0,
        sx: prev?.sx ?? s.w / 2,
        sy: prev?.sy ?? s.h / 2,
        depth: prev?.depth ?? 1,
        r: starRadius(n.degree, n.kind),
      };
    });
    s.edges = edges;
  }, [nodes, edges]);

  useEffect(() => {
    const s = state.current;
    s.selectedId = selectedId;
    if (selectedId && s.cam.k < 2) {
      s.cam.targetK = Math.min(2.4, Math.max(s.cam.k * 1.15, 1.55));
    }
  }, [selectedId]);

  useEffect(() => {
    state.current.query = query;
  }, [query]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    state.current.reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let raf = 0;
    let running = true;
    let last = performance.now();
    let lastShownZoom = Math.round(state.current.cam.k * 100);

    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      state.current.w = rect.width;
      state.current.h = rect.height;
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);

    const tick = (now: number) => {
      if (!running) return;
      const dt = Math.min(0.033, (now - last) / 1000);
      last = now;
      const s = state.current;
      s.t += s.reduce ? 0 : dt;
      for (const n of s.sim) {
        const age = Math.max(0, s.t - n.born);
        const speed = s.reduce ? 20 : 0.42 + n.mass * 0.35;
        const expand = 1 - Math.exp(-age * speed);
        n.shell += (n.targetShell * expand - n.shell) * Math.min(1, dt * 3.2);
      }
      const R = globeR(s);
      const focus = s.selectedId ? s.sim.find((n) => n.id === s.selectedId) : undefined;
      const ease = s.reduce ? 1 : 1 - Math.exp(-dt * 2.6);
      if (focus) {
        const dest = nodeWorld(focus, R);
        s.cam.pivot.x += (dest.x - s.cam.pivot.x) * ease;
        s.cam.pivot.y += (dest.y - s.cam.pivot.y) * ease;
        s.cam.pivot.z += (dest.z - s.cam.pivot.z) * ease;
      } else {
        s.cam.pivot.x += (0 - s.cam.pivot.x) * ease;
        s.cam.pivot.y += (0 - s.cam.pivot.y) * ease;
        s.cam.pivot.z += (0 - s.cam.pivot.z) * ease;
      }
      s.cam.x += (0 - s.cam.x) * ease;
      s.cam.y += (0 - s.cam.y) * ease;
      if (s.cam.targetK != null) {
        s.cam.k += (s.cam.targetK - s.cam.k) * ease;
        if (Math.abs(s.cam.k - s.cam.targetK) < 0.012) {
          s.cam.k = s.cam.targetK;
          s.cam.targetK = null;
        }
        const pct = Math.round(s.cam.k * 100);
        if (pct !== lastShownZoom) {
          lastShownZoom = pct;
          setZoomPct(pct);
        }
      }
      if (!s.spin) {
        if (!s.reduce && !s.selectedId) s.cam.yaw += 0.16 * dt;
        s.cam.yaw += s.cam.vYaw;
        s.cam.pitch += s.cam.vPitch;
        s.cam.vYaw *= 0.92;
        s.cam.vPitch *= 0.92;
      }
      s.cam.pitch = Math.max(-1.2, Math.min(1.2, s.cam.pitch));
      projectGlobe(s);
      draw(ctx, s);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    const toLocal = (clientX: number, clientY: number) => {
      const rect = canvas.getBoundingClientRect();
      return { x: clientX - rect.left, y: clientY - rect.top };
    };

    const hit = (lx: number, ly: number) => {
      const s = state.current;
      let best: SimNode | null = null;
      let bestD = Infinity;
      for (const n of s.sim) {
        if (n.depth < 0.62) continue;
        const dx = lx - n.sx;
        const dy = ly - n.sy;
        const d2 = dx * dx + dy * dy;
        const rad = Math.max(8, n.r * n.depth + 5);
        if (d2 <= rad * rad && d2 < bestD) {
          best = n;
          bestD = d2;
        }
      }
      return best;
    };

    const pinchPair = () => {
      const pts = [...state.current.pointers.values()];
      if (pts.length < 2) return null;
      return { a: pts[0]!, b: pts[1]! };
    };

    const onDown = (ev: PointerEvent) => {
      if ((ev.target as HTMLElement | null)?.closest("button")) return;
      if (ev.button > 2) return;
      ev.preventDefault();
      const rect = canvas.getBoundingClientRect();
      state.current.pointers.set(ev.pointerId, {
        x: ev.clientX - rect.left,
        y: ev.clientY - rect.top,
      });
      try {
        wrap.setPointerCapture(ev.pointerId);
      } catch {
        /* ignore */
      }
      if (state.current.pointers.size >= 2) {
        const pair = pinchPair();
        if (pair) {
          state.current.pinch = {
            dist: pointerDist(pair.a, pair.b) || 1,
            k: state.current.cam.k,
            mx: (pair.a.x + pair.b.x) / 2,
            my: (pair.a.y + pair.b.y) / 2,
            cx: state.current.cam.x,
            cy: state.current.cam.y,
          };
          state.current.spin = null;
        }
        return;
      }
      const p = toLocal(ev.clientX, ev.clientY);
      const n = hit(p.x, p.y);
      state.current.cam.vYaw = 0;
      state.current.cam.vPitch = 0;
      state.current.spin = {
        pointerId: ev.pointerId,
        x: ev.clientX,
        y: ev.clientY,
        yaw: state.current.cam.yaw,
        pitch: state.current.cam.pitch,
        moved: false,
        hitId: n?.id ?? null,
      };
    };

    const onMove = (ev: PointerEvent) => {
      ev.preventDefault();
      const rect = canvas.getBoundingClientRect();
      if (state.current.pointers.has(ev.pointerId)) {
        state.current.pointers.set(ev.pointerId, {
          x: ev.clientX - rect.left,
          y: ev.clientY - rect.top,
        });
      }
      const pair = pinchPair();
      if (pair && state.current.pinch) {
        const dist = pointerDist(pair.a, pair.b) || 1;
        const midX = (pair.a.x + pair.b.x) / 2;
        const midY = (pair.a.y + pair.b.y) / 2;
        const scaleDelta = dist / state.current.pinch.dist;
        if (Math.abs(scaleDelta - 1) > 0.04) {
          applyZoom(state.current, state.current.pinch.k * scaleDelta, midX, midY);
          setZoomPct(Math.round(state.current.cam.k * 100));
        } else {
          state.current.cam.x = state.current.pinch.cx + (midX - state.current.pinch.mx);
          state.current.cam.y = state.current.pinch.cy + (midY - state.current.pinch.my);
        }
        return;
      }
      const g = state.current.spin;
      if (g && g.pointerId === ev.pointerId) {
        const dx = ev.clientX - g.x;
        const dy = ev.clientY - g.y;
        if (!g.moved && Math.hypot(dx, dy) > 6) g.moved = true;
        if (g.moved) {
          if (ev.shiftKey || ev.buttons === 2) {
            state.current.cam.x += ev.movementX || 0;
            state.current.cam.y += ev.movementY || 0;
          } else {
            state.current.cam.yaw = g.yaw + dx * 0.014;
            state.current.cam.pitch = Math.max(-1.2, Math.min(1.2, g.pitch + dy * 0.01));
            state.current.cam.vYaw = (ev.movementX || 0) * 0.008;
            state.current.cam.vPitch = (ev.movementY || 0) * 0.006;
          }
          canvas.style.cursor = "grabbing";
        }
        return;
      }
      const p = toLocal(ev.clientX, ev.clientY);
      const n = hit(p.x, p.y);
      state.current.hover = n?.id ?? null;
      canvas.style.cursor = n ? "pointer" : "grab";
    };

    const onUp = (ev: PointerEvent) => {
      state.current.pointers.delete(ev.pointerId);
      if (state.current.pointers.size < 2) state.current.pinch = null;
      const g = state.current.spin;
      if (g && g.pointerId === ev.pointerId) {
        if (!g.moved) onSelect(g.hitId);
        state.current.spin = null;
      }
      canvas.style.cursor = "grab";
    };

    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const rect = canvas.getBoundingClientRect();
      applyZoom(
        state.current,
        state.current.cam.k * (ev.deltaY < 0 ? 1.1 : 0.9),
        ev.clientX - rect.left,
        ev.clientY - rect.top,
      );
      setZoomPct(Math.round(state.current.cam.k * 100));
    };

    const onKey = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        state.current.cam.yaw -= 0.12;
      } else if (ev.key === "ArrowRight") {
        ev.preventDefault();
        state.current.cam.yaw += 0.12;
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        state.current.cam.pitch = Math.max(-1.2, state.current.cam.pitch - 0.08);
      } else if (ev.key === "ArrowDown") {
        ev.preventDefault();
        state.current.cam.pitch = Math.min(1.2, state.current.cam.pitch + 0.08);
      } else if (ev.key === "+" || ev.key === "=") {
        ev.preventDefault();
        zoomBy(1.2);
      } else if (ev.key === "-" || ev.key === "_") {
        ev.preventDefault();
        zoomBy(1 / 1.2);
      } else if (ev.key === "0") {
        ev.preventDefault();
        resetCam();
      }
    };

    wrap.addEventListener("pointerdown", onDown);
    wrap.addEventListener("pointermove", onMove);
    wrap.addEventListener("pointerup", onUp);
    wrap.addEventListener("pointercancel", onUp);
    wrap.addEventListener("wheel", onWheel, { passive: false });
    wrap.addEventListener("contextmenu", (e) => e.preventDefault());
    window.addEventListener("pointerup", onUp);
    window.addEventListener("keydown", onKey);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      wrap.removeEventListener("pointerdown", onDown);
      wrap.removeEventListener("pointermove", onMove);
      wrap.removeEventListener("pointerup", onUp);
      wrap.removeEventListener("pointercancel", onUp);
      wrap.removeEventListener("wheel", onWheel);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("keydown", onKey);
    };
  }, [onSelect]);

  const atMin = zoomPct <= Math.round(MIN_K * 100);
  const atMax = zoomPct >= Math.round(MAX_K * 100);

  return (
    <div
      ref={wrapRef}
      className="relative h-full min-h-0 w-full touch-none overflow-hidden"
      style={{ touchAction: "none", cursor: "grab" }}
    >
      <canvas ref={canvasRef} className="block h-full w-full touch-none" />
      <div className="pointer-events-none absolute inset-x-3 bottom-3 z-50 flex items-end justify-between gap-3 md:inset-x-4 md:bottom-4">
        <p className="hidden rounded-full border border-border bg-surface/80 px-3 py-1 font-mono text-xs text-muted backdrop-blur-sm sm:block">
          Tap a star to lock · drag to orbit it
        </p>
        <div className="pointer-events-auto ml-auto flex items-center gap-1 rounded-2xl border border-border bg-surface/90 p-1 shadow-lg backdrop-blur-sm">
          <ZoomBtn label="Zoom out" disabled={atMin} onClick={() => zoomBy(1 / 1.25)}>
            <Minus className="size-5" />
          </ZoomBtn>
          <span className="min-w-12 px-1 text-center font-mono text-xs tabular-nums text-muted">
            {zoomPct}%
          </span>
          <ZoomBtn label="Zoom in" disabled={atMax} onClick={() => zoomBy(1.25)}>
            <Plus className="size-5" />
          </ZoomBtn>
          <ZoomBtn label="Reset view" onClick={resetCam}>
            <LocateFixed className="size-5" />
          </ZoomBtn>
          {onToggleFocus && (
            <ZoomBtn
              label={focused ? "Exit fullscreen" : "Fullscreen star map"}
              onClick={onToggleFocus}
            >
              {focused ? <Minimize2 className="size-5" /> : <Maximize2 className="size-5" />}
            </ZoomBtn>
          )}
        </div>
      </div>
    </div>
  );
}

function ZoomBtn({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex size-11 items-center justify-center rounded-xl text-fg transition-colors duration-150 hover:bg-elevated disabled:opacity-30"
    >
      {children}
    </button>
  );
}

function rotatePoint(x0: number, y0: number, z0: number, yaw: number, pitch: number) {
  const cyaw = Math.cos(yaw);
  const syaw = Math.sin(yaw);
  const cp = Math.cos(pitch);
  const sp = Math.sin(pitch);
  const x1 = x0 * cyaw - z0 * syaw;
  const z1 = x0 * syaw + z0 * cyaw;
  const y2 = y0 * cp - z1 * sp;
  const z2 = y0 * sp + z1 * cp;
  return { x: x1, y: y2, z: z2 };
}

function draw(ctx: CanvasRenderingContext2D, s: Scene) {
  const { w, h, t, cam } = s;
  ctx.clearRect(0, 0, w, h);
  const bg = ctx.createRadialGradient(w * 0.5, h * 0.48, 8, w * 0.5, h * 0.5, Math.max(w, h) * 0.75);
  bg.addColorStop(0, "#122033");
  bg.addColorStop(0.22, "#0a121c");
  bg.addColorStop(0.6, "#05080e");
  bg.addColorStop(1, "#020308");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);
  drawStarfield(ctx, s);

  const R = Math.min(w, h) * 0.54;
  const focus =
    (s.selectedId ? s.sim.find((n) => n.id === s.selectedId) : undefined) ?? mainNode(s.sim);
  drawUniverse(ctx, s, focus?.sx ?? w / 2 + cam.x, focus?.sy ?? h / 2 + cam.y, R * cam.k);

  const q = s.query.trim().toLowerCase();
  const match = (n: SimNode) =>
    !q || n.title.toLowerCase().includes(q) || n.id.toLowerCase().includes(q);
  const lookup = new Map(s.sim.map((n) => [n.id, n]));

  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const e of s.edges) {
    const a = lookup.get(e.source);
    const b = lookup.get(e.target);
    if (!a || !b) continue;
    const hi = Boolean(s.selectedId && (e.source === s.selectedId || e.target === s.selectedId));
    drawRay(ctx, a, b, e.kind, hi, Boolean(q && (!match(a) || !match(b))), cam.k);
  }
  ctx.restore();

  const ordered = [...s.sim].sort((a, b) => b.wz - a.wz);
  for (const n of ordered) {
    drawStar(ctx, n, n.id === s.selectedId, n.id === s.hover, Boolean(q && !match(n)), cam.k, t);
  }

  for (const n of ordered) {
    if (n.depth < 0.72) continue;
    const faded = Boolean(q && !match(n));
    const sel = n.id === s.selectedId;
    const hov = n.id === s.hover;
    const show = n.kind !== "raw" && n.kind !== "page" ? true : sel || hov;
    if (!show || (faded && !sel && !hov)) continue;
    ctx.font = `${sel ? 600 : 450} 12px "Cormorant Garamond", "Newsreader", serif`;
    ctx.fillStyle = faded ? "rgba(140,170,200,0.28)" : `rgba(190,220,255,${0.4 + n.depth * 0.5})`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const label = n.title.length > 26 ? `${n.title.slice(0, 24)}…` : n.title;
    ctx.shadowColor = "rgba(140, 190, 255, 0.35)";
    ctx.shadowBlur = sel ? 12 : 6;
    ctx.fillText(label, n.sx, n.sy + Math.max(2, n.r * n.depth) + 6);
    ctx.shadowBlur = 0;
  }
}

function drawUniverse(
  ctx: CanvasRenderingContext2D,
  s: Scene,
  cx: number,
  cy: number,
  R: number,
) {
  const { cam, t } = s;
  const k = cam.k;
  const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.22);
  core.addColorStop(0, "rgba(180, 220, 255, 0.22)");
  core.addColorStop(0.4, "rgba(80, 140, 220, 0.07)");
  core.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(cx, cy, R * 0.22, 0, Math.PI * 2);
  ctx.fill();

  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (let i = 0; i < 3; i++) {
    const phase = (t * 0.12 + i / 3) % 1;
    ctx.beginPath();
    ctx.arc(cx, cy, R * (0.12 + phase * 0.95), 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(140, 190, 255, ${0.16 * (1 - phase)})`;
    ctx.lineWidth = (1.2 - phase) / Math.max(k, 0.5);
    ctx.stroke();
  }
  ctx.beginPath();
  const steps = 72;
  for (let i = 0; i <= steps; i++) {
    const lon = (i / steps) * Math.PI * 2;
    const r = R * 0.5;
    const p = rotatePoint(r * Math.cos(lon), 0, r * Math.sin(lon), cam.yaw, cam.pitch);
    const x = cx + p.x;
    const y = cy + p.y;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = "rgba(140, 190, 255, 0.12)";
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.restore();
}

function drawRay(
  ctx: CanvasRenderingContext2D,
  a: SimNode,
  b: SimNode,
  kind: GraphEdge["kind"],
  hi: boolean,
  faded: boolean,
  k: number,
) {
  const depth = (a.depth + b.depth) / 2;
  if (depth < 0.48 && !hi) return;
  ctx.beginPath();
  ctx.moveTo(a.sx, a.sy);
  ctx.quadraticCurveTo((a.sx + b.sx) / 2, (a.sy + b.sy) / 2 - 10 * depth, b.sx, b.sy);
  const alpha = faded
    ? 0.04
    : hi
      ? 0.45 * depth
      : kind === "source"
        ? 0.1 * depth
        : kind === "relates" || kind === "mesh"
          ? 0.22 * depth
          : 0.16 * depth;
  ctx.strokeStyle = `rgba(150, 200, 255, ${alpha})`;
  ctx.lineWidth = (hi ? 2 : 1) / Math.max(k, 0.6);
  ctx.shadowColor = hi ? "rgba(140, 200, 255, 0.7)" : "rgba(90, 150, 220, 0.2)";
  ctx.shadowBlur = hi ? 10 : 3;
  ctx.stroke();
  ctx.shadowBlur = 0;
}

function drawStar(
  ctx: CanvasRenderingContext2D,
  n: SimNode,
  sel: boolean,
  hov: boolean,
  faded: boolean,
  k: number,
  t: number,
) {
  const age = Math.max(0, t - n.born);
  const pop = 1 - Math.exp(-age * 2.4);
  const flash = Math.exp(-age * 2.1);
  const pulse = 1 + Math.sin(t * 2.2 + n.lon) * (sel ? 0.08 : 0.03);
  const pr = Math.max(0.55, n.r * n.depth * pulse * (0.2 + 0.8 * pop));
  const glowR = pr * (sel ? 3.2 : 2.0) + flash * 16;
  ctx.save();
  ctx.globalAlpha = faded ? 0.25 : (0.2 + n.depth * 0.75) * Math.min(1, 0.25 + pop);
  ctx.globalCompositeOperation = "lighter";
  if (!faded && n.depth > 0.45) {
    const halo = ctx.createRadialGradient(n.sx, n.sy, 0, n.sx, n.sy, glowR);
    halo.addColorStop(0, KIND_GLOW[n.kind]);
    halo.addColorStop(0.45, `rgba(120, 180, 255, ${0.08 + flash * 0.25})`);
    halo.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(n.sx, n.sy, glowR, 0, Math.PI * 2);
    ctx.fill();
  }
  if (flash > 0.05 && !faded) {
    ctx.beginPath();
    ctx.arc(n.sx, n.sy, 6 + (1 - flash) * 28, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(170, 210, 255, ${0.45 * flash})`;
    ctx.lineWidth = 1.4 / Math.max(k, 0.6);
    ctx.stroke();
  }
  if ((sel || hov) && n.depth > 0.55) {
    for (let i = 1; i <= 3; i++) {
      ctx.beginPath();
      ctx.arc(n.sx, n.sy, pr + (5 + i * 4) * n.depth, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(180, 220, 255, ${0.22 / i})`;
      ctx.lineWidth = 1 / Math.max(k, 0.6);
      ctx.stroke();
    }
  }
  ctx.beginPath();
  ctx.arc(n.sx, n.sy, pr, 0, Math.PI * 2);
  ctx.fillStyle = faded ? "rgba(90,110,140,0.25)" : KIND_CORE[n.kind];
  ctx.shadowColor = "rgba(180, 220, 255, 0.85)";
  ctx.shadowBlur = sel ? 14 : 7 + flash * 10;
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.restore();
}
