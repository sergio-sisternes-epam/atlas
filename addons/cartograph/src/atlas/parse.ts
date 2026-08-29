import type { NodeKind } from "./types";

export type RelatesTo = { path: string; kind: string };

export type ParsedPage = {
  meta: Record<string, string | string[] | RelatesTo[]>;
  body: string;
};

const WIKILINK_RE = /\[\[([^\]]+)\]\]/g;
const MD_LINK_RE = /\[([^\]]+)\]\(([^)]+)\)/g;
const ATLAS_URI_RE = /atlas:\/\/([A-Za-z0-9._-]+)\/([^\s)\]"'<>]+)/g;

export function parseFrontmatter(text: string): ParsedPage {
  if (!text.startsWith("---")) return { meta: {}, body: text };
  const end = text.indexOf("\n---", 3);
  if (end === -1) return { meta: {}, body: text };
  const block = text.slice(3, end).trim();
  const body = text.slice(end + 4);
  const meta: Record<string, string | string[] | RelatesTo[]> = {};
  let listKey: string | null = null;
  let objectList: RelatesTo[] | null = null;
  let currentObj: RelatesTo | null = null;

  const flushObj = () => {
    if (currentObj && objectList && currentObj.path) objectList.push(currentObj);
    currentObj = null;
  };

  for (const line of block.split("\n")) {
    const objField = line.match(/^\s{2,}([A-Za-z0-9_-]+):\s*(.*)$/);
    const listObj = line.match(/^\s+-\s+([A-Za-z0-9_-]+):\s*(.*)$/);
    const listScalar = line.match(/^\s+-\s+(.*)$/);

    if (listObj && listKey) {
      flushObj();
      if (!objectList) {
        objectList = [];
        meta[listKey] = objectList;
      }
      currentObj = { path: "", kind: "related" };
      const k = listObj[1] ?? "";
      const v = stripQuotes(listObj[2] ?? "");
      if (k === "path") currentObj.path = v;
      else if (k === "kind") currentObj.kind = v;
      continue;
    }

    if (objField && currentObj && listKey) {
      const k = objField[1] ?? "";
      const v = stripQuotes(objField[2] ?? "");
      if (k === "path") currentObj.path = v;
      else if (k === "kind") currentObj.kind = v;
      continue;
    }

    if (listScalar && listKey && !objectList) {
      const cur = meta[listKey];
      const item = stripQuotes(listScalar[1] ?? "");
      if (Array.isArray(cur) && cur.length && typeof cur[0] === "string") {
        (cur as string[]).push(item);
      } else {
        meta[listKey] = [item];
      }
      continue;
    }

    const m = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!m) continue;
    flushObj();
    objectList = null;
    const key = m[1] ?? "";
    const val = (m[2] ?? "").trim();
    if (val === "" || val === "[]") {
      meta[key] = [];
      listKey = key;
    } else {
      meta[key] = stripQuotes(val);
      listKey = null;
    }
  }
  flushObj();
  return { meta, body };
}

function stripQuotes(s: string): string {
  return s.replace(/^["']|["']$/g, "").trim();
}

export function extractWikilinks(text: string): string[] {
  const out: string[] = [];
  WIKILINK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = WIKILINK_RE.exec(text))) {
    const raw = (m[1] ?? "").split("|")[0]?.trim() ?? "";
    if (raw) out.push(raw);
  }
  return out;
}

export function extractMarkdownLinks(text: string): string[] {
  const out: string[] = [];
  MD_LINK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = MD_LINK_RE.exec(text))) {
    const href = (m[2] ?? "").trim();
    if (!href || href.startsWith("http") || href.startsWith("#") || href.startsWith("mailto:")) {
      continue;
    }
    if (href.startsWith("atlas://")) continue;
    out.push(href);
  }
  return out;
}

export function extractAtlasUris(text: string): { atlasId: string; path: string }[] {
  const out: { atlasId: string; path: string }[] = [];
  ATLAS_URI_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = ATLAS_URI_RE.exec(text))) {
    out.push({ atlasId: m[1] ?? "", path: (m[2] ?? "").replace(/\.md$/i, "") });
  }
  return out;
}

export function relatesToOf(meta: ParsedPage["meta"]): RelatesTo[] {
  const raw = meta.relates_to;
  if (!Array.isArray(raw)) return [];
  const out: RelatesTo[] = [];
  for (const item of raw) {
    if (item && typeof item === "object" && "path" in item && typeof item.path === "string") {
      out.push({ path: item.path, kind: typeof item.kind === "string" ? item.kind : "related" });
    } else if (typeof item === "string" && item) {
      out.push({ path: item, kind: "related" });
    }
  }
  return out;
}

export function sourcesOf(meta: ParsedPage["meta"]): string[] {
  const raw = meta.sources;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((s) => {
      if (typeof s === "string") return s;
      if (s && typeof s === "object" && "path" in s) return String((s as RelatesTo).path);
      return "";
    })
    .filter(Boolean)
    .map(normalizeLink);
}

export function normalizeLink(raw: string): string {
  return raw
    .replace(/\\/g, "/")
    .replace(/^\.\//, "")
    .replace(/\.md$/i, "")
    .replace(/^\/+/, "")
    .trim();
}

export function pageSlug(relPath: string): string {
  return normalizeLink(relPath);
}

export function aliasesFor(relPath: string): string[] {
  const slug = pageSlug(relPath);
  const stem = slug.split("/").pop() ?? slug;
  const set = new Set<string>([slug, stem, `${slug}.md`]);
  const prefixes = [
    "knowledge/",
    "raw/experiences/",
    "raw/articles/",
    "raw/",
    "modules/",
    "experiences/",
    "decisions/",
    "work/",
    "lessons/",
    "recipes/",
  ];
  for (const prefix of prefixes) {
    if (slug.startsWith(prefix)) set.add(slug.slice(prefix.length));
  }
  if (slug.endsWith("/index")) set.add(slug.replace(/\/index$/, ""));
  return [...set];
}

const KIND_SET = new Set<NodeKind>([
  "experience",
  "decision",
  "work",
  "lesson",
  "recipe",
  "index",
  "page",
  "knowledge",
  "raw",
  "module",
]);

export function kindFor(
  relPath: string,
  typeField: string | undefined,
  format: "atlas" | "okf-wiki" | "unknown",
): NodeKind {
  const typed = (typeField ?? "").trim().toLowerCase();
  if (typed && KIND_SET.has(typed as NodeKind)) return typed as NodeKind;
  const p = relPath.replace(/\\/g, "/");
  if (p === "index.md" || p === "index" || p.endsWith("/index.md") || p.endsWith("/index")) {
    return "index";
  }
  if (p.startsWith("experiences/")) return "experience";
  if (p.startsWith("decisions/")) return "decision";
  if (p.startsWith("work/")) return "work";
  if (p.startsWith("lessons/")) return "lesson";
  if (p.startsWith("recipes/")) return "recipe";
  if (p.startsWith("knowledge/")) return "knowledge";
  if (p.startsWith("raw/")) return "raw";
  if (p.startsWith("modules/")) return "module";
  return format === "okf-wiki" ? "knowledge" : "page";
}

export function displayTitle(
  meta: ParsedPage["meta"],
  relPath: string,
): string {
  const t = meta.title;
  if (typeof t === "string" && t.trim()) return t.trim();
  const stem = pageSlug(relPath).split("/").pop() ?? relPath;
  return stem.replace(/-/g, " ");
}
