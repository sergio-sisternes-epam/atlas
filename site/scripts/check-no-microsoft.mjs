#!/usr/bin/env node
// V7: no links to Microsoft-owned or Microsoft-branded domains.
//
// Usage: node scripts/check-no-microsoft.mjs [--source] [--dist]   (default: both)
// --source scans site/src, site/public, site/astro.config.mjs and the root README.md.
// --dist scans every href, src, srcset and CSS url() in site/dist (HTML and CSS).
// Plain font names such as "Segoe UI" are not links and are allowed.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { DIST_DIR, REPO_DIR, SITE_DIR, TEXT_EXT, lineOf, rel, requireDist, walk } from './lib.mjs';

const DOMAINS = [
	'microsoft.com',
	'aka.ms',
	'azure.com',
	'windows.net',
	'azurewebsites.net',
	'azureedge.net',
	'visualstudio.com',
	'msdn.com',
	'live.com',
	'office.com',
	'outlook.com',
];
const ORGS = ['microsoft', 'azure'];

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// A domain or any subdomain, as a host (not part of a longer label such as "alive.com").
const HOST_RE = new RegExp(`(?<![a-z0-9-])(?:[a-z0-9-]+\\.)*(?:${DOMAINS.map(esc).join('|')})(?![a-z0-9-])`, 'gi');
const ORG_RE = new RegExp(`github\\.com/(?:${ORGS.join('|')})(?:[/"'\\s)>#?]|$)`, 'gi');

function scanText(text) {
	const hits = [];
	for (const re of [HOST_RE, ORG_RE]) {
		re.lastIndex = 0;
		for (const m of text.matchAll(re)) hits.push({ index: m.index, match: m[0] });
	}
	return hits;
}

const args = new Set(process.argv.slice(2));
const doSource = args.has('--source') || !args.has('--dist');
const doDist = args.has('--dist') || !args.has('--source');

const findings = [];
let scanned = 0;

if (doSource) {
	const files = [
		...walk(join(SITE_DIR, 'src')),
		...walk(join(SITE_DIR, 'public')),
		join(SITE_DIR, 'astro.config.mjs'),
		join(REPO_DIR, 'README.md'),
	].filter((f) => TEXT_EXT.test(f));
	for (const file of files) {
		const text = readFileSync(file, 'utf8');
		scanned += 1;
		for (const hit of scanText(text)) findings.push(`${rel(file)}:${lineOf(text, hit.index)}: ${hit.match}`);
	}
}

if (doDist) {
	requireDist();
	const LINK_ATTR = /\s(?:href|src|srcset)\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
	const CSS_URL = /url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/gi;
	for (const file of walk(DIST_DIR, { includeAll: true }).filter((f) => /\.(html|css)$/.test(f))) {
		const text = readFileSync(file, 'utf8');
		scanned += 1;
		const patterns = file.endsWith('.html') ? [LINK_ATTR, CSS_URL] : [CSS_URL];
		for (const re of patterns) {
			for (const m of text.matchAll(re)) {
				const value = m[1] ?? m[2] ?? m[3] ?? '';
				if (scanText(value).length) findings.push(`${rel(file)}:${lineOf(text, m.index)}: ${value}`);
			}
		}
	}
}

if (findings.length) {
	console.log(`V7 FAIL: ${findings.length} Microsoft-owned link(s) or domain(s):`);
	for (const f of findings) console.log(`  ${f}`);
	process.exit(1);
}
const scope = [doSource && 'sources', doDist && 'dist'].filter(Boolean).join(' + ');
console.log(`V7 check-no-microsoft: OK (${scanned} files, ${scope})`);
