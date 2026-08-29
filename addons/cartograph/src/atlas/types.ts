export type NodeKind =
  | "experience"
  | "decision"
  | "work"
  | "lesson"
  | "recipe"
  | "index"
  | "page"
  | "knowledge"
  | "raw"
  | "module";

export type EdgeKind = "link" | "relates" | "source" | "mesh";

export type GraphRef = {
  raw: string;
  kind: EdgeKind;
  relKind?: string;
};

export type GraphNode = {
  id: string;
  kind: NodeKind;
  title: string;
  type: string;
  path: string;
  degree: number;
  sourceCount: number;
  aliases: string[];
  refs: GraphRef[];
  atlasId?: string;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  relKind?: string;
};

export type StoreInfo = {
  root: string;
  label: string;
  available: boolean;
  reason?: string;
  format: "atlas" | "okf-wiki" | "unknown";
  atlasId?: string;
  experiences: number;
  decisions: number;
  work: number;
  other: number;
  pages?: number;
  skill?: string;
};

export type AtlasGraph = {
  store: StoreInfo;
  nodes: GraphNode[];
  edges: GraphEdge[];
  nextOffset: number | null;
  scanned: number;
  total: number;
  complete: boolean;
};

export type AtlasPage = {
  id: string;
  path: string;
  title: string;
  type: string;
  kind: NodeKind;
  sources: string[];
  relatesTo: { path: string; kind: string }[];
  body: string;
};

export type RootPreset = {
  label: string;
  root: string;
};
