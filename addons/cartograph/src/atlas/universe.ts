import type { GraphEdge, GraphNode, NodeKind } from "./types";

export type UniverseNode = GraphNode & {
  mass: number;
  galaxy: string;
  lon: number;
  lat: number;
  targetShell: number;
};

const KIND_MASS: Record<NodeKind, number> = {
  index: 1,
  work: 0.92,
  module: 0.88,
  decision: 0.78,
  recipe: 0.7,
  lesson: 0.65,
  knowledge: 0.62,
  experience: 0.55,
  page: 0.4,
  raw: 0.18,
};

function hash01(s: string, salt = 0): number {
  let h = 2166136261 ^ salt;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

function kindBoost(n: GraphNode): number {
  return KIND_MASS[n.kind] ?? 0.4;
}

export function massOf(n: GraphNode, maxDegree: number, maxSources: number): number {
  const d = Math.log1p(n.degree) / Math.log1p(Math.max(maxDegree, 1));
  const s = Math.log1p(n.sourceCount) / Math.log1p(Math.max(maxSources, 1));
  return Math.min(1, kindBoost(n) * 0.38 + d * 0.47 + s * 0.15);
}

export function assignGalaxies(nodes: GraphNode[], edges: GraphEdge[]): Map<string, string> {
  const galaxy = new Map<string, string>();
  const adj = new Map<string, string[]>();
  const add = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, []);
    adj.get(a)!.push(b);
  };
  for (const e of edges) {
    add(e.source, e.target);
    add(e.target, e.source);
  }

  const seeds = nodes.filter(
    (n) => n.kind === "work" || n.kind === "index" || n.kind === "module" || n.kind === "decision",
  );
  const queue: string[] = [];
  for (const s of seeds) {
    galaxy.set(s.id, s.id);
    queue.push(s.id);
  }
  while (queue.length) {
    const id = queue.shift()!;
    const g = galaxy.get(id)!;
    for (const nb of adj.get(id) ?? []) {
      if (galaxy.has(nb)) continue;
      galaxy.set(nb, g);
      queue.push(nb);
    }
  }

  for (const n of nodes) {
    if (galaxy.has(n.id)) continue;
    galaxy.set(n.id, `cloud-${Math.floor(hash01(n.id, 7) * 8)}`);
  }
  return galaxy;
}

function dirFromHash(key: string, salt: number): { x: number; y: number; z: number } {
  const u = hash01(key, salt);
  const v = hash01(key, salt + 1);
  const lat = Math.acos(Math.max(-1, Math.min(1, 2 * u - 1)));
  const lon = v * Math.PI * 2;
  return {
    x: Math.sin(lat) * Math.cos(lon),
    y: Math.cos(lat),
    z: Math.sin(lat) * Math.sin(lon),
  };
}

function norm(x: number, y: number, z: number) {
  const l = Math.hypot(x, y, z) || 1;
  return { x: x / l, y: y / l, z: z / l };
}

export function layoutUniverse(nodes: GraphNode[], edges: GraphEdge[]): UniverseNode[] {
  const maxDegree = nodes.reduce((m, n) => Math.max(m, n.degree), 1);
  const maxSources = nodes.reduce((m, n) => Math.max(m, n.sourceCount), 1);
  const galaxies = assignGalaxies(nodes, edges);

  return nodes.map((n) => {
    const mass = massOf(n, maxDegree, maxSources);
    const gid = galaxies.get(n.id) ?? n.id;
    const own = dirFromHash(n.id, 21);
    const cloud = dirFromHash(gid, 3);
    const pull = n.kind === "raw" || n.kind === "page" ? 0.18 : 0.42;
    const mixed = norm(
      own.x * (1 - pull) + cloud.x * pull,
      own.y * (1 - pull) + cloud.y * pull,
      own.z * (1 - pull) + cloud.z * pull,
    );
    const lon = Math.atan2(mixed.z, mixed.x);
    const lat = Math.acos(Math.max(-1, Math.min(1, mixed.y)));
    const shell = 0.22 + (1 - mass) * 0.68 + hash01(n.id, 5) * 0.12;

    return {
      ...n,
      mass,
      galaxy: gid,
      lon: (lon + Math.PI * 2) % (Math.PI * 2),
      lat,
      targetShell: Math.min(1.08, shell),
    };
  });
}
