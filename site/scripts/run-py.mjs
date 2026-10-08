#!/usr/bin/env node
// Run a Python script with the project interpreter, so npm scripts work locally and in CI.
// Interpreter: $ATLAS_PYTHON, else site/.venv/bin/python when present, else python3.
// Defaults --atlas-src to $ATLAS_SRC or ../atlas-src when the script accepts it.
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { REPO_DIR, SITE_DIR, isFile } from './lib.mjs';

const [script, ...rest] = process.argv.slice(2);
if (!script) {
	console.error('usage: node scripts/run-py.mjs <script.py> [args...]');
	process.exit(2);
}
const venv = join(SITE_DIR, '.venv', 'bin', 'python');
const python = process.env.ATLAS_PYTHON || (isFile(venv) ? venv : 'python3');
const args = [join(SITE_DIR, 'scripts', script), ...rest];
if (!rest.includes('--atlas-src')) args.push('--atlas-src', process.env.ATLAS_SRC || join(REPO_DIR, 'atlas-src'));

const result = spawnSync(python, args, { stdio: 'inherit' });
if (result.error) {
	console.error(`cannot run ${python}: ${result.error.message}`);
	process.exit(1);
}
process.exit(result.status ?? 1);
