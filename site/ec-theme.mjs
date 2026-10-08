// Expressive Code themes for the Atlas docs site.
// Colours are read at build time from the verbatim atlas-style tokens file, so code blocks
// can never drift from the brand. Two-tone: text for most tokens, accent for the one thing
// to notice (keywords, functions, property names, tags), muted for comments and punctuation.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { ExpressiveCodeTheme } from '@astrojs/starlight/expressive-code';

const TOKENS_URL = new URL('./src/styles/atlas-tokens.css', import.meta.url);
const TOKENS_PATH = fileURLToPath(TOKENS_URL);
const REQUIRED_ROLES = ['surface', 'text', 'text-muted', 'accent', 'danger', 'success'];

/** Read the --color-* roles of the top-level rule whose selector list contains `selector`. */
function readRoles(css, selector) {
	const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
	for (const m of clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
		const selectors = m[1].split(',').map((s) => s.trim());
		if (!selectors.includes(selector)) continue;
		const roles = Object.fromEntries(
			[...m[2].matchAll(/--color-([a-z-]+)\s*:\s*(#[0-9a-f]{6})\s*;/gi)].map((r) => [r[1], r[2]]),
		);
		const missing = REQUIRED_ROLES.filter((role) => !roles[role]);
		if (missing.length) {
			throw new Error(
				`ec-theme: ${TOKENS_PATH} rule "${selector}" lacks hex values for ${missing.map((r) => `--color-${r}`).join(', ')}`,
			);
		}
		return roles;
	}
	throw new Error(`ec-theme: no rule for selector "${selector}" in ${TOKENS_PATH}`);
}

let tokensCss;
try {
	tokensCss = readFileSync(TOKENS_PATH, 'utf8');
} catch (err) {
	throw new Error(`ec-theme: cannot read the brand tokens at ${TOKENS_PATH}: ${err.message}`);
}

const atlasTheme = (name, type, c) =>
	new ExpressiveCodeTheme({
		name,
		type,
		colors: { 'editor.background': c.surface, 'editor.foreground': c.text },
		settings: [
			{ settings: { foreground: c.text } },
			{
				scope: ['comment', 'punctuation.definition.comment'],
				settings: { foreground: c['text-muted'], fontStyle: 'italic' },
			},
			{
				scope: [
					'keyword',
					'storage',
					'entity.name.function',
					'support.function',
					'support.type.property-name',
					'entity.name.tag',
				],
				settings: { foreground: c.accent },
			},
			{ scope: ['string', 'constant', 'variable'], settings: { foreground: c.text } },
			{ scope: ['punctuation', 'meta.brace', 'keyword.operator'], settings: { foreground: c['text-muted'] } },
			{
				scope: ['markup.deleted', 'punctuation.definition.deleted', 'invalid'],
				settings: { foreground: c.danger },
			},
			{ scope: ['markup.inserted', 'punctuation.definition.inserted'], settings: { foreground: c.success } },
		],
	});

/** Expressive Code options for Starlight's `expressiveCode` setting. */
export const atlasExpressiveCode = {
	themes: [
		atlasTheme('atlas-dark', 'dark', readRoles(tokensCss, '[data-theme="dark"]')),
		atlasTheme('atlas-light', 'light', readRoles(tokensCss, ':root')),
	],
	// The token colours already meet WCAG AA (4.5:1) on the code surface; keep them exact.
	minSyntaxHighlightingColorContrast: 4.5,
	defaultProps: { frame: 'code' },
	styleOverrides: {
		borderRadius: 'var(--radius-md)',
		borderColor: 'var(--color-border)',
		codeFontFamily: 'var(--font-mono)',
		codeFontSize: 'var(--text-mono)',
		codeLineHeight: 'var(--leading-small)',
		uiFontFamily: 'var(--font-sans)',
		focusBorder: 'var(--color-focus-ring)',
		scrollbarThumbColor: 'var(--color-border)',
		scrollbarThumbHoverColor: 'var(--color-text-muted)',
		frames: {
			editorBackground: 'var(--color-surface)',
			terminalBackground: 'var(--color-surface)',
			editorTabBarBackground: 'var(--color-surface)',
			editorActiveTabBackground: 'var(--color-surface)',
			editorActiveTabForeground: 'var(--color-text-muted)',
			editorActiveTabIndicatorTopColor: 'var(--color-accent)',
			editorTabBarBorderBottomColor: 'var(--color-border)',
			terminalTitlebarBackground: 'var(--color-surface)',
			terminalTitlebarForeground: 'var(--color-text-muted)',
			terminalTitlebarBorderBottomColor: 'var(--color-border)',
			terminalTitlebarDotsForeground: 'var(--color-border)',
			inlineButtonForeground: 'var(--color-text-muted)',
			inlineButtonBorder: 'var(--color-border)',
			tooltipSuccessBackground: 'var(--color-success)',
			tooltipSuccessForeground: 'var(--color-surface)',
			frameBoxShadowCssValue: 'none',
		},
	},
};
