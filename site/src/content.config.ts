import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

const SOURCE_PATH = /^[A-Za-z0-9._-]+(\/[A-Za-z0-9._-]+)*$/;
const BLOB_SHA = /^[0-9a-f]{40}$/;
const TAG = /^v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$/;

/** Every page records the Atlas sources it was checked against (see site/README.md). */
const sourceFields = z.object({
	source: z.array(z.string().regex(SOURCE_PATH)).min(1),
	source_sha: z.record(z.string().regex(SOURCE_PATH), z.string().regex(BLOB_SHA)),
	source_tag: z.string().regex(TAG),
	generated: z.boolean().optional(),
});

const docsWithSources = docsSchema({ extend: sourceFields });

type SourceData = { source: string[]; source_sha: Record<string, string> };

/** source and source_sha must list the same paths. */
function sameSourcePaths(data: SourceData, ctx: z.RefinementCtx) {
	const listed = new Set(data.source);
	const hashed = new Set(Object.keys(data.source_sha));
	for (const path of listed) {
		if (!hashed.has(path)) {
			ctx.addIssue({ code: 'custom', path: ['source_sha'], message: `missing hash for ${path}` });
		}
	}
	for (const path of hashed) {
		if (!listed.has(path)) {
			ctx.addIssue({ code: 'custom', path: ['source_sha'], message: `${path} is not in source` });
		}
	}
}

export const collections = {
	docs: defineCollection({
		loader: docsLoader(),
		schema: (context) => docsWithSources(context).superRefine(sameSourcePaths),
	}),
};
