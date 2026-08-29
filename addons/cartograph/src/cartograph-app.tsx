import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Circle,
  FolderOpen,
  GitBranch,
  Layers,
  Link2,
  Loader2,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { getBootstrap, getGraph, getPage } from "./atlas/api";
import { mergeGraphs } from "./atlas/merge";
import { normalizeLink } from "./atlas/parse";
import type { AtlasGraph, AtlasPage, GraphEdge, GraphNode, StoreInfo } from "./atlas/types";
import { GraphCanvas } from "./graph-canvas";
import { MarkdownView } from "./markdown-view";
import { OpeningCrawl } from "./opening-crawl";
import { WelcomeGate } from "./welcome-gate";
import { HyperspaceJump } from "./hyperspace-jump";
import { cn } from "./cn";

type Layers = {
  experiences: boolean;
  decisions: boolean;
  work: boolean;
  indexes: boolean;
  other: boolean;
  relations: boolean;
  sources: boolean;
};

const DEFAULT_LAYERS: Layers = {
  experiences: true,
  decisions: true,
  work: true,
  indexes: true,
  other: true,
  relations: true,
  sources: true,
};

export type CartographAppProps = {
  initialRoot?: string;
  onRootChange?: (root: string) => void;
  skipIntro?: boolean;
};

function layerFor(kind: GraphNode["kind"]): keyof Layers {
  if (kind === "experience" || kind === "raw") return "experiences";
  if (kind === "decision") return "decisions";
  if (kind === "work" || kind === "module") return "work";
  if (kind === "index") return "indexes";
  return "other";
}

