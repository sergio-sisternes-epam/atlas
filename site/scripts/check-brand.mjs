#!/usr/bin/env node
// V9: brand guard.
// 1. site/src/styles/atlas-tokens.css matches the sha256 in atlas-tokens.lock.json.
// 2. No raw hex colours and no raw px/rem/em lengths in any other site CSS or Astro <style>.
// 3. No Starlight "caution" aside in content (atlas-style has no warning colour role).
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { SITE_DIR, lineOf, rel, walk } from './lib.mjs';

const STYLES = join(SITE_DIR, 'src', 'styles');
const TOKENS = join(STYLES, 'atlas-tokens.css');
const LOCK = join(STYLES, 'atlas-tokens.lock.json');
// Explicit exceptions as "path:line-text-substring". Keep this tiny; it is empty today.
const EXCEPTIONS = [];

const failures = [];

const lock = JSON.parse(readFileSync(LOCK, 'utf8'));
const actual = createHash('sha256').update(readFileSync(TOKENS)).digest('hex');
if (actual !== lock.sha256) {
	failures.push(`${rel(TOKENS)}: sha256 ${actual} != lock ${lock.sha256} (copy tokens.css verbatim from atlas-style ${lock.version})`);
}

const HEX = /(?<![\w&-])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})(?![\w-])/gi;
const LENGTH = /(?<![\w.-])-?(?:\d+\.?\d*|\.\d+)(?:px|rem|em)(?![\w-])/gi;

function scanCss(file, css, offset, text) {
	const clean = css.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '));
	for (const [kind, re] of [
		['raw hex colour', HEX],
		['raw length', LENGTH],
	]) {
		for (const m of clean.matchAll(re)) {
			const line = lineOf(text, offset + m.index);
			const lineText = text.split('\n')[line - 1] ?? '';
			if (EXCEPTIONS.some((e) => e === `${rel(file)}:${lineText.trim()}`)) continue;
			failures.push(`${rel(file)}:${line}: ${kind} ${m[0]} (use a var(--token))`);
		}
	}
}

const srcFiles = walk(join(SITE_DIR, 'src'));
let styled = 0;
for (const file of srcFiles) {
	if (file === TOKENS) continue;
	const text = readFileSync(file, 'utf8');
	if (file.endsWith('.css')) {
		styled += 1;
		scanCss(file, text, 0, text);
	} else if (file.endsWith('.astro')) {
		for (const m of text.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)) {
			styled += 1;
			scanCss(file, m[1], m.index + m[0].indexOf(m[1]), text);
		}
		for (const m of text.matchAll(/\sstyle\s*=\s*(?:"([^"]*)"|'([^']*)')/gi)) {
			scanCss(file, m[1] ?? m[2], m.index, text);
		}
	}
}

const CAUTION = /:::\s*caution\b|<Aside\b[^>]*\btype\s*=\s*(?:\{\s*)?["']caution["']/gi;
const content = srcFiles.filter((f) => /\.(md|mdx|mdoc|astro)$/.test(f));
for (const file of content) {
	const text = readFileSync(file, 'utf8');
	for (const m of text.matchAll(CAUTION)) {
		failures.push(`${rel(file)}:${lineOf(text, m.index)}: banned caution aside (use note, tip or danger)`);
	}
}

if (failures.length) {
	console.log(`V9 FAIL: ${failures.length} brand problem(s):`);
	for (const f of failures) console.log(`  ${f}`);
	process.exit(1);
}
console.log(`V9 check-brand: OK (tokens sha256 ${actual.slice(0, 12)}…, ${styled} style blocks/files, ${content.length} content files)`);
