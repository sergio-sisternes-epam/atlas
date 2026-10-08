// Shared helpers for the Node docs checks.
import { readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

export const SITE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const REPO_DIR = resolve(SITE_DIR, '..');
export const DIST_DIR = join(SITE_DIR, 'dist');
export const BASE = '/atlas';

const SKIP_DIRS = new Set(['node_modules', '.venv', '.astro', 'dist', '__pycache__', 'test-reports', '.git']);

/** Recursively list files under dir. Skips caches unless includeAll is set (used for dist). */
export function walk(dir, { includeAll = false } = {}) {
	const out = [];
	let entries;
	try {
		entries = readdirSync(dir, { withFileTypes: true });
	} catch {
		return out;
	}
	for (const entry of entries) {
		const full = join(dir, entry.name);
		if (entry.isDirectory()) {
			if (!includeAll && SKIP_DIRS.has(entry.name)) continue;
			out.push(...walk(full, { includeAll }));
		} else if (entry.isFile()) {
			out.push(full);
		}
	}
	return out.sort();
}

export function rel(path, from = REPO_DIR) {
	return relative(from, path).split(sep).join('/');
}

export function isFile(path) {
	try {
		return statSync(path).isFile();
	} catch {
		return false;
	}
}

export function requireDist() {
	try {
		if (statSync(DIST_DIR).isDirectory()) return;
	} catch {
		// fall through
	}
	console.error('error: site/dist does not exist. Run `npm run build` first.');
	process.exit(1);
}

export function lineOf(text, index) {
	let line = 1;
	for (let i = 0; i < index; i += 1) if (text.charCodeAt(i) === 10) line += 1;
	return line;
}

export const TEXT_EXT = /\.(md|mdx|astro|ts|mts|js|mjs|cjs|json|css|html|svg|xml|txt|yml|yaml|py|toml)$/i;

const ROOT_TEXT = /(^|\/)(\.nvmrc|\.gitignore|README|LICENSE|NOTICE)$/;

/** Text files to scan for leaks: site sources (caches excluded) plus everything in site/dist. */
export function scanTargets({ exclude = [] } = {}) {
	const skip = new Set(exclude);
	const sources = walk(SITE_DIR).filter((f) => TEXT_EXT.test(f) || ROOT_TEXT.test(f));
	const dist = walk(DIST_DIR, { includeAll: true }).filter((f) => TEXT_EXT.test(f));
	return [...sources, ...dist].filter((f) => !skip.has(rel(f)));
}
