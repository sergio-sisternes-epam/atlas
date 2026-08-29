import { countKinds, linkGraph, withDegrees } from "./link";
import type { AtlasGraph } from "./types";

export function mergeGraphs(base: AtlasGraph, extra: AtlasGraph): AtlasGraph {
  const byId = new Map(base.nodes.map((n) => [n.id, n]));
  for (const n of extra.nodes) byId.set(n.id, n);
  const nodes = [...byId.values()];
  const edges = linkGraph(nodes);
  return {
    store: { ...base.store, ...extra.store, ...countKinds(nodes) },
    nodes: withDegrees(nodes, edges),
    edges,
    nextOffset: extra.nextOffset,
    scanned: base.scanned + extra.scanned,
    total: Math.max(base.total, extra.total),
    complete: extra.complete,
  };
}
