#!/usr/bin/env node
// V13 (H3): repository size guard. Final budgets come from site/size-budget.json.
//
// Usage: node scripts/check-size.mjs [--base <ref>] [--skip-diff]
//                                    [--history-url <url>] [--mirror-url <url>]
//   --base         compare the working tree (including untracked, non-ignored files) with
//                  the merge base of <ref> and HEAD (default origin/docs).
//   --skip-diff    skip (a), (b), (c) and (e), for example on the first commit of a branch.
//   --history-url  for (d), clone <url> with --bare --single-branch --branch docs and
//                  measure it. Without it, (d) measures this checkout's HEAD history as a
//                  stand-in, plus a projection that commits the working tree in a temp repo.
//   --mirror-url   for (f), measure a fresh `git clone --mirror <url>`. Skipped without it.
//
// (a) no build output, caches, archives, media or binaries;
// (b1) raster image cap; (b2) cap for any single file, the lockfile included;
// (c) bytes added by the diff, the lockfile excluded and reported separately;
// (d) packed docs history: warn and fail thresholds;
// (e) svgo dry run on added SVGs; any added raster fails;
// (f) packed size of a mirror clone of the whole repository: warn and fail thresholds.
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { optimize } from 'svgo';
import { REPO_DIR, SITE_DIR } from './lib.mjs';

const budget = JSON.parse(readFileSync(join(SITE_DIR, 'size-budget.json'), 'utf8'));
if (budget.status !== 'final') {
	console.error('V13 FAIL: size-budget.json must have "status": "final"');
	process.exit(1);
}

const args = { base: 'origin/docs', skipDiff: false, historyUrl: '', mirrorUrl: '' };
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i += 1) {
	if (argv[i] === '--base') args.base = argv[++i];
	else if (argv[i] === '--skip-diff') args.skipDiff = true;
	else if (argv[i] === '--history-url') args.historyUrl = argv[++i];
	else if (argv[i] === '--mirror-url') args.mirrorUrl = argv[++i];
	else {
		console.error(`unknown argument ${argv[i]}`);
		process.exit(1);
	}
}

const run = (cwd, cmdArgs, opts = {}) =>
	execFileSync('git', cmdArgs, { cwd, encoding: 'utf8', maxBuffer: 1 << 28, stdio: ['pipe', 'pipe', 'pipe'], ...opts });
