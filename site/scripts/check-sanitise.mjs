#!/usr/bin/env node
// V8 (a+b): public pattern scan for secrets, hosts, addresses, emails and home paths.
// Scans site sources (excluding node_modules, .venv, .astro, dist caches) and site/dist.
// Allowlist: scripts/sanitise-allowlist.json (public patterns only).
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { DIST_DIR, SITE_DIR, lineOf, rel, scanTargets } from './lib.mjs';

const allowlist = JSON.parse(readFileSync(join(SITE_DIR, 'scripts', 'sanitise-allowlist.json'), 'utf8'));
const allow = Object.fromEntries(
	Object.entries(allowlist.allow ?? {}).map(([kind, list]) => [kind, list.map((p) => new RegExp(p, 'i'))]),
);

const vendored = (allowlist.vendored_exemptions ?? []).map((e) => ({ path: new RegExp(e.path), kinds: new Set(e.kinds) }));
const exempt = (file, kind) => vendored.some((e) => e.kinds.has(kind) && e.path.test(rel(file)));

const OCTET = '(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)';
const RULES = [
	{ kind: 'github-token', re: /\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{4,}/g },
	{ kind: 'github-token', re: /\bgithub_pat_[A-Za-z0-9_]{4,}/g },
	{ kind: 'slack-token', re: /\bxox[abpr]-[A-Za-z0-9-]{4,}/g },
	{ kind: 'aws-key', re: /\bAKIA[0-9A-Z]{12,}\b/g },
	{ kind: 'private-key', re: /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/g },
	{ kind: 'ssh-remote', re: /\b[A-Za-z0-9._-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+:(?!\/\/)/g },
	{ kind: 'ipv4', re: new RegExp(`(?<![\\w.])${OCTET}(?:\\.${OCTET}){3}(?![\\w.]*\\d)`, 'g') },
	{ kind: 'private-host', re: /\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:ts\.net|internal|local)(?![\w$(-])/gi },
	{ kind: 'cloud-resource', re: /\b(?:snet|vnet|rg|nsg)-[a-z0-9][a-z0-9_-]*/gi },
	{ kind: 'email', re: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b/g },
	{ kind: 'home_path', re: /\/home\/[A-Za-z0-9._-]+\//g },
	{ kind: 'home_path', re: /\/Users\/[A-Za-z0-9._-]+\//g },
];

const files = scanTargets({ exclude: allowlist.exclude_paths ?? [] });
const findings = [];
for (const file of files) {
	const text = readFileSync(file, 'utf8');
	for (const { kind, re } of RULES) {
		if (exempt(file, kind)) continue;
		for (const m of text.matchAll(re)) {
			const value = m[0];
			if ((allow[kind] ?? []).some((a) => a.test(value))) continue;
			findings.push(`${rel(file)}:${lineOf(text, m.index)}: ${kind}: ${value}`);
		}
	}
}

const distFiles = files.filter((f) => f.startsWith(DIST_DIR)).length;
if (findings.length) {
	console.log(`V8 FAIL: ${findings.length} sanitisation finding(s):`);
	for (const f of findings) console.log(`  ${f}`);
	console.log('Fix the content, or add a PUBLIC pattern to scripts/sanitise-allowlist.json if it is a false positive.');
	process.exit(1);
}
console.log(`V8 check-sanitise: OK (${files.length - distFiles} source files, ${distFiles} dist files)`);
