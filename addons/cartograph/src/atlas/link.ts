import { normalizeLink } from "./parse";
import type { GraphEdge, GraphNode, StoreInfo } from "./types";

export function linkGraph(nodes: GraphNode[]): GraphEdge[] {
  const aliasToId = new Map<string, string>();
  for (const n of nodes) {
    for (const a of n.aliases) {
      if (!aliasToId.has(a)) aliasToId.set(a, n.id);
    }
  }
  const resolveRef = (ref: string) => {
    const n = normalizeLink(ref);
    if (!n) return null;
    return (
      aliasToId.get(n) ??
      aliasToId.get(n.replace(/^\.\.\//, "")) ??
      aliasToId.get(n.split("/").pop() ?? "") ??
      null
    );
  };
  const edges: GraphEdge[] = [];
  const seen = new Set<string>();
  for (const n of nodes) {
    for (const ref of n.refs) {
      const tid = resolveRef(ref.raw);
      if (!tid || tid === n.id) continue;
      const key = `${ref.kind}:${n.id}->${tid}:${ref.relKind ?? ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      edges.push({
        id: key,
        source: n.id,
        target: tid,
        kind: ref.kind,
        relKind: ref.relKind,
      });
    }
  }
  return edges;
}

export function withDegrees(nodes: GraphNode[], edges: GraphEdge[]): GraphNode[] {
  const degree = new Map<string, number>();
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }
  return nodes.map((n) => ({ ...n, degree: degree.get(n.id) ?? 0 }));
}

export function countKinds(nodes: GraphNode[]): Pick<
  StoreInfo,
  "experiences" | "decisions" | "work" | "other"
> {
  const kinds = { experiences: 0, decisions: 0, work: 0, other: 0 };
  for (const n of nodes) {
    if (n.kind === "experience" || n.kind === "raw") kinds.experiences += 1;
    else if (n.kind === "decision") kinds.decisions += 1;
    else if (n.kind === "work" || n.kind === "module") kinds.work += 1;
    else kinds.other += 1;
  }
  return kinds;
}
