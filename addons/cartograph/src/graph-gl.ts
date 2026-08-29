/** GPU path for the star map. Canvas2D remains the fallback in graph-canvas. */

type Kind = string;

const CORE: Record<string, [number, number, number]> = {
  experience: [0.83, 0.89, 1],
  decision: [0.56, 0.78, 0.75],
  work: [0.91, 0.95, 1],
  lesson: [0.72, 0.83, 0.78],
  recipe: [0.77, 0.83, 0.91],
  index: [0.94, 0.96, 0.98],
  page: [0.49, 0.56, 0.67],
  knowledge: [0.83, 0.89, 1],
  raw: [0.49, 0.56, 0.67],
  module: [0.56, 0.78, 0.75],
};

export type GlNode = {
  id: string;
  sx: number;
  sy: number;
  depth: number;
  r: number;
  kind: Kind;
  lon: number;
  born: number;
  title: string;
};

export type GlEdge = { source: string; target: string; kind: string };

export type GlFrame = {
  w: number;
  h: number;
  t: number;
  k: number;
  cx: number;
  cy: number;
  selectedId: string | null;
  hover: string | null;
  query: string;
  nodes: GlNode[];
  edges: GlEdge[];
  bg: Float32Array;
};

const VS_POINT = `
attribute vec2 a_pos;
attribute float a_size;
attribute vec4 a_col;
uniform vec2 u_res;
varying vec4 v_col;
void main() {
  vec2 clip = (a_pos / u_res) * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
  gl_PointSize = max(a_size, 1.0);
  v_col = a_col;
}`;

const FS_POINT = `
precision mediump float;
varying vec4 v_col;
void main() {
  vec2 p = gl_PointCoord * 2.0 - 1.0;
  float d = dot(p, p);
  if (d > 1.0) discard;
  float a = exp(-d * 2.6);
  gl_FragColor = vec4(v_col.rgb, v_col.a * a);
}`;

const VS_LINE = `
attribute vec2 a_pos;
attribute vec4 a_col;
uniform vec2 u_res;
varying vec4 v_col;
void main() {
  vec2 clip = (a_pos / u_res) * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
  v_col = a_col;
}`;

const FS_LINE = `
precision mediump float;
varying vec4 v_col;
void main() {
  gl_FragColor = v_col;
}`;

