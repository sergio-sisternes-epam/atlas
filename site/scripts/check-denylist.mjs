#!/usr/bin/env node
// V8 (c): private host deny-list scan.
//
// Reads newline-separated private host/domain patterns from env DOCS_HOST_DENYLIST
// (an Actions secret provided by the security reviewer; never committed, never printed).
// Unset or empty: warn and exit 0 only when DOCS_DENYLIST_MODE=pending-ok; otherwise fail closed.
// On a hit, print only file:line and the entry index, never the entry or the matched text.
import { readFileSync } from 'node:fs';
import { DIST_DIR, rel, scanTargets } from './lib.mjs';

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

// Plain substring match, case-insensitive. A leading "*." means "this domain or any subdomain".
const needles = entries.map((entry) => entry.toLowerCase().replace(/^\*\./, ''));

const files = scanTargets();
let hits = 0;
for (const file of files) {
	const lines = readFileSync(file, 'utf8').toLowerCase().split('\n');
	lines.forEach((line, i) => {
		needles.forEach((needle, n) => {
			if (line.includes(needle)) {
				hits += 1;
				console.log(`  ${rel(file)}:${i + 1}: entry #${n + 1}`);
			}
		});
	});
}

const distFiles = files.filter((f) => f.startsWith(DIST_DIR)).length;
if (hits) {
	console.log(`V8(c) FAIL: ${hits} deny-list hit(s). Remove the private host references listed above.`);
	process.exit(1);
}
console.log(`V8(c) check-denylist: OK (${entries.length} entries, ${files.length - distFiles} source files, ${distFiles} dist files)`);
