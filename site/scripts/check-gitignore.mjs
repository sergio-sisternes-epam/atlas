#!/usr/bin/env node
// check-gitignore: fail if any tracked file, or any untracked file that .gitignore does
// not exclude (and so could be committed), sits in a build, cache or input folder.
import { execFileSync } from 'node:child_process';
import { REPO_DIR } from './lib.mjs';

const FORBIDDEN = ['dist', '.astro', 'node_modules', '.venv', 'atlas-src', '.inputs'];

const tracked = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
	cwd: REPO_DIR,
	encoding: 'utf8',
})
	.split('\0')
	.filter(Boolean);
const bad = tracked.filter((path) => path.split('/').some((part) => FORBIDDEN.includes(part)));

if (bad.length) {
	console.log(`check-gitignore FAIL: ${bad.length} tracked or committable file(s) in ignored folders (${FORBIDDEN.join(', ')}):`);
	for (const path of bad.slice(0, 50)) console.log(`  ${path}`);
	if (bad.length > 50) console.log(`  … and ${bad.length - 50} more`);
	process.exit(1);
}
console.log(`check-gitignore: OK (${tracked.length} tracked or committable files; none under ${FORBIDDEN.map((f) => `${f}/`).join(', ')})`);
