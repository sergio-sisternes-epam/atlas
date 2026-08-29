import type { ReactNode } from "react";

type Props = {
  markdown: string;
  onWikiLink?: (target: string) => void;
};

function promoteLegacyIndexRows(md: string): string {
  return md
    .replace(
      /^(\s*[-*+]\s+)experience\s+`([^`]+)`(\s*[\u2014\u2013\-].*)$/gm,
      (_m, bullet, slug, rest) => `${bullet}[[raw/experiences/${slug}|${slug}]]${rest}`,
    )
    .replace(
      /^(\s*[-*+]\s+)experience\s+([A-Za-z0-9][A-Za-z0-9._-]*)(\s*[\u2014\u2013\-].*)$/gm,
      (_m, bullet, slug, rest) => `${bullet}[[raw/experiences/${slug}|${slug}]]${rest}`,
    );
}

export function MarkdownView({ markdown, onWikiLink }: Props) {
  const blocks = splitBlocks(promoteLegacyIndexRows(markdown.trim()));
  return (
    <div className="wiki-md text-sm leading-relaxed text-muted">
      {blocks.map((b, i) => renderBlock(b, i, onWikiLink))}
    </div>
  );
}

function splitBlocks(src: string): string[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let buf: string[] = [];
  let fence = false;
  const flush = () => {
    if (buf.length) {
      out.push(buf.join("\n"));
      buf = [];
    }
  };
  for (const line of lines) {
    if (line.startsWith("```")) {
      if (fence) {
        buf.push(line);
        flush();
        fence = false;
      } else {
        flush();
        fence = true;
        buf.push(line);
      }
      continue;
    }
    if (fence) {
      buf.push(line);
      continue;
    }
    if (/^\s*$/.test(line)) {
      flush();
      continue;
    }
    const isTable = /^\s*\|/.test(line);
    const prevTable = buf.length > 0 && /^\s*\|/.test(buf[0]!);
    if (buf.length && isTable !== prevTable) flush();
    const isList = /^\s*[-*+]\s+/.test(line) || /^\s*\d+\.\s+/.test(line);
    const prevList = buf.length > 0 && (/^\s*[-*+]\s+/.test(buf[0]!) || /^\s*\d+\.\s+/.test(buf[0]!));
    if (buf.length && isList !== prevList && !isList) flush();
    if (buf.length && /^(#{1,6}\s|---$|___$|\*\*\*$|>\s)/.test(line)) flush();
    buf.push(line);
  }
  flush();
  return out;
}