const VS_QUAD = `
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
  v_uv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

const FS_QUAD = `
precision mediump float;
varying vec2 v_uv;
void main() {
  vec2 d = v_uv - vec2(0.5, 0.48);
  float r = length(d);
  vec3 c = mix(vec3(0.07, 0.13, 0.20), vec3(0.02, 0.03, 0.05), smoothstep(0.0, 0.72, r));
  c = mix(vec3(0.07, 0.13, 0.20), c, 0.35);
  gl_FragColor = vec4(c, 1.0);
}`;

function compile(gl: WebGLRenderingContext, vs: string, fs: string): WebGLProgram | null {
  const sh = (type: number, src: string) => {
    const s = gl.createShader(type);
    if (!s) return null;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.warn(gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    }
    return s;
  };
  const v = sh(gl.VERTEX_SHADER, vs);
  const f = sh(gl.FRAGMENT_SHADER, fs);
  if (!v || !f) return null;
  const p = gl.createProgram();
  if (!p) return null;
  gl.attachShader(p, v);
  gl.attachShader(p, f);
  gl.bindAttribLocation(p, 0, "a_pos");
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    console.warn(gl.getProgramInfoLog(p));
    return null;
  }
  return p;
}

export class GraphGL {
  gl: WebGLRenderingContext;
  point: WebGLProgram;
  line: WebGLProgram;
  quad: WebGLProgram;
  buf: WebGLBuffer;
  quadBuf: WebGLBuffer;
  cssW = 1;
  cssH = 1;
  scratch = new Float32Array(7 * 8192);
  loc = {
    pointRes: null as WebGLUniformLocation | null,
    pointPos: 0,
    pointSize: 0,
    pointCol: 0,
    lineRes: null as WebGLUniformLocation | null,
    linePos: 0,
    lineCol: 0,
    quadPos: 0,
  };

  constructor(gl: WebGLRenderingContext, point: WebGLProgram, line: WebGLProgram, quad: WebGLProgram) {
    this.gl = gl;
    this.point = point;
    this.line = line;
    this.quad = quad;
    this.buf = gl.createBuffer()!;
    this.quadBuf = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    this.loc.pointRes = gl.getUniformLocation(point, "u_res");
    this.loc.pointPos = gl.getAttribLocation(point, "a_pos");
    this.loc.pointSize = gl.getAttribLocation(point, "a_size");
    this.loc.pointCol = gl.getAttribLocation(point, "a_col");
    this.loc.lineRes = gl.getUniformLocation(line, "u_res");
    this.loc.linePos = gl.getAttribLocation(line, "a_pos");
    this.loc.lineCol = gl.getAttribLocation(line, "a_col");
    this.loc.quadPos = gl.getAttribLocation(quad, "a_pos");
  }

  resize(cssW: number, cssH: number, dpr: number) {
    const gl = this.gl;
    const canvas = gl.canvas as HTMLCanvasElement;
    const bw = Math.max(1, Math.floor(cssW * dpr));
    const bh = Math.max(1, Math.floor(cssH * dpr));
    if (canvas.width !== bw || canvas.height !== bh) {
      canvas.width = bw;
      canvas.height = bh;
    }
    canvas.style.width = `${cssW}px`;
    canvas.style.height = `${cssH}px`;
    gl.viewport(0, 0, bw, bh);
    this.cssW = cssW;
    this.cssH = cssH;
  }

  draw(f: GlFrame) {
    const gl = this.gl;
    const { w, h } = f;
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.clearColor(0.02, 0.03, 0.05, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);

    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this.drawQuad();
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);

    if (f.bg.length) this.drawPoints(f.bg, 7, f.bg.length / 7);

    this.drawCore(f.cx, f.cy, Math.min(w, h) * 0.12 * f.k);

    const lookup = new Map(f.nodes.map((n) => [n.id, n]));
    const q = f.query.trim().toLowerCase();
    const match = (n: GlNode) =>
      !q || n.title.toLowerCase().includes(q) || n.id.toLowerCase().includes(q);
    const related = new Set<string>();
    if (f.selectedId) {
      related.add(f.selectedId);
      for (const e of f.edges) {
        if (e.source === f.selectedId) related.add(e.target);
        else if (e.target === f.selectedId) related.add(e.source);
      }
    }

    const lineCount = this.packEdges(f, lookup, q, match, related);
    if (lineCount) this.drawLines(this.scratch, lineCount);

    const pointCount = this.packNodes(f, q, match, related);
    if (pointCount) this.drawPoints(this.scratch, 7, pointCount);
  }

  private drawQuad() {
    const gl = this.gl;
    gl.useProgram(this.quad);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuf);
    gl.enableVertexAttribArray(this.loc.quadPos);
    gl.vertexAttribPointer(this.loc.quadPos, 2, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  private drawCore(cx: number, cy: number, r: number) {
    const out = this.scratch;
    out[0] = cx;
    out[1] = cy;
    out[2] = r * 2;
    out[3] = 0.7;
    out[4] = 0.86;
    out[5] = 1;
    out[6] = 0.22;
    this.drawPoints(out, 7, 1);
  }

  private packEdges(
    f: GlFrame,
    lookup: Map<string, GlNode>,
    q: string,
    match: (n: GlNode) => boolean,
    related: Set<string>,
  ): number {
    let i = 0;
    const out = this.ensure(f.edges.length * 2 * 6);
    const max = Math.min(f.edges.length, 5000);
    const locked = related.size > 0;
    for (let e = 0; e < max; e++) {
      const edge = f.edges[e]!;
      const a = lookup.get(edge.source);
      const b = lookup.get(edge.target);
      if (!a || !b) continue;
      const depth = (a.depth + b.depth) / 2;
      const hi = Boolean(f.selectedId && (edge.source === f.selectedId || edge.target === f.selectedId));
      if (depth < 0.48 && !hi) continue;
      const faded = Boolean(q && (!match(a) || !match(b))) || (locked && !hi);
      const alpha = faded
        ? 0.04
        : hi
          ? 0.85
          : edge.kind === "source"
            ? 0.1 * depth
            : edge.kind === "relates" || edge.kind === "mesh"
              ? 0.24 * depth
              : 0.16 * depth;
      const r = hi ? 0.82 : 0.59;
      const g = hi ? 0.92 : 0.78;
      const bcol = 1;
      out[i++] = a.sx;
      out[i++] = a.sy;
      out[i++] = r;
      out[i++] = g;
      out[i++] = bcol;
      out[i++] = alpha;
      out[i++] = b.sx;
      out[i++] = b.sy;
      out[i++] = r;
      out[i++] = g;
      out[i++] = bcol;
      out[i++] = alpha;
    }
    return i / 6;
  }

  private packNodes(
    f: GlFrame,
    q: string,
    match: (n: GlNode) => boolean,
    related: Set<string>,
  ): number {
    const ordered = f.nodes;
    const out = this.ensure(ordered.length * 7);
    const locked = related.size > 0;
    let i = 0;
    for (const n of ordered) {
      const sel = n.id === f.selectedId;
      const hov = n.id === f.hover;
      const near = related.has(n.id);
      const faded = Boolean(q && !match(n)) || (locked && !near);
      const age = Math.max(0, f.t - n.born);
      const pop = 1 - Math.exp(-age * 2.4);
      const pulse = 1 + Math.sin(f.t * 2.2 + n.lon) * (sel ? 0.08 : near ? 0.05 : 0.03);
      const pr = Math.max(1.2, n.r * n.depth * pulse * (0.2 + 0.8 * pop) * 2.2);
      const rgb = CORE[n.kind] ?? CORE.page;
      const a = faded ? 0.1 : (0.25 + n.depth * 0.75) * Math.min(1, 0.3 + pop);
      out[i++] = n.sx;
      out[i++] = n.sy;
      out[i++] = sel ? pr * 2.8 : near || hov ? pr * 2.2 : pr * 1.6;
      out[i++] = sel ? 0.96 : rgb![0];
      out[i++] = sel ? 0.98 : rgb![1];
      out[i++] = sel ? 1 : rgb![2];
      out[i++] = faded ? 0.1 : near || sel ? Math.min(1, a + 0.25) : a;
    }
    return i / 7;
  }

  private ensure(n: number): Float32Array {
    if (this.scratch.length < n) {
      this.scratch = new Float32Array(Math.max(n, this.scratch.length * 2));
    }
    return this.scratch;
  }

  private drawPoints(data: Float32Array, stride: number, count: number) {
    const gl = this.gl;
    gl.useProgram(this.point);
    gl.uniform2f(this.loc.pointRes, this.cssW, this.cssH);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    gl.bufferData(gl.ARRAY_BUFFER, data.subarray(0, count * stride), gl.DYNAMIC_DRAW);
    const b = stride * 4;
    gl.enableVertexAttribArray(this.loc.pointPos);
    gl.vertexAttribPointer(this.loc.pointPos, 2, gl.FLOAT, false, b, 0);
    gl.enableVertexAttribArray(this.loc.pointSize);
    gl.vertexAttribPointer(this.loc.pointSize, 1, gl.FLOAT, false, b, 8);
    gl.enableVertexAttribArray(this.loc.pointCol);
    gl.vertexAttribPointer(this.loc.pointCol, 4, gl.FLOAT, false, b, 12);
    gl.drawArrays(gl.POINTS, 0, count);
  }

  private drawLines(data: Float32Array, count: number) {
    const gl = this.gl;
    gl.useProgram(this.line);
    gl.uniform2f(this.loc.lineRes, this.cssW, this.cssH);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    gl.bufferData(gl.ARRAY_BUFFER, data.subarray(0, count * 6), gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(this.loc.linePos);
    gl.vertexAttribPointer(this.loc.linePos, 2, gl.FLOAT, false, 24, 0);
    gl.enableVertexAttribArray(this.loc.lineCol);
    gl.vertexAttribPointer(this.loc.lineCol, 4, gl.FLOAT, false, 24, 8);
    gl.drawArrays(gl.LINES, 0, count);
  }
}

export function createGraphGL(canvas: HTMLCanvasElement): GraphGL | null {
  const gl =
    canvas.getContext("webgl", {
      alpha: false,
      antialias: true,
      powerPreference: "high-performance",
      premultipliedAlpha: false,
    }) ||
    canvas.getContext("experimental-webgl", {
      alpha: false,
      antialias: true,
    });
  if (!gl || !(gl instanceof WebGLRenderingContext)) return null;
  const point = compile(gl, VS_POINT, FS_POINT);
  const line = compile(gl, VS_LINE, FS_LINE);
  const quad = compile(gl, VS_QUAD, FS_QUAD);
  if (!point || !line || !quad) return null;
  return new GraphGL(gl, point, line, quad);
}

export function packBgStars(
  stars: { lon: number; lat: number; mag: number; tw: number }[],
  w: number,
  h: number,
  yaw: number,
  pitch: number,
  t: number,
  camx: number,
  camy: number,
  into: Float32Array,
): number {
  const cx = w / 2 + camx * 0.08;
  const cy = h / 2 + camy * 0.08;
  const far = Math.max(w, h) * 0.72;
  const cyaw = Math.cos(yaw * 0.35);
  const syaw = Math.sin(yaw * 0.35);
  const cp = Math.cos(pitch * 0.35);
  const sp = Math.sin(pitch * 0.35);
  let i = 0;
  for (const star of stars) {
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
    into[i++] = cx + x1 * 0.55;
    into[i++] = cy + y2 * 0.55;
    into[i++] = 1.2 + star.mag * 2.2;
    into[i++] = 0.75;
    into[i++] = 0.86;
    into[i++] = 1;
    into[i++] = (0.18 + star.mag * 0.55) * twinkle;
  }
  return i;
}