export function CartographApp({ initialRoot, onRootChange, skipIntro }: CartographAppProps) {
  const [phase, setPhase] = useState<"crawl" | "welcome" | "jump" | "map">(() => {
    if (initialRoot) return "map";
    if (skipIntro) return "welcome";
    try {
      if (sessionStorage.getItem("cartograph-intro") === "done") return "welcome";
    } catch {
      /* ignore */
    }
    return "crawl";
  });
  const [presets, setPresets] = useState<StoreInfo[]>([]);
  const [draftRoot, setDraftRoot] = useState(initialRoot ?? "");
  const [root, setRoot] = useState(initialRoot ?? "");
  const [graph, setGraph] = useState<AtlasGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [page, setPage] = useState<AtlasPage | null>(null);
  const [pageLoading, setPageLoading] = useState(false);
  const [hydrating, setHydrating] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const appRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    getBootstrap()
      .then((boot) => {
        if (cancelled) return;
        setPresets(boot.presets);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (initialRoot && initialRoot !== root) {
      setDraftRoot(initialRoot);
      setRoot(initialRoot);
    }
  }, [initialRoot]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyRoot = useCallback(
    (next: string) => {
      const trimmed = next.trim();
      setDraftRoot(trimmed);
      setRoot(trimmed);
      setPhase("jump");
      onRootChange?.(trimmed);
    },
    [onRootChange],
  );

  useEffect(() => {
    if (!root) {
      setHydrating(false);
      setGraph(null);
      return;
    }
    let cancelled = false;
    setHydrating(true);
    setError(null);
    setSelectedId(null);
    setPage(null);

    (async () => {
      try {
        let offset = 0;
        let acc: AtlasGraph | null = null;
        let first = true;
        let steps = 0;
        while (!cancelled && steps++ < 40) {
          const batch = await getGraph({
            data: { root, offset, limit: first ? 24 : 40 },
          });
          if (cancelled) return;
          if (!batch.store.available) {
            setGraph(batch);
            setError(batch.store.reason ?? "Store is not available.");
            setHydrating(false);
            return;
          }
          acc = acc ? mergeGraphs(acc, batch) : batch;
          setGraph(acc);
          if (first) setHydrating(false);
          first = false;
          const next = batch.nextOffset;
          if (next == null || next <= offset) break;
          offset = next;
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load Atlas");
          setHydrating(false);
        }
      } finally {
        if (!cancelled) setHydrating(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [root]);

  useEffect(() => {
    if (!selectedId || !root) {
      setPage(null);
      return;
    }
    let cancelled = false;
    setPageLoading(true);
    getPage({ data: { root, nodeId: selectedId } })
      .then((p) => {
        if (!cancelled) setPage(p);
      })
      .catch(() => {
        if (!cancelled) setPage(null);
      })
      .finally(() => {
        if (!cancelled) setPageLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [root, selectedId]);

  const visible = useMemo(() => {
    if (!graph) return { nodes: [] as GraphNode[], edges: [] as GraphEdge[] };
    const nodes = graph.nodes.filter((n) => layers[layerFor(n.kind)]);
    const ids = new Set(nodes.map((n) => n.id));
    const edges = graph.edges.filter((e) => {
      if (!ids.has(e.source) || !ids.has(e.target)) return false;
      if (e.kind === "source" && !layers.sources) return false;
      if ((e.kind === "relates" || e.kind === "mesh") && !layers.relations) return false;
      return true;
    });
    return { nodes, edges };
  }, [graph, layers]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return visible.nodes
      .filter(
        (n) =>
          n.title.toLowerCase().includes(q) || n.id.toLowerCase().includes(q),
      )
      .slice(0, 8);
  }, [visible.nodes, query]);

  const onSelect = useCallback((id: string | null) => {
    setSelectedId(id);
    if (id) setPreviewOpen(true);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "," && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setPanelOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const pickSearch = (id: string) => {
    setSelectedId(id);
    setPreviewOpen(true);
    setQuery("");
  };

  const openWikiLink = useCallback(
    (target: string) => {
      const key = normalizeLink(target);
      if (!key) return;
      const hit = graph?.nodes.find(
        (n) =>
          n.aliases.some((a) => normalizeLink(a) === key) ||
          n.id === key ||
          n.id.endsWith(`/${key}`) ||
          n.path === key ||
          n.path === `${key}.md` ||
          n.title.toLowerCase() === key.toLowerCase(),
      );
      setSelectedId(hit?.id ?? key);
      setPreviewOpen(true);
    },
    [graph],
  );

  const selectedNode = graph?.nodes.find((n) => n.id === selectedId);
  const store = graph?.store;

  if (phase === "crawl") {
    return <OpeningCrawl onDone={() => setPhase("welcome")} />;
  }

  if (phase === "welcome") {
    return <WelcomeGate stores={presets} error={error} onOpen={applyRoot} />;
  }

  if (phase === "jump") {
    return <HyperspaceJump onDone={() => setPhase("map")} />;
  }

  return (
    <div ref={appRef} className="relative h-dvh min-h-0 overflow-hidden bg-bg text-fg">
      <main className="absolute inset-0">
        {error && (
          <div className="absolute inset-x-4 top-20 z-10 rounded-xl border border-border bg-elevated px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}
        <GraphCanvas
          nodes={visible.nodes}
          edges={visible.edges}
          selectedId={selectedId}
          query={query}
          onSelect={onSelect}
        />
      </main>

      <div className="pointer-events-none absolute inset-x-0 top-0 z-[60] flex items-start justify-center gap-2 px-3 pt-3">
        <button
          type="button"
          aria-label={panelOpen ? "Hide options" : "Show options"}
          aria-expanded={panelOpen}
          onClick={() => setPanelOpen((v) => !v)}
          className="pointer-events-auto inline-flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-surface/80 text-fg shadow-lg backdrop-blur-md"
        >
          <SlidersHorizontal className="size-5" />
        </button>
        <SearchBar
          query={query}
          onQuery={setQuery}
          matches={matches}
          onPick={pickSearch}
          className="pointer-events-auto w-full max-w-md"
        />
      </div>

      <p className="pointer-events-none absolute top-3.5 left-[3.6rem] z-40 hidden font-mono text-[10px] tracking-[0.22em] text-subtle uppercase lg:block">
        Cartograph
      </p>

      {panelOpen && (
        <aside className="absolute top-16 inset-x-3 z-50 max-h-[min(70vh,32rem)] overflow-y-auto rounded-2xl border border-border bg-surface/85 p-4 shadow-2xl backdrop-blur-md">
          <p className="font-mono text-xs tracking-[0.18em] text-subtle uppercase">Options</p>
          <div className="mt-3 grid gap-4 md:grid-cols-[minmax(0,1.6fr)_minmax(12rem,0.8fr)]">
            <div>
              <form
                className="flex flex-col gap-2 sm:flex-row sm:items-center"
                onSubmit={(e) => {
                  e.preventDefault();
                  applyRoot(draftRoot);
                }}
              >
                <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-border bg-bg/50 px-3 py-2">
                  <FolderOpen className="size-4 shrink-0 text-muted" />
                  <input
                    className="min-w-0 flex-1 bg-transparent font-mono text-xs text-fg outline-none placeholder:text-subtle"
                    placeholder="Atlas root"
                    value={draftRoot}
                    onChange={(e) => setDraftRoot(e.target.value)}
                    aria-label="Atlas store root"
                    spellCheck={false}
                  />
                </label>
                <button
                  type="submit"
                  className="min-h-11 shrink-0 rounded-xl bg-accent px-4 text-sm font-medium text-accent-fg"
                >
                  Open
                </button>
              </form>
              {presets.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setPhase("welcome")}
                    className="rounded-full border border-border px-3 py-1 text-xs text-muted"
                  >
                    All atlases
                  </button>
                  {presets.map((p) => (
                    <button
                      key={p.root}
                      type="button"
                      disabled={!p.available}
                      onClick={() => applyRoot(p.root)}
                      className={cn(
                        "rounded-full border px-3 py-1 text-xs",
                        root === p.root
                          ? "border-border-strong bg-elevated text-fg"
                          : "border-border text-muted",
                        !p.available && "opacity-40",
                      )}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              )}
              <p className="mt-4 font-mono text-xs text-subtle uppercase">Layers</p>
              <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                <LayerToggle
                  active={layers.experiences}
                  onClick={() => setLayers((l) => ({ ...l, experiences: !l.experiences }))}
                  icon={<Circle className="size-3.5" />}
                  label="Experiences"
                  swatch="bg-experience"
                />
                <LayerToggle
                  active={layers.decisions}
                  onClick={() => setLayers((l) => ({ ...l, decisions: !l.decisions }))}
                  icon={<BookOpen className="size-3.5" />}
                  label="Decisions"
                  swatch="bg-decision"
                />
                <LayerToggle
                  active={layers.work}
                  onClick={() => setLayers((l) => ({ ...l, work: !l.work }))}
                  icon={<Layers className="size-3.5" />}
                  label="Work"
                  swatch="bg-work"
                />
                <LayerToggle
                  active={layers.indexes}
                  onClick={() => setLayers((l) => ({ ...l, indexes: !l.indexes }))}
                  icon={<FolderOpen className="size-3.5" />}
                  label="Indexes"
                  swatch="bg-index"
                />
                <LayerToggle
                  active={layers.relations}
                  onClick={() => setLayers((l) => ({ ...l, relations: !l.relations }))}
                  icon={<GitBranch className="size-3.5" />}
                  label="Relates"
                  swatch="bg-relates"
                />
                <LayerToggle
                  active={layers.sources}
                  onClick={() => setLayers((l) => ({ ...l, sources: !l.sources }))}
                  icon={<Link2 className="size-3.5" />}
                  label="Provenance"
                  swatch="bg-source"
                />
              </div>
            </div>
            <dl className="grid gap-1 border-t border-border pt-3 font-mono text-xs text-muted md:border-t-0 md:border-l md:pt-0 md:pl-4">
              <div className="flex justify-between gap-3">
                <dt>Nodes</dt>
                <dd className="tabular-nums text-fg">{visible.nodes.length}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Edges</dt>
                <dd className="tabular-nums text-fg">{visible.edges.length}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Format</dt>
                <dd className="text-fg">{store?.format ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Loaded</dt>
                <dd className="tabular-nums text-fg">
                  {graph?.scanned ?? 0}
                  {graph?.total ? ` / ${graph.total}` : ""}
                </dd>
              </div>
              <div className="mt-1 break-all text-subtle">
                {store?.available
                  ? store.atlasId
                    ? `${store.atlasId}`
                    : store.root
                  : "Set an Atlas root to open Cartograph."}
              </div>
              {hydrating && (
                <div className="mt-2 flex items-center gap-2 text-subtle">
                  <Loader2 className="size-3 animate-spin" />
                  Streaming pages
                </div>
              )}
            </dl>
          </div>
        </aside>
      )}

      {previewOpen && selectedId && (
        <div className="absolute inset-x-0 top-0 bottom-16 z-40 flex items-center justify-center px-3 pt-3">
          <button
            type="button"
            aria-label="Dismiss preview backdrop"
            className="absolute inset-0 cursor-default"
            onClick={() => setPreviewOpen(false)}
          />
          <div className="relative z-10 flex h-full max-h-[min(80vh,calc(100%-0.5rem))] w-full max-w-[min(80%,48rem)] min-h-0 overflow-hidden rounded-2xl border border-border bg-surface/70 shadow-2xl backdrop-blur-md md:max-w-[80%]">
            <PagePreview
              selectedNode={selectedNode}
              page={page}
              pageLoading={pageLoading}
              onWikiLink={openWikiLink}
              onClose={() => setPreviewOpen(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function SearchBar({
  query,
  onQuery,
  matches,
  onPick,
  className,
}: {
  query: string;
  onQuery: (value: string) => void;
  matches: { id: string; title: string; kind: string }[];
  onPick: (id: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("relative min-w-0", className)}>
      <label className="flex min-h-11 min-w-0 items-center gap-2 rounded-xl border border-border bg-surface/80 px-3 py-2 backdrop-blur-md">
        <Search className="size-4 shrink-0 text-muted" />
        <input
          className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-subtle"
          placeholder="Find a page"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
        />
      </label>
      {matches.length > 0 && (
        <ul className="absolute top-full right-0 z-[80] mt-1 max-h-56 w-full overflow-auto rounded-xl border border-border bg-elevated py-1 shadow-lg">
          {matches.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                className="flex min-h-11 w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-surface"
                onClick={() => onPick(n.id)}
              >
                <span className="text-fg">{n.title}</span>
                <span className="font-mono text-xs text-subtle">{n.kind}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PagePreview({
  selectedNode,
  page,
  pageLoading,
  onWikiLink,
  onClose,
}: {
  selectedNode?: GraphNode;
  page: AtlasPage | null;
  pageLoading: boolean;
  onWikiLink: (target: string) => void;
  onClose?: () => void;
}) {
  if (!selectedNode) {
    return (
      <div className="px-5 py-4 text-sm text-muted">Select a star to read the page.</div>
    );
  }
  return (
    <article className="flex h-full min-h-0 w-full flex-col">
      <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <p className="font-mono text-xs tracking-wide text-subtle uppercase">{selectedNode.kind}</p>
          <h2 className="font-display text-xl font-medium italic text-fg">{selectedNode.title}</h2>
        </div>
        {onClose && (
          <button
            type="button"
            aria-label="Close preview"
            onClick={onClose}
            className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl text-muted hover:bg-elevated hover:text-fg"
          >
            <X className="size-5" />
          </button>
        )}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {pageLoading && (
          <p className="flex items-center gap-2 text-sm text-muted">
            <Loader2 className="size-4 animate-spin" />
            Loading
          </p>
        )}
        {!pageLoading && page && page.relatesTo.length > 0 && (
          <ul className="mb-4 flex flex-wrap gap-1.5">
            {page.relatesTo.map((r) => (
              <li key={`${r.kind}:${r.path}`}>
                <button
                  type="button"
                  onClick={() => onWikiLink(r.path)}
                  className="rounded-full border border-border px-2.5 py-1 font-mono text-[11px] text-muted hover:border-border-strong hover:text-fg"
                >
                  {r.kind} · {r.path.split("/").pop()?.replace(/\.md$/, "")}
                </button>
              </li>
            ))}
          </ul>
        )}
        {!pageLoading && page && (
          <MarkdownView markdown={page.body} onWikiLink={onWikiLink} />
        )}
        {!pageLoading && !page && (
          <p className="text-sm text-muted">No page body for this node.</p>
        )}
      </div>
    </article>
  );
}

function LayerToggle({
  active,
  onClick,
  icon,
  label,
  swatch,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
  swatch: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-h-10 items-center gap-2 rounded-xl border px-3 text-sm",
        active ? "border-border-strong bg-elevated text-fg" : "border-border text-muted",
      )}
    >
      <span className={cn("size-2 rounded-full", swatch)} />
      {icon}
      {label}
    </button>
  );
}
