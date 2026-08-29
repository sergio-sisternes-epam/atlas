import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { RootPreset } from "./types";

function loadEnvFile(): void {
  if (typeof process === "undefined" || !process.env) return;
  if ((process.env as { __ATLAS_ENV_LOADED?: string }).__ATLAS_ENV_LOADED) return;
  try {
    const path =
      process.env.ATLAS_ENV_FILE ||
      process.env.OKF_WIKI_ENV_FILE ||
      "/home/workdir/artifacts/atlas-viewer.env";
    if (!existsSync(path)) {
      (process.env as { __ATLAS_ENV_LOADED?: string }).__ATLAS_ENV_LOADED = "1";
      return;
    }
    for (const line of readFileSync(path, "utf8").split("\n")) {
      const s = line.trim();
      if (!s || s.startsWith("#")) continue;
      const i = s.indexOf("=");
      if (i <= 0) continue;
      const k = s.slice(0, i).trim();
      const v = s.slice(i + 1).trim();
      if (k && !(process.env[k] && process.env[k]!.length)) process.env[k] = v;
    }
  } catch {
    /* ignore */
  }
  (process.env as { __ATLAS_ENV_LOADED?: string }).__ATLAS_ENV_LOADED = "1";
}

function env(name: string): string {
  if (typeof process === "undefined" || !process.env) return "";
  loadEnvFile();
  return String(process.env[name] ?? "").trim();
}

function parsePresets(raw: string): RootPreset[] {
  if (!raw) return [];
  const out: RootPreset[] = [];
  for (const part of raw.split(",")) {
    const s = part.trim();
    if (!s) continue;
    const idx = s.indexOf(":");
    if (idx <= 0) continue;
    const label = s.slice(0, idx).trim();
    const root = s.slice(idx + 1).trim();
    if (label && root) out.push({ label, root });
  }
  return out;
}

/** Atlas skill root — this add-on lives at addons/cartograph/src/atlas/. */
export function atlasSkillRoot(): string {
  const fromEnv = env("ATLAS_SKILL_ROOT");
  if (fromEnv && existsSync(join(fromEnv, "SKILL.md"))) return resolve(fromEnv);
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    const guessed = resolve(here, "../../../../");
    if (existsSync(join(guessed, "SKILL.md"))) return guessed;
  } catch {
    /* bundled */
  }
  for (const p of [
    "/root/.grok/server-skills/atlas",
    "/home/workdir/.grok/skills/atlas",
  ]) {
    if (existsSync(join(p, "SKILL.md"))) return p;
  }
  return "";
}

function skillStore(rel: string, bundledId: string): string {
  const root = atlasSkillRoot();
  if (root) {
    const live = resolve(root, rel);
    if (existsSync(live)) return live;
  }
  return `bundled:${bundledId}`;
}

/** Defaults are the Atlas skill's own stores — not host copies. */
export const BUNDLED_PRESETS: RootPreset[] = [
  { label: "Skill memory", root: skillStore("references/atlas", "skill-memory") },
  { label: "Mini atlas", root: skillStore("fixtures/mini-atlas", "mini") },
];

export const DEFAULT_ROOT =
  env("ATLAS_ROOT") ||
  env("ATLAS_VIEWER_ROOT") ||
  env("OKF_WIKI_ROOT") ||
  env("OKF_WIKI_VIEWER_ROOT") ||
  BUNDLED_PRESETS[0]?.root ||
  "";

export const ROOT_PRESETS: RootPreset[] = [
  ...parsePresets(env("ATLAS_PRESETS") || env("OKF_WIKI_PRESETS")),
  ...BUNDLED_PRESETS,
].filter((p, i, arr) => arr.findIndex((q) => q.root === p.root) === i);
