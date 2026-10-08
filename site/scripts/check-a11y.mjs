#!/usr/bin/env node
// V10: axe-core accessibility scan of every built page, in light and dark themes.
// Serves site/dist under the /atlas/ base, loads each page in Playwright Chromium with
// localStorage['atlas-style-theme'] preset, and fails on any serious or critical violation.
// Uses PLAYWRIGHT_CHROMIUM_EXECUTABLE when set, otherwise Playwright's bundled Chromium.
// Writes a JSON report to site/test-reports/a11y.json (git-ignored).
import { createServer } from 'node:http';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import AxeBuilder from '@axe-core/playwright';
import { chromium } from 'playwright';
import { BASE, DIST_DIR, SITE_DIR, isFile, rel, requireDist, walk } from './lib.mjs';

requireDist();

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'];
const THEMES = ['light', 'dark'];
const BLOCKING = new Set(['serious', 'critical']);
const TYPES = {
	'.html': 'text/html; charset=utf-8',
	'.css': 'text/css; charset=utf-8',
	'.js': 'text/javascript; charset=utf-8',
	'.mjs': 'text/javascript; charset=utf-8',
	'.json': 'application/json',
	'.svg': 'image/svg+xml',
	'.xml': 'application/xml',
	'.txt': 'text/plain; charset=utf-8',
	'.wasm': 'application/wasm',
};

function resolveFile(pathname) {
	if (!pathname.startsWith(`${BASE}/`)) return null;
	let local = normalize(decodeURIComponent(pathname.slice(BASE.length)));
	if (local.includes('..')) return null;
	if (local.endsWith('/')) local += 'index.html';
	const full = join(DIST_DIR, local);
	if (isFile(full)) return full;
	if (isFile(join(full, 'index.html'))) return join(full, 'index.html');
	return null;
}

const server = createServer((req, res) => {
	const url = new URL(req.url, 'http://localhost');
	const file = resolveFile(url.pathname);
	if (!file) {
		res.writeHead(404, { 'content-type': TYPES['.html'] });
		res.end(isFile(join(DIST_DIR, '404.html')) ? readFileSync(join(DIST_DIR, '404.html')) : 'Not found');
		return;
	}
	res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' });
	res.end(readFileSync(file));
});
await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
const origin = `http://127.0.0.1:${server.address().port}`;

const pages = walk(DIST_DIR, { includeAll: true })
	.filter((f) => f.endsWith('.html'))
	.map((f) => `${BASE}/${rel(f, DIST_DIR)}`.replace(/index\.html$/, ''));

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;
let browser;
try {
	browser = await chromium.launch({ executablePath });
} catch (err) {
	server.close();
	console.error(`V10 FAIL: cannot launch Chromium${executablePath ? ` at ${executablePath}` : ''}: ${err.message.split('\n')[0]}`);
	process.exit(1);
}

const report = { tags: TAGS, chromium: browser.version(), pages: [] };
const blocking = [];
try {
	for (const theme of THEMES) {
		const context = await browser.newContext({ colorScheme: theme });
		await context.addInitScript((value) => {
			try {
				localStorage.setItem('atlas-style-theme', value);
			} catch {
				// storage unavailable
			}
		}, theme);
		const page = await context.newPage();
		for (const path of pages) {
			await page.goto(`${origin}${path}`, { waitUntil: 'load' });
			// Expressive Code's runtime script makes scrollable code blocks focusable after a short delay.
			await page.waitForFunction(
				() =>
					[...document.querySelectorAll('.expressive-code pre')].every(
						(pre) => pre.scrollWidth <= pre.clientWidth || pre.hasAttribute('tabindex'),
					),
				undefined,
				{ timeout: 10000 },
			).catch(() => blocking.push(`${path} [${theme}]: scrollable code blocks did not become focusable`));
			const applied = await page.evaluate(() => document.documentElement.dataset.theme);
			if (applied !== theme) blocking.push(`${path} [${theme}]: data-theme is ${applied}, expected ${theme}`);
			const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
			const violations = result.violations.map((v) => ({
				id: v.id,
				impact: v.impact,
				help: v.help,
				nodes: v.nodes.map((n) => n.target.join(' ')),
			}));
			report.pages.push({ path, theme, violations, passes: result.passes.length });
			for (const v of violations.filter((x) => BLOCKING.has(x.impact))) {
				blocking.push(`${path} [${theme}]: ${v.impact} ${v.id} — ${v.help} (${v.nodes.slice(0, 3).join(', ')})`);
			}
		}
		await context.close();
	}
} finally {
	await browser.close();
	server.close();
}

const outDir = join(SITE_DIR, 'test-reports');
mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'a11y.json'), `${JSON.stringify(report, null, 2)}\n`);
const minor = report.pages.reduce((n, p) => n + p.violations.filter((v) => !BLOCKING.has(v.impact)).length, 0);

if (blocking.length) {
	console.log(`V10 FAIL: ${blocking.length} serious/critical problem(s):`);
	for (const b of blocking) console.log(`  ${b}`);
	console.log(`Report: ${rel(join(outDir, 'a11y.json'))}`);
	process.exit(1);
}
console.log(
	`V10 check-a11y: OK (${pages.length} pages × ${THEMES.length} themes, Chromium ${report.chromium}; ` +
		`${minor} moderate/minor finding(s) in ${rel(join(outDir, 'a11y.json'))})`,
);
