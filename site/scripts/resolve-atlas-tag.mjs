#!/usr/bin/env node
// V0: resolve the Atlas release tag the site documents.
//
// Usage:
//   node scripts/resolve-atlas-tag.mjs [--tag vX.Y.Z[-pre]] [--remote <url|name>] [--main-ref <ref>]
//   node scripts/resolve-atlas-tag.mjs --self-test
//
// With --tag: validate the format and that the tag exists on the remote.
// Without: list refs/tags/v* on the remote, sort by SemVer (highest first) and pick
// the first tag whose commit is an ancestor of --main-ref (default origin/main).
// The caller fetches main beforehand (the CI workflow does this read-only).
// Prints the tag and commit, and appends to $GITHUB_OUTPUT / $GITHUB_STEP_SUMMARY when set.
import { execFileSync, spawnSync } from 'node:child_process';
import { appendFileSync } from 'node:fs';

const TAG_RE = /^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?$/;
const DEFAULT_REMOTE = 'https://github.com/sergio-sisternes-epam/atlas.git';

function parseArgs(argv) {
	const args = { tag: '', remote: DEFAULT_REMOTE, mainRef: 'origin/main', selfTest: false };
	for (let i = 0; i < argv.length; i += 1) {
		const a = argv[i];
		if (a === '--self-test') args.selfTest = true;
		else if (a === '--tag') args.tag = (argv[++i] ?? '').trim();
		else if (a === '--remote') args.remote = argv[++i];
		else if (a === '--main-ref') args.mainRef = argv[++i];
		else fail(`unknown argument ${a}`);
	}
	return args;
}

function fail(message) {
	console.error(`V0 FAIL: ${message}`);
	process.exit(1);
}

function parse(tag) {
	const m = TAG_RE.exec(tag);
	if (!m) return null;
	return { core: [m[1], m[2], m[3]].map(Number), pre: m[4] ? m[4].split('.') : [] };
}

function compareIdent(a, b) {
	const an = /^\d+$/.test(a);
	const bn = /^\d+$/.test(b);
	if (an && bn) return Number(a) - Number(b);
	if (an) return -1;
	if (bn) return 1;
	return a < b ? -1 : a > b ? 1 : 0;
}

/** SemVer 2.0.0 precedence (build metadata is not part of the accepted tag shape). */
export function compareSemver(x, y) {
	const a = parse(x);
	const b = parse(y);
	for (let i = 0; i < 3; i += 1) if (a.core[i] !== b.core[i]) return a.core[i] - b.core[i];
	if (!a.pre.length || !b.pre.length) return b.pre.length - a.pre.length;
	for (let i = 0; i < Math.min(a.pre.length, b.pre.length); i += 1) {
		const c = compareIdent(a.pre[i], b.pre[i]);
		if (c) return c;
	}
	return a.pre.length - b.pre.length;
}

function selfTest() {
	const expected = [
		'v0.9.0',
		'v0.12.1',
		'v0.13.0-alpha',
		'v0.13.0-beta',
		'v0.13.0-beta.2',
		'v0.13.0-beta.3',
		'v0.13.0-beta.10',
		'v0.13.0-beta.12',
		'v0.13.0-beta.13',
		'v0.13.0-rc.1',
		'v0.13.0',
		'v0.13.1',
		'v1.0.0',
	];
	const shuffled = [...expected].reverse();
	shuffled.push(shuffled.shift());
	const sorted = [...shuffled].sort(compareSemver);
	const bad = ['main', 'v1.2', 'v1.2.3-', 'v1.2.3+build', '1.2.3', 'v01.2.3x'].filter((t) => parse(t));
	if (JSON.stringify(sorted) !== JSON.stringify(expected) || bad.length) {
		console.error('expected:', expected.join(' < '));
		console.error('got:     ', sorted.join(' < '));
		if (bad.length) console.error('accepted invalid tags:', bad.join(', '));
		fail('SemVer self-test failed');
	}
	console.log(`V0 self-test: OK (${expected.join(' < ')})`);
}

function lsRemoteTags(remote, pattern) {
	const out = execFileSync('git', ['ls-remote', '--tags', remote, pattern, `${pattern}^{}`], { encoding: 'utf8' });
	const tags = new Map();
	for (const line of out.split('\n')) {
		const [sha, ref] = line.trim().split(/\s+/);
		if (!sha || !ref?.startsWith('refs/tags/')) continue;
		const peeled = ref.endsWith('^{}');
		const name = ref.slice('refs/tags/'.length).replace(/\^\{\}$/, '');
		// Annotated tags list the tag object and a peeled ^{} line; keep the commit.
		if (peeled || !tags.has(name)) tags.set(name, sha);
	}
	return tags;
}

function isAncestor(commit, mainRef) {
	const r = spawnSync('git', ['merge-base', '--is-ancestor', commit, mainRef], { stdio: 'ignore' });
	return r.status === 0;
}

function report(tag, commit) {
	console.log(`tag=${tag}`);
	console.log(`commit=${commit}`);
	if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, `tag=${tag}\ncommit=${commit}\n`);
	if (process.env.GITHUB_STEP_SUMMARY) {
		appendFileSync(process.env.GITHUB_STEP_SUMMARY, `### Atlas tag\n\n- Tag: \`${tag}\`\n- Commit: \`${commit}\`\n`);
	}
}

const args = parseArgs(process.argv.slice(2));
if (args.selfTest) {
	selfTest();
	process.exit(0);
}

if (args.tag) {
	if (!parse(args.tag)) fail(`tag ${JSON.stringify(args.tag)} does not match ${TAG_RE.source}`);
	const tags = lsRemoteTags(args.remote, `refs/tags/${args.tag}`);
	const commit = tags.get(args.tag);
	if (!commit) fail(`tag ${args.tag} does not exist on the remote`);
	report(args.tag, commit);
	process.exit(0);
}

const candidates = [...lsRemoteTags(args.remote, 'refs/tags/v*')]
	.filter(([name]) => parse(name))
	.sort(([a], [b]) => compareSemver(b, a));
if (!candidates.length) fail('no release tags (v*) found on the remote');
const verify = spawnSync('git', ['rev-parse', '--verify', '--quiet', `${args.mainRef}^{commit}`], { stdio: 'ignore' });
if (verify.status !== 0) fail(`${args.mainRef} is not available locally; fetch main first`);
const pick = candidates.find(([, commit]) => isAncestor(commit, args.mainRef));
if (!pick) fail(`no release tag is an ancestor of ${args.mainRef}`);
report(pick[0], pick[1]);
