# Strip Cartograph

This add-on is optional. Deleting it must not break compile, search, migrate, or promote.

The Build host must **import** this folder, not keep a second copy of Atlas code.

## Delete

1. Remove `addons/cartograph/`
2. Remove `references/modules/cartograph.md`
3. In `SKILL.md`, delete the **Cartograph (Build only)** section and the `view` CLI row
4. Remove `scripts/atlas_cli/commands/view.py` and its registration in `cli.py`
5. In the host Build app, remove:
   - import of `CartographApp` from `@atlas/cartograph`
   - tsconfig path `@atlas/cartograph`
   - vite alias `@atlas/cartograph`

Do **not** touch `atlas_cli` validate/search/migrate/promote, SCHEMA, or store files.
