import { existsSync, readdirSync, readFileSync, realpathSync, statSync } from "node:fs";
import { basename, isAbsolute, join, normalize, relative, resolve } from "node:path";
import { BUNDLED_ATLASES } from "./bundled-data";
import { DEFAULT_ROOT, ROOT_PRESETS } from "./catalog";
import {
  aliasesFor,
  displayTitle,
  extractAtlasUris,
  extractMarkdownLinks,
  extractWikilinks,
  kindFor,
  normalizeLink,
  pageSlug,
  parseFrontmatter,
  relatesToOf,
  sourcesOf,
} from "./parse";
import type { GraphNode, GraphRef, StoreInfo, AtlasGraph, AtlasPage } from "./types";
import { countKinds, linkGraph, withDegrees } from "./link";

const SKIP_DIRS = new Set([
  "log",
  "evals",
  "node_modules",
  ".git",
  "staging",
  "templates",
  "mesh",
  ".atlas-index",
]);

export const STREAM_BATCH = 8;
const BUST_NAME = ".okf-wiki-listing-bust";

type Listing = { files: string[]; done: boolean };

const listings = new Map<string, Listing>();
const listingBustSeen = new Map<string, number>();

function bustMtime(root: string): number {
  try {
    const p = join(root, BUST_NAME);
    if (!existsSync(p)) return 0;
    return statSync(p).mtimeMs || 0;
  } catch {
    return 0;
  }
}

function honorListingBust(root: string): void {
  const m = bustMtime(root);
  if (!m) return;
  const seen = listingBustSeen.get(root) ?? 0;
  if (m > seen) {
    listings.delete(root);
    listingBustSeen.set(root, m);
  }
}

export function clearListing(root?: string): void {
  if (root) listings.delete(root);
  else listings.clear();
}

function walkMd(dir: string, acc: string[] = [], depth = 0): string[] {
  if (!existsSync(dir) || depth > 12) return acc;
  let entries: string[] = [];
  try {
    entries = readdirSync(dir);
  } catch {
    return acc;
  }
  for (const name of entries) {
    if (name.startsWith(".")) continue;
    const full = join(dir, name);
    let st;
    try {
      st = statSync(full);
    } catch {
      continue;
    }
    if (st.isDirectory()) {
      if (SKIP_DIRS.has(name)) continue;
      walkMd(full, acc, depth + 1);
    } else if (name.endsWith(".md")) {
      acc.push(full);
    }
  }
  return acc;
}

function bundledKeyFor(root: string): string | null {
  const n = root.replace(/\\/g, "/").replace(/\/$/, "");
  if (n.startsWith("bundled:")) return n.slice("bundled:".length);
  if (n.endsWith("/atlas/references/atlas") || n.endsWith("/atlases/skill-memory")) {
    return "skill-memory";
  }
  if (n.endsWith("/atlas/fixtures/mini-atlas") || n.endsWith("/atlases/mini")) {
    return "mini";
  }
  return null;
}

function bundledPages(root: string): Record<string, string> | null {
  const key = bundledKeyFor(root);
  if (!key) return null;
  return BUNDLED_ATLASES[key]?.pages ?? null;
}

function ensureListed(storeRoot: string): { files: string[]; complete: boolean } {
  const embedded = bundledPages(storeRoot);
  if (embedded && !existsSync(storeRoot)) {
    return { files: Object.keys(embedded).sort(), complete: true };
  }
  let L = listings.get(storeRoot);
  if (!L || !L.done) {
    const files = walkMd(storeRoot).sort();
    L = { files, done: true };
    listings.set(storeRoot, L);
  }
  return { files: L.files, complete: L.done };
}

function readText(path: string): string {
  return readFileSync(path, "utf8");
}

