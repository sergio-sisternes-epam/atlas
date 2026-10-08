// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

/** DOCS_PREVIEW=1 marks a build as an unpublished preview (noindex + visible banner). */
const preview = process.env.DOCS_PREVIEW === '1';

export default defineConfig({
	site: 'https://sergio-sisternes-epam.github.io',
	base: '/atlas',
	trailingSlash: 'always',
	telemetry: false,
	vite: {
		define: {
			__DOCS_PREVIEW__: JSON.stringify(preview),
		},
	},
	integrations: [
		starlight({
			title: 'Atlas',
			description:
				'Documentation for Atlas, a distributed Semantic Knowledge Network built on git and markdown.',
			logo: {
				light: './src/assets/atlas-mark.svg',
				dark: './src/assets/atlas-mark-on-dark.svg',
				alt: 'Atlas',
			},
			favicon: '/favicon.svg',
			defaultLocale: 'root',
			locales: {
				root: { label: 'English', lang: 'en-GB' },
			},
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/sergio-sisternes-epam/atlas' },
			],
			customCss: ['./src/styles/atlas-tokens.css', './src/styles/starlight-atlas.css'],
			lastUpdated: false,
			credits: false,
			head: preview
				? [{ tag: 'meta', attrs: { name: 'robots', content: 'noindex, nofollow' } }]
				: [],
			components: {
				ThemeProvider: './src/components/ThemeProvider.astro',
				ThemeSelect: './src/components/ThemeSelect.astro',
				SiteTitle: './src/components/SiteTitle.astro',
				Footer: './src/components/Footer.astro',
				Banner: './src/components/Banner.astro',
			},
			sidebar: [
				{
					label: 'Start',
					items: [
						{ label: 'What is Atlas?', slug: 'start/what-is-atlas' },
						{ label: 'Install', slug: 'start/install' },
						{ label: 'First journey', slug: 'start/first-journey' },
						{ label: 'Choose storage', slug: 'start/choose-storage' },
					],
				},
				{
					label: 'Modules',
					items: [{ autogenerate: { directory: 'modules' } }],
				},
				{
					label: 'Reference',
					items: [
						{
							label: 'CLI',
							items: [{ autogenerate: { directory: 'reference/cli' } }],
						},
					],
				},
				{
					label: 'Project',
					items: [
						{ label: 'Changelog', slug: 'project/changelog' },
						{ label: 'Contributing', slug: 'project/contributing' },
						{ label: 'Security', slug: 'project/security' },
						{ label: 'Licence', slug: 'project/licence' },
						{ label: 'Related projects', slug: 'project/related-projects' },
					],
				},
			],
		}),
	],
});