const git = (...a) => run(REPO_DIR, a);
const gitOk = (...a) => spawnSync('git', a, { cwd: REPO_DIR, stdio: 'ignore' }).status === 0;
const fmt = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(2)} MiB` : `${(n / 1024).toFixed(1)} KiB`);
// Bare repositories are always addressed with --git-dir (safe.bareRepository may be 'explicit').
const bare = (gitDir, a, opts) => run(tmpdir(), ['--git-dir', gitDir, ...a], opts);
const sizePack = (gitDir) => {
	const line = bare(gitDir, ['count-objects', '-v']).split('\n').find((l) => l.startsWith('size-pack:'));
	return Number(line.split(':')[1].trim()) * 1024;
};
const tempDirs = [];
const tempDir = (name) => {
	const d = mkdtempSync(join(tmpdir(), `atlas-docs-${name}-`));
	tempDirs.push(d);
	return d;
};
const cleanup = () => tempDirs.forEach((d) => rmSync(d, { recursive: true, force: true }));

const failures = [];
const warnings = [];
const notes = [];
const table = [];
// Adds one row. warn and fail are byte thresholds or null; the value fails above fail.
const row = (measure, value, warn, fail, display) => {
	let result = 'ok';
	if (fail !== null && value > fail) {
		result = 'FAIL';
		failures.push(`${measure}: ${fmt(value)} > ${fmt(fail)}`);
	} else if (warn !== null && value > warn) {
		result = 'WARN';
		warnings.push(`${measure}: ${fmt(value)} > ${fmt(warn)}`);
	}
	table.push([measure, display ?? fmt(value), warn === null ? '-' : fmt(warn), fail === null ? '-' : fmt(fail), result]);
};
const countRow = (measure, count) => {
	table.push([measure, String(count), '-', '0', count ? 'FAIL' : 'ok']);
};

const lockPath = budget.lockfile;
const brandVerbatim = new Set(budget.brand_verbatim);
const rasterRe = new RegExp(`\\.(?:${budget.raster_extensions.join('|')})$`, 'i');
const forbiddenExtRe = new RegExp(`(?:\\.tar\\.[^/]+|\\.(?:${budget.forbidden_extensions.join('|')}))$`, 'i');
const forbiddenPath = (p) =>
	p.split('/').slice(0, -1).some((part) => budget.forbidden_dirs.includes(part)) ||
	budget.forbidden_prefixes.some((prefix) => p.startsWith(prefix)) ||
	forbiddenExtRe.test(p);

try {
	if (!args.skipDiff) {
		if (!gitOk('rev-parse', '--verify', '--quiet', `${args.base}^{commit}`)) {
			console.error(`V13 FAIL: base ${args.base} is not available (fetch it, or pass --skip-diff)`);
			process.exit(1);
		}
		const mergeBase = git('merge-base', args.base, 'HEAD').trim();
		const changes = new Map();
		const parts = git('diff', '--name-status', '--no-renames', '-z', mergeBase).split('\0');
		for (let i = 0; i + 1 < parts.length; i += 2) if (parts[i]) changes.set(parts[i + 1], parts[i]);
		for (const path of git('ls-files', '--others', '--exclude-standard', '-z').split('\0').filter(Boolean)) {
			changes.set(path, 'A');
		}

		let added = 0;
		let lockAdded = 0;
		let largest = { path: '', size: 0 };
		let largestRaster = { path: '', size: 0 };
		let forbidden = 0;
		const svgs = [];
		const rasters = [];
		for (const [path, status] of [...changes].sort()) {
			if (status === 'D') continue;
			const oldSize = status === 'A' ? 0 : Number(git('cat-file', '-s', `${mergeBase}:${path}`).trim());
			const size = statSync(join(REPO_DIR, path)).size;
			if (forbiddenPath(path)) {
				forbidden += 1;
				failures.push(`(a) forbidden path: ${path}`);
			}
			if (rasterRe.test(path)) {
				rasters.push(path);
				if (size > largestRaster.size) largestRaster = { path, size };
			}
			if (size > budget.file_max_bytes) failures.push(`(b2) ${path}: ${fmt(size)} > ${fmt(budget.file_max_bytes)}`);
			if (path !== lockPath && size > largest.size) largest = { path, size };
			const grew = Math.max(size - oldSize, 0);
			if (path === lockPath) lockAdded += grew;
			else added += grew;
			if (/\.svg$/i.test(path)) svgs.push(path);
		}

		countRow('(a) forbidden paths', forbidden);
		if (largestRaster.path) {
			row(`(b1) largest raster (${largestRaster.path})`, largestRaster.size, null, budget.raster_image_max_bytes);
		} else {
			table.push(['(b1) raster images', 'none', '-', fmt(budget.raster_image_max_bytes), 'ok']);
		}
		if (largest.path) row(`(b2) largest file (${largest.path})`, largest.size, null, budget.file_max_bytes);
		if (changes.has(lockPath) && changes.get(lockPath) !== 'D') {
			row(`(b2) ${lockPath}`, statSync(join(REPO_DIR, lockPath)).size, null, budget.file_max_bytes);
		}
		row(`(c) bytes added vs ${args.base}, excl. lockfile (${changes.size} paths)`, added, null, budget.diff_added_max_bytes);
		table.push([`(c) lockfile bytes added (reported separately)`, fmt(lockAdded), '-', '-', 'info']);

		// (e) svgo dry run: nothing is written back.
		for (const path of svgs) {
			const source = readFileSync(join(REPO_DIR, path), 'utf8');
			const optimised = optimize(source, { path, multipass: true }).data;
			const before = Buffer.byteLength(source);
			const saving = before ? ((before - Buffer.byteLength(optimised)) / before) * 100 : 0;
			const value = `${saving.toFixed(1)}%`;
			const limit = `${budget.svg_max_saving_percent}%`;
			if (brandVerbatim.has(path)) {
				table.push([`(e) svgo ${path} (brand verbatim)`, value, '-', '-', 'info']);
			} else if (saving >= budget.svg_max_saving_percent) {
				table.push([`(e) svgo ${path}`, value, '-', limit, 'FAIL']);
				failures.push(`(e) ${path}: svgo would save ${value}; run svgo on it and commit the result`);
			} else {
				table.push([`(e) svgo ${path}`, value, '-', limit, 'ok']);
			}
		}
		if (!svgs.length) table.push(['(e) svgo dry run', 'no SVGs added', '-', '-', 'ok']);
		for (const path of rasters) {
			failures.push(`(e) ${path}: raster image added. Use WebP or AVIF and optimise it manually (no raster tooling yet).`);
		}
		countRow('(e) raster images added', rasters.length);
	} else {
		console.log('::notice::V13 (a), (b), (c) and (e) skipped (--skip-diff)');
	}

	// (d) packed docs history.
	const dWarn = budget.docs_history_packed.warn_bytes;
	const dFail = budget.docs_history_packed.fail_bytes;
	if (args.historyUrl) {
		const dir = tempDir('history');
		run(tmpdir(), ['clone', '--quiet', '--bare', '--single-branch', '--branch', 'docs', args.historyUrl, dir]);
		row('(d) docs history, fresh single-branch clone', sizePack(dir), dWarn, dFail);
		notes.push(`(d) measured a fresh \`git clone --bare --single-branch --branch docs ${args.historyUrl}\`.`);
	} else {
		const dir = tempDir('history');
		run(tmpdir(), ['init', '--quiet', '--bare', dir]);
		bare(dir, ['-c', 'fetch.unpackLimit=1', 'fetch', '--quiet', '--no-tags', REPO_DIR, 'HEAD:refs/heads/stand-in']);
		row('(d) HEAD history (stand-in for a docs clone)', sizePack(dir), dWarn, dFail);
		notes.push('(d) measured the history of this checkout\'s HEAD, fetched into a temp bare repository, as the stand-in for a fresh docs clone.');
		// Projection: commit the working tree in the temp repository only, then repack.
		const env = {
			...process.env,
			GIT_WORK_TREE: REPO_DIR,
			GIT_INDEX_FILE: join(dir, 'projection-index'),
			GIT_AUTHOR_NAME: 'size-check',
			GIT_AUTHOR_EMAIL: 'size-check@invalid',
			GIT_COMMITTER_NAME: 'size-check',
			GIT_COMMITTER_EMAIL: 'size-check@invalid',
		};
		const g = (...a) => run(REPO_DIR, ['--git-dir', dir, ...a], { env });
		g('read-tree', 'refs/heads/stand-in');
		g('add', '-A', '--', '.');
		const tree = g('write-tree').trim();
		if (tree !== g('rev-parse', 'refs/heads/stand-in^{tree}').trim()) {
			const commit = g('commit-tree', tree, '-p', 'refs/heads/stand-in', '-m', 'projection').trim();
			g('update-ref', 'refs/heads/stand-in', commit);
			bare(dir, ['repack', '-adq']);
			bare(dir, ['prune']);
			row('(d) projected HEAD history with uncommitted changes', sizePack(dir), dWarn, dFail);
		}
	}

	// (f) whole-repository consumer cost.
	if (args.mirrorUrl) {
		const dir = tempDir('mirror');
		run(tmpdir(), ['clone', '--quiet', '--mirror', args.mirrorUrl, dir]);
		const refs = bare(dir, ['for-each-ref', '--format=%(refname)']).split('\n').filter(Boolean);
		const pulls = refs.filter((r) => r.startsWith('refs/pull/')).length;
		row('(f) fresh mirror clone of the repository', sizePack(dir), budget.repo_mirror_packed.warn_bytes, budget.repo_mirror_packed.fail_bytes);
		notes.push(`(f) mirror of ${args.mirrorUrl}: ${refs.length} refs, of which ${pulls} are refs/pull/* that GitHub serves to --mirror clones.`);
	} else {
		table.push(['(f) mirror clone', 'skipped (no --mirror-url)', fmt(budget.repo_mirror_packed.warn_bytes), fmt(budget.repo_mirror_packed.fail_bytes), '-']);
	}
} finally {
	cleanup();
}

console.log(`V13 size budget (status: ${budget.status})`);
const header = ['measure', 'value', 'warn', 'fail', 'result'];
const widths = header.map((_, i) => Math.max(...[header, ...table].map((r) => r[i].length)));
for (const r of [header, ...table]) {
	console.log(`  ${r.map((c, i) => (i === 0 ? c.padEnd(widths[i]) : c.padStart(widths[i]))).join('  ')}`);
}
for (const n of notes) console.log(`  note: ${n}`);
for (const w of warnings) console.log(`::warning::V13 ${w}`);
if (failures.length) {
	console.log(`V13 FAIL: ${failures.length} problem(s):`);
	for (const f of failures) console.log(`  ${f}`);
	process.exit(1);
}
console.log('V13 check-size: OK');