function renderBlock(block: string, key: number, onWiki?: (t: string) => void): ReactNode {
  if (/^\s*\|/.test(block)) {
    return renderTable(block, key, onWiki);
  }
  if (/^```/.test(block)) {
    const lines = block.split("\n");
    const body = lines.slice(1, lines[lines.length - 1]?.startsWith("```") ? -1 : undefined).join("\n");
    return (
      <pre
        key={key}
        className="my-3 overflow-x-auto rounded-xl border border-border bg-elevated px-3 py-2 font-mono text-xs text-fg"
      >
        {body}
      </pre>
    );
  }
  if (/^(---+|___+|\*\*\*+)$/.test(block.trim())) {
    return <hr key={key} className="my-4 border-border" />;
  }
  const heading = block.match(/^(#{1,6})\s+(.*)$/);
  if (heading && !block.includes("\n")) {
    const level = heading[1]!.length;
    const cls =
      level === 1
        ? "font-display mt-4 mb-2 text-xl font-medium text-fg"
        : level === 2
          ? "font-display mt-4 mb-2 text-lg font-medium text-fg"
          : "mt-3 mb-1 text-sm font-medium text-fg";
    const Tag = (`h${Math.min(level, 4)}` as "h1" | "h2" | "h3" | "h4");
    return (
      <Tag key={key} className={cls}>
        {inline(heading[2] ?? "", onWiki)}
      </Tag>
    );
  }
  if (/^>\s?/.test(block)) {
    const text = block
      .split("\n")
      .map((l) => l.replace(/^>\s?/, ""))
      .join("\n");
    return (
      <blockquote
        key={key}
        className="my-3 border-l-2 border-accent/50 pl-3 text-muted italic"
      >
        {inline(text, onWiki)}
      </blockquote>
    );
  }
  if (/^\s*[-*+]\s+/.test(block)) {
    const items = block.split("\n").filter((l) => /^\s*[-*+]\s+/.test(l));
    return (
      <ul key={key} className="my-2 list-disc space-y-1 pl-5">
        {items.map((item, i) => (
          <li key={i}>{inline(item.replace(/^\s*[-*+]\s+/, ""), onWiki)}</li>
        ))}
      </ul>
    );
  }
  if (/^\s*\d+\.\s+/.test(block)) {
    const items = block.split("\n").filter((l) => /^\s*\d+\.\s+/.test(l));
    return (
      <ol key={key} className="my-2 list-decimal space-y-1 pl-5">
        {items.map((item, i) => (
          <li key={i}>{inline(item.replace(/^\s*\d+\.\s+/, ""), onWiki)}</li>
        ))}
      </ol>
    );
  }
  return (
    <p key={key} className="my-2 text-pretty">
      {inline(block, onWiki)}
    </p>
  );
}

function splitCells(row: string): string[] {
  let s = row.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function isSepRow(row: string): boolean {
  const cells = splitCells(row);
  return cells.length > 0 && cells.every((c) => /^:?-{3,}:?$/.test(c));
}

function renderTable(
  block: string,
  key: number,
  onWiki?: (t: string) => void,
): ReactNode {
  const rows = block.split("\n").filter((l) => /^\s*\|/.test(l));
  if (!rows.length) return null;
  let head = splitCells(rows[0]!);
  let bodyRows = rows.slice(1);
  if (bodyRows[0] && isSepRow(bodyRows[0])) bodyRows = bodyRows.slice(1);
  return (
    <div key={key} className="my-3 overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-max border-collapse text-left text-xs">
        <thead className="bg-elevated">
          <tr>
            {head.map((c, i) => (
              <th
                key={i}
                className="border-b border-border px-3 py-2 font-medium text-fg"
              >
                {inline(c, onWiki)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bodyRows.map((row, ri) => (
            <tr key={ri} className="even:bg-elevated/40">
              {splitCells(row).map((c, ci) => (
                <td key={ci} className="border-b border-border/70 px-3 py-2 align-top">
                  {inline(c, onWiki)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Prefer readable labels; keep full path as navigation target. */
function shortWikiLabel(target: string): string {
  const t = target.replace(/\\/g, "/").replace(/\.md$/i, "");
  for (const prefix of [
    "raw/experiences/",
    "raw/articles/",
    "raw/papers/",
    "knowledge/",
    "experiences/",
    "decisions/",
    "work/",
    "lessons/",
    "recipes/",
    "modules/",
  ]) {
    if (t.startsWith(prefix)) return t.slice(prefix.length);
  }
  return t;
}

function inline(text: string, onWiki?: (t: string) => void): ReactNode[] {
  const tokens: ReactNode[] = [];
  const re =
    /(\[\[([^\]|]+)(?:\|([^\]]+))?\]\])|(\[([^\]]+)\]\(([^)]+)\))|(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(_[^_]+_)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) tokens.push(text.slice(last, m.index));
    if (m[1]) {
      const target = (m[2] ?? "").trim();
      const explicit = (m[3] ?? "").trim();
      const label = explicit || shortWikiLabel(target);
      tokens.push(
        <button
          key={`w${i++}`}
          type="button"
          className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
          onClick={() => onWiki?.(target)}
        >
          {label}
        </button>,
      );
    } else if (m[4]) {
      tokens.push(
        <a
          key={`a${i++}`}
          href={m[6]}
          className="text-accent underline decoration-accent/40 underline-offset-2"
          target="_blank"
          rel="noreferrer"
        >
          {m[5]}
        </a>,
      );
    } else if (m[7]) {
      tokens.push(
        <code
          key={`c${i++}`}
          className="rounded-md bg-elevated px-1 py-0.5 font-mono text-[0.85em] text-fg"
        >
          {m[7].slice(1, -1)}
        </code>,
      );
    } else if (m[8]) {
      tokens.push(
        <strong key={`b${i++}`} className="font-medium text-fg">
          {m[8].slice(2, -2)}
        </strong>,
      );
    } else {
      const raw = m[9] ?? m[10] ?? "";
      tokens.push(
        <em key={`i${i++}`}>{raw.slice(1, -1)}</em>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) tokens.push(text.slice(last));
  return tokens;
}