function readJson(path: string): Record<string, unknown> | null {
  try {
    return JSON.parse(readText(path)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function sanitizeRoot(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("bundled:")) return trimmed;
  return isAbsolute(trimmed) ? normalize(trimmed) : resolve(process.cwd(), trimmed);
}

function detectFormat(root: string): StoreInfo["format"] {
  const bundled = bundledKeyFor(root);
  if (bundled && BUNDLED_ATLASES[bundled]) return "atlas";
  if (existsSync(join(root, "SCHEMA.json"))) return "atlas";
  if (existsSync(join(root, "knowledge")) || existsSync(join(root, "SCHEMA.md"))) {
    return "okf-wiki";
  }
  if (existsSync(join(root, "index.md"))) return "atlas";
  return "unknown";
}

function tallyStore(root: string): {
  experiences: number;
  decisions: number;
  work: number;
  other: number;
  pages: number;
} {
  const files = ensureListed(root).files;
  let experiences = 0;
  let decisions = 0;
  let work = 0;
  let other = 0;
  for (const f of files) {
    const rel = (isAbsolute(f) ? relative(root, f) : f).replace(/\\/g, "/");
    if (/(^|\/)(experiences|raw)\//.test(rel)) experiences += 1;
    else if (/(^|\/)decisions\//.test(rel)) decisions += 1;
    else if (/(^|\/)(work|modules)\//.test(rel)) work += 1;
    else other += 1;
  }
  return { experiences, decisions, work, other, pages: files.length };
}

export function inspectRoot(rawRoot: string): StoreInfo {
  const root = sanitizeRoot(rawRoot);
  const label = ROOT_PRESETS.find((p) => sanitizeRoot(p.root) === root)?.label ?? root;
  const empty = (reason: string): StoreInfo => ({
    root,
    label: label || "No root",
    available: false,
    reason,
    format: "unknown",
    experiences: 0,
    decisions: 0,
    work: 0,
    other: 0,
    pages: 0,
  });
  if (!root) return empty("Set an Atlas root to open Cartograph.");
  const bKey = bundledKeyFor(root);
  const bundled = bKey ? BUNDLED_ATLASES[bKey] : undefined;
  const onDisk = existsSync(root);
  if (!onDisk && !bundled) return empty("Path does not exist.");
  if (onDisk) {
    let st;
    try {
      st = statSync(root);
    } catch {
      if (!bundled) return empty("Cannot read path.");
    }
    if (st && !st.isDirectory() && !bundled) return empty("Root must be a directory.");
  }
  const format = detectFormat(root);
  if (format === "unknown") {
    return empty("Not an Atlas (need SCHEMA.json or index.md) or okf-wiki store.");
  }
  let atlasId: string | undefined = bundled?.id;
  if (format === "atlas" && onDisk) {
    const schema = readJson(join(root, "SCHEMA.json"));
    if (schema && typeof schema.atlas_id === "string") atlasId = schema.atlas_id;
  }
  const counts = tallyStore(root);
  return {
    root,
    label,
    available: true,
    format,
    atlasId,
    ...counts,
  };
}

function realPath(p: string): string {
  try {
    return realpathSync(p);
  } catch {
    return resolve(p);
  }
}

function storeKey(info: StoreInfo): string {
  if (info.atlasId) return `${info.format}:${info.atlasId}`;
  return realPath(info.root);
}

function iterSkillDirs(): string[] {
  const roots = [
    "/root/.grok/server-skills",
    "/home/workdir/.grok/skills",
    resolve(process.cwd(), ".grok/skills"),
  ];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const root of roots) {
    if (!existsSync(root)) continue;
    let names: string[] = [];
    try {
      names = readdirSync(root);
    } catch {
      continue;
    }
    for (const name of names) {
      if (name.startsWith(".")) continue;
      const dir = join(root, name);
      if (!existsSync(join(dir, "SKILL.md"))) continue;
      const key = realPath(dir);
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(dir);
    }
  }
  return out;
}

function skillCandidates(skillDir: string): { role: string; root: string }[] {
  const found: { role: string; root: string }[] = [
    { role: "process memory", root: join(skillDir, "references", "atlas") },
  ];
  const fixtures = join(skillDir, "fixtures");
  if (existsSync(fixtures)) {
    try {
      for (const name of readdirSync(fixtures)) {
        found.push({ role: name, root: join(fixtures, name) });
      }
    } catch {
      /* ignore */
    }
  }
  const examples = join(skillDir, "examples");
  if (existsSync(examples)) {
    try {
      for (const name of readdirSync(examples)) {
        found.push({ role: name, root: join(examples, name) });
      }
    } catch {
      /* ignore */
    }
  }
  return found;
}

export function listSkillStores(): StoreInfo[] {
  const seen = new Set<string>();
  const out: StoreInfo[] = [];
  for (const skillDir of iterSkillDirs()) {
    const skill = basename(skillDir);
    for (const cand of skillCandidates(skillDir)) {
      if (!existsSync(cand.root)) continue;
      const info = inspectRoot(cand.root);
      if (!info.available || info.format !== "atlas") continue;
      const key = storeKey(info);
      if (seen.has(key)) continue;
      seen.add(key);
      const label =
        cand.role === "process memory" ? skill : `${skill} · ${cand.role}`;
      out.push({ ...info, skill, label });
    }
  }
  for (const preset of listPresets()) {
    if (!preset.available || preset.format !== "atlas") continue;
    const key = storeKey(preset);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(preset);
  }
  out.sort((a, b) => a.label.localeCompare(b.label));
  return out;
}

export function listPresets(): StoreInfo[] {
  return ROOT_PRESETS.map((p) => inspectRoot(p.root));
}

export function defaultRoot(): string {
  if (DEFAULT_ROOT) {
    const env = inspectRoot(DEFAULT_ROOT);
    if (env.available) return env.root;
  }
  const first = listPresets().find((s) => s.available);
  return first?.root ?? DEFAULT_ROOT ?? "";
}

function parseFiles(
  storeRoot: string,
  files: string[],
  format: StoreInfo["format"],
  atlasId?: string,
): GraphNode[] {
  const onDisk = existsSync(storeRoot);
  const embedded = onDisk ? null : bundledPages(storeRoot);
  const nodes: GraphNode[] = [];
  for (const file of files) {
    const rel = (
      isAbsolute(file) ? relative(storeRoot, file) : file
    ).replace(/\\/g, "/");
    let text = "";
    try {
      if (embedded) {
        text = embedded[rel] ?? "";
      } else {
        const full = isAbsolute(file) ? file : join(storeRoot, file);
        text = readText(full);
      }
    } catch {
      continue;
    }
    if (!text) continue;
    const { meta, body } = parseFrontmatter(text);
    const type = typeof meta.type === "string" && meta.type ? meta.type : "";
    const kind = kindFor(rel, type, format);
    const sources = sourcesOf(meta);
    const relates = relatesToOf(meta);
    const links = [
      ...extractWikilinks(body),
      ...extractMarkdownLinks(body),
    ].map(normalizeLink);
    const mesh = extractAtlasUris(`${body}\n${JSON.stringify(meta)}`);
    const refs: GraphRef[] = [
      ...sources.map((raw) => ({ raw, kind: "source" as const })),
      ...relates.map((r) => ({
        raw: r.path,
        kind: "relates" as const,
        relKind: r.kind,
      })),
      ...links
        .filter((raw) => !sources.includes(raw) && !relates.some((r) => normalizeLink(r.path) === raw))
        .map((raw) => ({ raw, kind: "link" as const })),
      ...mesh.map((m) => ({
        raw: m.path,
        kind: "mesh" as const,
        relKind: m.atlasId,
      })),
    ];
    nodes.push({
      id: pageSlug(rel),
      kind,
      title: displayTitle(meta, rel),
      type: type || kind,
      path: rel,
      degree: 0,
      sourceCount: sources.length,
      aliases: aliasesFor(rel),
      refs,
      atlasId,
    });
  }
  return nodes;
}

export function loadGraph(
  rawRoot: string,
  opts?: { offset?: number; limit?: number },
): AtlasGraph {
  const store = inspectRoot(rawRoot);
  honorListingBust(store.root);
  if ((opts?.offset ?? 0) === 0) clearListing(store.root);
  if (!store.available) {
    return {
      store,
      nodes: [],
      edges: [],
      nextOffset: null,
      scanned: 0,
      total: 0,
      complete: true,
    };
  }
  const offset = Math.max(0, opts?.offset ?? 0);
  const limit = Math.max(1, Math.min(80, opts?.limit ?? STREAM_BATCH));
  const { files, complete: listedAll } = ensureListed(store.root);
  const slice = files.slice(offset, offset + limit);
  const nodes = parseFiles(store.root, slice, store.format, store.atlasId);
  const edges = linkGraph(nodes);
  const next = offset + slice.length;
  const hasMore = next < files.length || !listedAll;
  return {
    store: { ...store, ...countKinds(nodes), pages: files.length },
    nodes: withDegrees(nodes, edges),
    edges,
    nextOffset: hasMore ? next : null,
    scanned: slice.length,
    total: listedAll ? files.length : Math.max(files.length, next + 1),
    complete: !hasMore,
  };
}

export function loadPage(rawRoot: string, nodeId: string): AtlasPage | null {
  const store = inspectRoot(rawRoot);
  if (!store.available) return null;
  const id = normalizeLink(nodeId);
  const stem = basename(id);
  const embedded = !existsSync(store.root) ? bundledPages(store.root) : null;
  if (embedded) {
    const hit =
      Object.keys(embedded).find((k) => pageSlug(k) === id || k === `${id}.md`) ??
      Object.keys(embedded).find((k) => basename(k).replace(/\.md$/, "") === stem);
    if (!hit) return null;
    const { meta, body } = parseFrontmatter(embedded[hit] ?? "");
    const type = typeof meta.type === "string" && meta.type ? meta.type : "";
    const kind = kindFor(hit, type, store.format);
    return {
      id: pageSlug(hit),
      path: hit,
      title: displayTitle(meta, hit),
      type: type || kind,
      kind,
      sources: sourcesOf(meta),
      relatesTo: relatesToOf(meta),
      body: body.trim(),
    };
  }
  const candidates = [
    join(store.root, id.endsWith(".md") ? id : `${id}.md`),
    join(store.root, "experiences", `${stem}.md`),
    join(store.root, "decisions", `${stem}.md`),
    join(store.root, "work", `${stem}.md`),
    join(store.root, "knowledge", `${stem}.md`),
    join(store.root, "raw", "experiences", `${stem}.md`),
    join(store.root, id),
  ];
  const file = candidates.find((p) => existsSync(p) && statSync(p).isFile());
  if (!file) return null;
  const rel = relative(store.root, file).replace(/\\/g, "/");
  const { meta, body } = parseFrontmatter(readText(file));
  const type = typeof meta.type === "string" && meta.type ? meta.type : "";
  const kind = kindFor(rel, type, store.format);
  return {
    id: pageSlug(rel),
    path: rel,
    title: displayTitle(meta, rel),
    type: type || kind,
    kind,
    sources: sourcesOf(meta),
    relatesTo: relatesToOf(meta),
    body: body.trim(),
  };
}
