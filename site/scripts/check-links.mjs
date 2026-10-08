#!/usr/bin/env node
// V5: every internal href/src in site/dist resolves to a built file, including #anchors.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { BASE, DIST_DIR, isFile, rel, requireDist, walk } from './lib.mjs';

requireDist();

const ATTR = /\s(?:href|src|srcset)\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
const ID = /\sid\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
const SKIP_SCHEME = /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i;

const files = walk(DIST_DIR, { includeAll: true });
const htmlFiles = files.filter((f) => f.endsWith('.html'));
const idCache = new Map();

function idsOf(file) {
	if (!idCache.has(file)) {
		const ids = new Set();
		for (const m of readFileSync(file, 'utf8').matchAll(ID)) ids.add(decodeURIComponent(m[1] ?? m[2]));
		idCache.set(file, ids);
	}
	return idCache.get(file);
}

function decodeEntities(value) {
	return value.replace(/&amp;/g, '&').replace(/&#x27;|&#39;/g, "'").replace(/&quot;/g, '"');
}

/** Map a URL path under the base to a file in dist, or null. */
function target(pathname) {
	if (!pathname.startsWith(`${BASE}/`) && pathname !== BASE) return null;
	let local = decodeURIComponent(pathname.slice(BASE.length)) || '/';
	if (local.endsWith('/')) local += 'index.html';
	const full = join(DIST_DIR, local);
	if (isFile(full)) return full;
	if (isFile(`${full}.html`)) return `${full}.html`;
	if (isFile(join(full, 'index.html'))) return join(full, 'index.html');
	return null;
}

const broken = [];
let checked = 0;
for (const file of htmlFiles) {
	const html = readFileSync(file, 'utf8');
	const pagePath = `/${rel(file, DIST_DIR)}`;
	const pageUrl = new URL(`${BASE}${pagePath}`, 'https://site.invalid');
	for (const m of html.matchAll(ATTR)) {
		const raw = decodeEntities((m[1] ?? m[2]).trim());
		const values = /srcset/i.test(m[0]) ? raw.split(',').map((s) => s.trim().split(/\s+/)[0]) : [raw];
		for (const value of values) {
			if (!value || SKIP_SCHEME.test(value)) continue;
			checked += 1;
			const url = new URL(value, pageUrl);
			const dest = target(url.pathname);
			if (!dest) {
				broken.push(`${rel(file)}: ${value} (no file for ${url.pathname})`);
				continue;
			}
			const anchor = url.hash ? decodeURIComponent(url.hash.slice(1)) : '';
			if (anchor && dest.endsWith('.html') && !idsOf(dest).has(anchor)) {
				broken.push(`${rel(file)}: ${value} (no element id="${anchor}")`);
			}
		}
	}
}

if (broken.length) {
	console.log(`V5 FAIL: ${broken.length} broken internal link(s):`);
	for (const b of broken) console.log(`  ${b}`);
	process.exit(1);
}
console.log(`V5 check-links: OK (${checked} internal links in ${htmlFiles.length} HTML files)`);
