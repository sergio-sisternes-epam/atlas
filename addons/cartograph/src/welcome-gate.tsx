import { useMemo, useState } from "react";
import { FolderOpen, Map, Search } from "lucide-react";
import type { StoreInfo } from "./atlas/types";
import { cn } from "./cn";

export function WelcomeGate({
  stores,
  error,
  onOpen,
}: {
  stores: StoreInfo[];
  error?: string | null;
  onOpen: (root: string) => void;
}) {
  const [q, setQ] = useState("");
  const [path, setPath] = useState("");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return stores;
    return stores.filter(
      (s) =>
        s.label.toLowerCase().includes(needle) ||
        (s.skill ?? "").toLowerCase().includes(needle) ||
        (s.atlasId ?? "").toLowerCase().includes(needle) ||
        s.format.includes(needle),
    );
  }, [stores, q]);

  const atlas = filtered.filter((s) => s.format === "atlas");

  return (
    <div className="relative flex h-dvh min-h-0 flex-col overflow-hidden bg-bg text-fg">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,color-mix(in_oklab,var(--color-experience)_12%,transparent),transparent_55%)]" />
      <header className="relative z-10 shrink-0 px-5 pt-8 pb-4 text-center md:pt-12">
        <p className="font-mono text-[10px] tracking-[0.28em] text-subtle uppercase">Cartograph</p>
        <h1 className="mt-2 font-display text-4xl font-medium text-fg italic md:text-5xl">
          Open an Atlas
        </h1>
        <p className="mx-auto mt-3 max-w-md text-sm text-muted">
          Skills on this machine with <span className="text-fg">SCHEMA.json</span>.
        </p>
      </header>

      <div className="relative z-10 mx-auto w-full max-w-3xl shrink-0 px-4">
        <label className="flex min-h-11 items-center gap-2 rounded-xl border border-border bg-surface/80 px-3 backdrop-blur-md">
          <Search className="size-4 text-muted" />
          <input
            className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-subtle"
            placeholder="Filter skills"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Filter Atlas-compatible skills"
          />
        </label>
      </div>

      <div className="relative z-10 mx-auto min-h-0 w-full max-w-3xl flex-1 overflow-y-auto px-4 py-5">
        {error && (
          <p className="mb-4 rounded-xl border border-border bg-elevated px-4 py-3 text-sm text-danger">
            {error}
          </p>
        )}
        {filtered.length === 0 && (
          <p className="py-10 text-center text-sm text-muted">No matching stores on this machine.</p>
        )}
        {atlas.length > 0 && (
          <section className="mb-8">
            <h2 className="mb-3 font-mono text-[10px] tracking-[0.2em] text-subtle uppercase">Atlas</h2>
            <ul className="grid gap-3 sm:grid-cols-2">
              {atlas.map((s) => (
                <li key={s.root}>
                  <StoreCard store={s} onOpen={onOpen} />
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <form
        className="relative z-10 mx-auto flex w-full max-w-3xl shrink-0 flex-col gap-2 px-4 pt-2 pb-[max(1rem,env(safe-area-inset-bottom))] sm:flex-row sm:items-center"
        onSubmit={(e) => {
          e.preventDefault();
          if (path.trim()) onOpen(path.trim());
        }}
      >
        <label className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-xl border border-border bg-surface/80 px-3">
          <FolderOpen className="size-4 shrink-0 text-muted" />
          <input
            className="min-w-0 flex-1 bg-transparent font-mono text-xs text-fg outline-none placeholder:text-subtle"
            placeholder="Or paste any Atlas root"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            aria-label="Atlas store path"
            spellCheck={false}
          />
        </label>
        <button
          type="submit"
          disabled={!path.trim()}
          className="min-h-11 shrink-0 rounded-xl bg-accent px-4 text-sm font-medium text-accent-fg disabled:opacity-40"
        >
          Open path
        </button>
      </form>
    </div>
  );
}

function StoreCard({ store, onOpen }: { store: StoreInfo; onOpen: (root: string) => void }) {
  const pages = store.pages ?? store.experiences + store.decisions + store.work + store.other;
  return (
    <button
      type="button"
      onClick={() => onOpen(store.root)}
      className="flex min-h-24 w-full flex-col items-start rounded-2xl border border-border bg-surface/75 p-4 text-left shadow-lg backdrop-blur-md transition-transform duration-150 ease-out active:scale-[0.96] hover:border-border-strong"
    >
      <span className="flex w-full items-center justify-between gap-2">
        <span className="font-display text-xl text-fg italic">{store.label}</span>
        <Map className="size-4 shrink-0 text-muted" />
      </span>
      <span className="mt-1 font-mono text-[11px] text-subtle">
        {store.format === "atlas" ? "SCHEMA.json" : "not Atlas"}
        {store.atlasId ? ` · ${store.atlasId}` : ""}
      </span>
      <span className={cn("mt-3 font-mono text-xs text-muted")}>
        {pages} {pages === 1 ? "page" : "pages"}
      </span>
    </button>
  );
}
