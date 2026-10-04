---
name: atlas/paths/prune
description: After KVA terminate, drop named failed-path pages from tip onto one summary. History stays on relates_to.ref.
path_id: prune
---

# Path: prune

## When

The user wants a failed frame off tip after an explicit KVA terminate, and the exit-reason page already exists. Discuss terminate does not delete. Do not enter this path from inside terminate. Do not enter it because a page mentions an old idea.

This is not supersede. Supersede replaces a living page. Prune drops a failed frame from the tip projection.

Provenance: atlas-atlas `decision-claim-b-tip-summary-git-history.md` and the pins it records.

## Enter

Mount first when this turn has not already set `root`. Then:

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: atlas | <project>
path: prune
path_module: references/paths/prune.md
intent: <one line>
root: <atlas store root>
summary: <tip summary path>
drop: <named exclusive-to-frame paths>
rev: <pre-prune git rev>
kind: <caller-supplied kind>
```

Read this file before `atlas ref prune`. Missing `summary`, `drop`, `rev`, or `kind` means incomplete Enter. Ask and stop. Do not invent `kind`. The pin's example is `derived_from`; pass it only when the caller chose it. Do not copy mount `ref` into `rev`. Do not walk links to discover more drop paths.

## Procedure

1. **Root** is the mounted store. No git repository: stop. If terminate has not produced the exit-reason page, stop and use discuss path `terminate`. Do not prune first.
2. **Rev must already hold every drop path, and the resolved commit must be an ancestor of the current tip.** HEAD itself is allowed. A descendant or an unrelated commit is not the pre-prune snapshot, even when the page bytes match. If the trial is uncommitted, commit that trial first, then use that SHA as `rev`. A branch name is allowed only because git can resolve it; prefer the SHA, because branch names move.
3. **One summary.** Write `summary` on tip: what happened, why it ended, how to walk back. Shared living pages stay. Multiverse shared-page cases stay open; the caller names the exclusive-to-frame set.
4. **Prune.** The tool does not commit.

   ```text
   python3 <atlas-skill>/scripts/atlas.py ref prune \
     --summary <summary> \
     --drop <path> \
     --ref <rev> \
     --kind <kind> \
     --root <root>
   ```

   Repeat `--drop` for each named path.    The command refuses a rev that is not an ancestor of HEAD, a rev that lacks a page blob, a summary that is itself in `--drop`, a path that escapes the store, a summary or drop that is not an eligible tip markdown page, a summary compile would reject before or after the retarget, including a blocking page-contract warning, a summary folder with no `index.md`, an invalid schema overlay, or a schema that fails shape, contract, or schema 2.0 checks, a summary or drop named `index.md` or `log.md`, an Atlas-managed path (`templates`, `staging`, `mesh`, `schema.d`, `.atlas-index`), a drop whose worktree bytes differ from the rev, a drop that is not a blob on tip, a drop absent from tip, a rewrite of a hard-linked page, an unsupported `relates_to` scalar that still names a drop, a page that changed before rewrite, a page replaced during rewrite, a page replaced before delete, a drop whose bytes change after it is claimed, a deletion that fails after the page is moved aside, a historical entry that is not a regular file, a non-UTF-8 page, and a rollback that would replace an existing path. It deletes only the named paths, retargets inbound tip `relates_to` and markdown links onto the summary with no `ref` and the existing kind kept, and keeps a link fragment or query on the summary URL.
5. **Compile** must be green before claiming tip exclusion:

   ```text
   python3 <atlas-skill>/scripts/atlas.py compile --root <root>
   ```

6. **Commit the prune** of the summary, the deletions, and the retargeted pages only. Do not commit unrelated dirty files. Default search no longer sees the dropped pages. Recover one with path **history**.

## Exit

- Named pages absent from tip, inbound tip links on the summary, summary `ref` edges at the resolved SHA, compile exit 0, and the caller has committed the summary, deletions, and retargeted pages. The prune command does not create that commit.
- Incomplete if the drop set was inferred, `kind` was invented, or compile is red.

## Non-goals

- Transitive closure of the failed graph.
- Shredding git history. Delete means tip plus default-search exclusion.
- Health measures for aggressive prune.
- Closing Claim A grain.
- Editing the discuss skill.
