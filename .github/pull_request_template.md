## Summary

<!-- What does this change, and which Atlas tag does it document? -->

## Checklist

- [ ] The base branch is `docs` (never `main`).
- [ ] Sources only: no `dist/`, `.astro/`, `node_modules/`, archives, video or heavy binaries. Images are SVG.
- [ ] Every changed page still matches its sources, and `source` / `source_sha` / `source_tag` are updated (generated pages: re-ran `generate.py`).
- [ ] No links to Microsoft-owned or Microsoft-branded domains.
- [ ] No hostnames, IP addresses, secrets, tokens, usernames or personal data; placeholders only.
- [ ] CLI examples use `python3 <atlas-skill>/scripts/atlas.py ...`; install examples use the marketplace or a pinned release tag.
- [ ] `npm run check:source`, `npm run build` and `npm run check:dist` pass locally.
