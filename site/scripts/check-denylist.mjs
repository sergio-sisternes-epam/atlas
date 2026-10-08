#!/usr/bin/env node
// V8 (c): private host deny-list scan.
//
// Reads newline-separated private host/domain patterns from env DOCS_HOST_DENYLIST
// (an Actions secret provided by the security reviewer; never committed, never printed).
// Unset or empty: warn and exit 0 only when DOCS_DENYLIST_MODE=pending-ok; otherwise fail closed.
// On a hit, print only file:line and the entry index, never the entry or the matched text.
//
// Usage:
//   node check-denylist.mjs                         scan site/ sources + site/dist (local runs)
//   node check-denylist.mjs --dist <dir>            scan site/ sources + <dir> (or env DOCS_SCAN_DIST)
//   node check-denylist.mjs --dist-only [--dist d]  scan only the built dist dir (CI enforce job)
// --dist-only exists for CI, where the enforce job holds only the trusted site/scripts and the
// built dist artefact. The dist is the published output, so it covers what matters for publication.
// Node built-ins only: the enforce job installs no packages.
import { readFileSync, statSync } from 'node:fs';
import { relative, resolve, sep } from 'node:path';
import { parseArgs } from 'node:util';
import { DIST_DIR, rel, scanTargets } from './lib.mjs';

let args;
try {
	({ values: args } = parseArgs({
		options: {
			dist: { type: 'string' },
			'dist-only': { type: 'boolean', default: false },
		},
		strict: true,
		allowPositionals: false,
	}));
} catch (err) {
	console.log(`V8(c) FAIL: ${err.message}`);
	process.exit(2);
}

const distArg = args.dist ?? process.env.DOCS_SCAN_DIST ?? '';
const distDir = distArg ? resolve(distArg) : DIST_DIR;
const distOnly = args['dist-only'];

const entries = (process.env.DOCS_HOST_DENYLIST ?? '')
	.split(/\r?\n/)
	.map((line) => line.trim())
	.filter((line) => line && !line.startsWith('#'));

if (!entries.length) {
	if (process.env.DOCS_DENYLIST_MODE === 'pending-ok') {
		console.log('::warning::V8(c) PENDING — private host deny-list not provisioned');
		process.exit(0);
	}
	console.log('V8(c) FAIL: DOCS_HOST_DENYLIST is not set (fail closed). Set DOCS_DENYLIST_MODE=pending-ok only on pull requests.');
	process.exit(1);
}

let distIsDir = false;
try {
	distIsDir = statSync(distDir).isDirectory();
} catch {
	// handled below
}
if ((distOnly || distArg) && !distIsDir) {
	console.log(`V8(c) FAIL: dist directory not found: ${distArg || 'site/dist'} (fail closed)`);
	process.exit(1);
}

// Plain substring match, case-insensitive. A leading "*." means "this domain or any subdomain".
const needles = entries.map((entry) => entry.toLowerCase().replace(/^\*\./, ''));

const inDist = (file) => file === distDir || file.startsWith(distDir + sep);
const label = (file) =>
	inDist(file) && distDir !== DIST_DIR ? `dist/${relative(distDir, file).split(sep).join('/')}` : rel(file);

const files = scanTargets({ distDir, includeSources: !distOnly });
const distFiles = files.filter(inDist).length;
if (distOnly && !distFiles) {
	console.log('V8(c) FAIL: no text files found in the dist directory (fail closed)');
	process.exit(1);
}

let hits = 0;
for (const file of files) {
	const lines = readFileSync(file, 'utf8').toLowerCase().split('\n');
	lines.forEach((line, i) => {
		needles.forEach((needle, n) => {
			if (line.includes(needle)) {
				hits += 1;
				console.log(`  ${label(file)}:${i + 1}: entry #${n + 1}`);
			}
		});
	});
}

if (hits) {
	console.log(`V8(c) FAIL: ${hits} deny-list hit(s). Remove the private host references listed above.`);
	process.exit(1);
}
console.log(`V8(c) check-denylist: OK (${entries.length} entries, ${files.length - distFiles} source files, ${distFiles} dist files)`);
