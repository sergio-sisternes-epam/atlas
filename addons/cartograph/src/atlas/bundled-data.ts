export type BundledAtlas = {
  id: string;
  title: string;
  schema: Record<string, unknown> | null;
  pages: Record<string, string>;
};

/** Snapshot of this skill's own Atlas stores (references/atlas + fixtures/mini-atlas). */
export const BUNDLED_ATLASES: Record<string, BundledAtlas> = {
  "skill-memory": {
    "id": "atlas-skill-memory",
    "title": "Atlas skill process memory",
    "schema": {
      "schema_version": "1.0",
      "atlas_id": "atlas-skill-memory",
      "title": "Atlas skill process memory",
      "description": "Design decisions, implement experiences, and operational memory for the Atlas skill itself.",
      "structure": {
        "free_layout": true,
        "staging_dir": "staging",
        "require_index_in_folders": true,
        "reserved_names": [
          "index.md",
          "log.md",
          "staging"
        ]
      },
      "compile": {
        "hard_fail": true,
        "allow_inline_ignores": true,
        "min_body_chars": 40,
        "core_checks": [
          "okf_compliance",
          "frontmatter",
          "internal_links",
          "not_just_links",
          "schema_present",
          "no_answerable_in_staging",
          "index_md_present"
        ],
        "simplicity_budget": {
          "max_required_frontmatter_keys_per_type": 8,
          "max_required_sections_per_type": 6
        }
      },
      "templates": {
        "directory": "templates/",
        "by_type": {
          "experience": {
            "file": "templates/experience.md",
            "frontmatter": {
              "required": [
                "type",
                "title",
                "created",
                "work_id"
              ],
              "recommended": [
                "description",
                "tags",
                "status"
              ]
            },
            "sections": {
              "required": [
                "Context",
                "What happened",
                "Outcome"
              ],
              "recommended": [
                "Related",
                "Follow-ups"
              ]
            }
          },
          "decision": {
            "file": "templates/decision.md",
            "frontmatter": {
              "required": [
                "type",
                "title",
                "created"
              ],
              "recommended": [
                "status",
                "work_id"
              ]
            },
            "sections": {
              "required": [
                "Decision",
                "Rationale"
              ],
              "recommended": [
                "Alternatives considered",
                "Consequences"
              ]
            }
          },
          "work": {
            "file": "templates/work.md",
            "frontmatter": {
              "required": [
                "type",
                "title",
                "created",
                "work_id"
              ],
              "recommended": [
                "status",
                "description"
              ]
            },
            "sections": {
              "required": [
                "Scope",
                "Status"
              ],
              "recommended": [
                "Outcomes",
                "Related"
              ]
            }
          }
        }
      },
      "query": {
        "default_mode": "local",
        "search_engine": "grep",
        "fallback": "rg",
        "staging_visible": false
      },
      "mesh": {
        "participates": true,
        "default_access": "read/write"
      },
      "types": {
        "recommended": [
          "experience",
          "decision",
          "lesson",
          "recipe",
          "work"
        ],
        "roles": {
          "experience": "episodic — session / phase / challenge that happened",
          "decision": "semantic — pinned choice",
          "lesson": "semantic — do X / avoid Y (optional; distilled from experiences)",
          "recipe": "procedural — reusable how-to",
          "work": "task hub — scope, status, and relates_to cluster for a work_id"
        },
        "notes": [
          "Types are recommendations, not a closed enum (OKF freedom).",
          "memory is not a page type; Atlas is the memory substrate."
        ]
      },
      "relations": {
        "how_to_link": [
          "AUTHORITATIVE: frontmatter relates_to: [{path, kind}] — used by visualisers, tools, and compile-time graph consumers.",
          "OPTIONAL: ## Related Markdown section may mirror relates_to for human reading of the body; agents should prefer frontmatter.",
          "path values are relative to the Atlas root (forward slashes).",
          "kind should be one of the recommended_kinds when possible.",
          "atlas compile checks that relates_to paths resolve (and Markdown links if present).",
          "On promote/compile, agent writes relates_to first; body Related is optional echo."
        ],
        "authoritative": "frontmatter",
        "recommended_kinds": [
          "follows",
          "records",
          "supersedes",
          "implements",
          "derived_from",
          "related"
        ],
        "kind_meanings": {
          "follows": "This item continues or comes after the target in a sequence (e.g. phase N follows phase N-1).",
          "records": "This item (usually a decision) captures the outcome of the target experience/session.",
          "supersedes": "This item replaces the target; prefer this over the target for current guidance.",
          "implements": "This item carries out the target plan, decision, or work_id scope.",
          "derived_from": "This item was distilled or extracted from the target.",
          "related": "Generic association when no tighter role fits."
        }
      }
    },
    "pages": {
      "decisions/atlas-name.md": "---\ntype: decision\ntitle: \"Successor name is Atlas\"\ncreated: 2026-08-23\nstatus: accepted\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Operational successor to okf-wiki is named Atlas.\"\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-atlas-name-pin.md\n    kind: records\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: implements\n  - path: decisions/type-vocabulary.md\n    kind: related\n---\n## Decision\n\nThe rebooted operational knowledge skill is named **Atlas**.\n\n## Rationale\n\nAtlas best signals compiled, modular, navigable knowledge for skills and projects without process theatre.\n\n## Alternatives considered\n\nCodex, library, archive, memory, and wiki-derived names were rejected for confusion or scope mismatch.\n\n## Consequences\n\nSkill package, CLI (`atlas`), and stores use this name; okf remains pure format authority.\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **records:** [2026-08-23-atlas-name-pin](../experiences/2026-08-23-atlas-name-pin.md)\n- **implements:** [2026-08-23-atlas-design-plan](../experiences/2026-08-23-atlas-design-plan.md)\n- **related:** [type-vocabulary](type-vocabulary.md)\n",
      "decisions/cartograph-fork-in-atlas.md": "---\ntype: decision\ntitle: \"Cartograph lives only in the Atlas skill\"\ncreated: 2026-08-23\nstatus: accepted\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"The star-map viewer is an Atlas-owned fork of okf-wiki graph-viewer. Hosts import it; they must not keep a second Atlas source tree.\"\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-cartograph-atlas-port.md\n    kind: records\n  - path: decisions/atlas-name.md\n    kind: related\n---\n\n## Decision\n\nCartograph source lives only under `atlas/addons/cartograph/`. It is a fork of `okf-wiki/addons/graph-viewer`, not a shared package. Grok Build hosts **import** `@atlas/cartograph`; they do not duplicate Atlas or viewer code.\n\n## Rationale\n\nA host copy drifts from the skill. Atlas owns `SCHEMA.json`, free layout, `relates_to`, and `atlas://`. okf-wiki's viewer remains the legacy wiki sky.\n\n## Alternatives considered\n\nKeeping the viewer only in okf-wiki and adapting at the host. Rejected: Atlas stores would keep looking like wikis.\n\nCopying Cartograph into each Build app. Rejected: two sources of truth.\n\n## Consequences\n\nStrip with `addons/cartograph/STRIP.md`. `atlas view` is Build-only. Compile, search, migrate, and promote do not depend on the add-on.\n\n## Related\n\n- **implements:** [Atlas reboot of okf-wiki](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **records:** [Cartograph ported into Atlas](../experiences/2026-08-23-cartograph-atlas-port.md)\n- **related:** [Successor name is Atlas](atlas-name.md)\n",
      "decisions/index.md": "# Decisions\n\n- [Successor name is Atlas](atlas-name.md)\n- [Type vocabulary (agentic roles)](type-vocabulary.md)\n- [Cartograph lives only in the Atlas skill](cartograph-fork-in-atlas.md)\n",
      "decisions/type-vocabulary.md": "---\ntype: decision\ntitle: \"Atlas recommended types align with agentic memory roles\"\ncreated: 2026-08-23\nstatus: accepted\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"experience=episodic, decision=semantic pin; lesson/recipe optional; memory is not a page type.\"\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-okf-wiki-design-challenge-karpathy-realign.md\n    kind: derived_from\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: implements\n  - path: decisions/atlas-name.md\n    kind: related\n---\n## Decision\n\nRecommended SCHEMA types are `experience`, `decision`, `lesson`, and `recipe`. Atlas is the memory substrate; pages are not typed `memory`.\n\n## Rationale\n\nMatches AI agent episodic / semantic / procedural vocabulary while keeping human-friendly names and existing templates.\n\n## Alternatives considered\n\nUsing `memory` as a page type, or renaming experience to mean distillation, was rejected after think-challenge against cognitive science and agent-memory literature.\n\n## Consequences\n\nOpening-test promotes use experience for sessions and decision for pins; lesson/recipe templates deferred until needed.\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **derived_from:** [2026-08-23-okf-wiki-design-challenge-karpathy-realign](../experiences/2026-08-23-okf-wiki-design-challenge-karpathy-realign.md)\n- **implements:** [2026-08-23-atlas-design-plan](../experiences/2026-08-23-atlas-design-plan.md)\n- **related:** [atlas-name](atlas-name.md)\n",
      "experiences/2026-08-23-atlas-design-plan.md": "---\ntype: experience\ntitle: \"Atlas design plan approved and persisted\"\ncreated: 2026-08-23\nstatus: done\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Formal Autogenesis design plan for Atlas reboot of okf-wiki; approved after think-challenge.\"\ntags:\n  - design\n  - atlas\n  - plan\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-okf-wiki-design-challenge-karpathy-realign.md\n    kind: derived_from\n  - path: decisions/atlas-name.md\n    kind: related\n  - path: decisions/type-vocabulary.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase1.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase6.md\n    kind: related\n  - path: experiences/2026-08-23-construct-adversarial-green.md\n    kind: related\n---\n## Context\n\nDesign path for the okf-wiki operational reboot produced a formal plan with Genesis Artifacts, pins, and adversarial draft.\n\n## What happened\n\nThe plan was persisted, challenged, adjusted (BM25 pilot grep, staging migration mode, simplicity budget, answerability), and explicitly approved. Implementation phases 1–6 followed that plan.\n\n## Outcome\n\nAtlas exists as skill + CLI + opening-test store. Plan path remains the design source of truth.\n\n\n## Follow-ups\n\nLive okf-wiki migration and BM25 index remain deferred.\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **derived_from:** [2026-08-23-okf-wiki-design-challenge-karpathy-realign](2026-08-23-okf-wiki-design-challenge-karpathy-realign.md)\n- **related:** [atlas-name](../decisions/atlas-name.md)\n- **related:** [type-vocabulary](../decisions/type-vocabulary.md)\n- **related:** [2026-08-23-implement-atlas-phase1](2026-08-23-implement-atlas-phase1.md)\n- **related:** [2026-08-23-implement-atlas-phase6](2026-08-23-implement-atlas-phase6.md)\n- **related:** [2026-08-23-construct-adversarial-green](2026-08-23-construct-adversarial-green.md)\n",
      "experiences/2026-08-23-atlas-name-pin.md": "---\ntype: experience\ntitle: \"2026-08-23 pin: Atlas as the rebooted skill name\"\ncreated: 2026-08-23\nstatus: raw\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Pinned decision: the successor to okf-wiki is named Atlas. Captures compiled, modular, navigable knowledge for skills and projects.\"\ntags: \"[memory, design, pin, naming, atlas, work_id]\"\norigin: internal\nsensitivity: internal\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: decisions/atlas-name.md\n    kind: related\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: related\n---\n# 2026-08-23 pin: Atlas\n\n## Decision\n\nThe rebooted skill that succeeds `okf-wiki` is named **Atlas**.\n\n## Rationale (from session)\n\nAtlas was selected after evaluating:\n\n- Codex (strong on compiled source-of-truth, weak on modularity, mild OpenAI collision)\n- Memory (too narrow and overused)\n- Library (clear but plain)\n- Archive, Vault, Garden, Lattice, Nexus, Tome, Summa, etc.\n\nAtlas best holds the intersection of:\n\n- compiled / authoritative knowledge (Codex strength)\n- modular, navigable structure (graph / progressive disclosure)\n- breadth beyond pure memory (experiences + designs + recipes + requirements + project knowledge)\n\n## Scope the name is intended to cover\n\n- Skill long-term memory and operational recipes (autogenesis and other skills)\n- Project knowledge graphs (requirements, design decisions, system understanding) as single source of truth\n- Durable, OKF-conformant, modular knowledge substrate\n\n\n## Status\n\nName pinned. Design path remains open; formal plan and remaining pins still to be completed and approved. No implementation in this turn.\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **related:** [atlas-name](../decisions/atlas-name.md)\n- **related:** [2026-08-23-atlas-design-plan](2026-08-23-atlas-design-plan.md)\n",
      "experiences/2026-08-23-cartograph-atlas-port.md": "---\ntype: experience\ntitle: \"Cartograph ported into Atlas as Build viewer\"\ncreated: 2026-08-23\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\nstatus: done\ndescription: \"Forked okf-wiki graph-viewer into atlas/addons/cartograph; Atlas-native scan, skill-only source, crawl, welcome gate, hyperspace arrival.\"\ntags:\n  - cartograph\n  - viewer\n  - port\n  - build\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: decisions/cartograph-fork-in-atlas.md\n    kind: records\n  - path: decisions/atlas-name.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase6.md\n    kind: follows\n---\n\n## Context\n\nokf-wiki shipped an optional Grok Build star-map (`addons/graph-viewer`). Atlas needed the same sky without remaining bound to `knowledge/` · `SCHEMA.md` folders, and without a second copy of Atlas code in the host app.\n\n## What happened\n\nThe viewer was forked into `addons/cartograph/` (not a shared module). Scan now detects `SCHEMA.json`, walks free layout (skipping `staging/` · `templates/` · `mesh/`), treats `relates_to` as authoritative edges, and resolves `atlas://` mesh links. Legacy okf-wiki stores still open.\n\nThe Build host imports `@atlas/cartograph` from the skill (symlink, not a copy). Opening sequence is crawl → welcome list of Atlas-compatible skills → hyperspace drop into the chosen galaxy. `atlas view --root` points the preview at a store.\n\n## Outcome\n\nCartograph is Atlas-owned. Skill process memory and fixtures render as the live sky. Wiki-compatible skills remain selectable. Compile/search/migrate are unchanged; the add-on stays optional (`STRIP.md`).\n\n## Related\n\n- **implements:** [Atlas reboot of okf-wiki](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **records:** [Cartograph lives only in the Atlas skill](../decisions/cartograph-fork-in-atlas.md)\n- **related:** [Successor name is Atlas](../decisions/atlas-name.md)\n- **follows:** [Implement phase 6](2026-08-23-implement-atlas-phase6.md)\n\n## Follow-ups\n\nKeep bundled snapshots of this Atlas in sync when process memory changes. Do not re-copy viewer source into host apps.\n",
      "experiences/2026-08-23-construct-adversarial-green.md": "---\ntype: experience\ntitle: \"Construct adversarial report green for Atlas CLI\"\ncreated: 2026-08-23\nstatus: done\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Phase 6 adversarial smokes: 8 green, 0 red, 2 deferred out of scope.\"\ntags:\n  - construct\n  - atlas\n  - evaluation\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-implement-atlas-phase6.md\n    kind: follows\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: implements\n---\n## Context\n\nImplement path required adversarial construct evaluation for the Atlas new-surface work.\n\n## What happened\n\nSmokes from `atlas-reboot-adversarial-v1.yaml` were executed against the Python Atlas CLI (validate, search, migrate, promote, mesh).\n\n## Outcome\n\nconstruct_eval **green**. Deferred only: relative-index-portable (BM25 not in scope) and answerability-concrete (no live migration cut-over yet).\n\n\n## Follow-ups\n\nRe-run suite when BM25 and live migration land.\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **follows:** [2026-08-23-implement-atlas-phase6](2026-08-23-implement-atlas-phase6.md)\n- **implements:** [2026-08-23-atlas-design-plan](2026-08-23-atlas-design-plan.md)\n",
      "experiences/2026-08-23-implement-atlas-phase1.md": "---\ntype: experience\ntitle: \"2026-08-23 implement Phase 1: Atlas foundation (skill skeleton, scenario, SCHEMA contract)\"\ncreated: 2026-08-23\nstatus: raw\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Phase 1 implement of approved Atlas design plan — adversarial scenario materialised, atlas skill skeleton, SCHEMA contract shape.\"\ntags: \"[memory, implement, atlas, work_id]\"\norigin: internal\nsensitivity: internal\nimplements: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\nplan_path: /home/workdir/artifacts/autogenesis-plans/2026-08-23-atlas-reboot-okf-wiki-v1.md\nconstruct_eval: deferred\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: implements\n  - path: experiences/2026-08-23-okf-wiki-design-challenge-karpathy-realign.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase2.md\n    kind: related\n---\n# 2026-08-23 implement Phase 1: Atlas foundation\n\n## Context\n\nDesign plan approved after think-challenge. User directed proceed with implementation. Change-class new-surface; full Rust CLI out of single-slice scope.\n\n## What was implemented (Phase 1)\n\n### Changed files\n\n- `artifacts/autogenesis-plans/2026-08-23-atlas-reboot-okf-wiki-v1.md` — status approved + accepted challenge deltas\n- `okf-wiki/references/scenarios/atlas-reboot-adversarial-v1.yaml` — materialised adversarial draft including challenge smokes\n- `atlas/SKILL.md` — successor skill skeleton (contract, CLI target surface, routing to okf, activation cards)\n- `atlas/references/SCHEMA.contract.json` — machine contract shape for per-Atlas SCHEMA.json including simplicity budget\n\n### Explicitly deferred (not in this slice)\n\n- Rust `atlas` binary / BM25 implementation\n- Live migration of production okf-wiki store content\n- Mesh runtime fan-out\n- Construct evaluation run (deferred until CLI exists to exercise smokes)\n\n## Outcome\n\nPhase 1 foundation in place. Skill name **Atlas** is now a real skill entry with pinned contracts. Further implement slices must stay within approved plan scope and re-enter implement path as needed.\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **implements:** [2026-08-23-atlas-design-plan](2026-08-23-atlas-design-plan.md)\n- **related:** [2026-08-23-okf-wiki-design-challenge-karpathy-realign](2026-08-23-okf-wiki-design-challenge-karpathy-realign.md)\n- **related:** [2026-08-23-implement-atlas-phase2](2026-08-23-implement-atlas-phase2.md)\n",
      "experiences/2026-08-23-implement-atlas-phase2.md": "---\ntype: experience\ntitle: \"2026-08-23 implement Phase 2: atlas validate/compile Python CLI\"\ncreated: 2026-08-23\nstatus: raw\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Phase 2 — agent-cli layout prototype: SCHEMA gate, staging-empty hard fail, not-just-links, default templates, mini-atlas fixture smokes green.\"\ntags: \"[memory, implement, atlas, cli, work_id]\"\norigin: internal\nsensitivity: internal\nimplements: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\nplan_path: /home/workdir/artifacts/autogenesis-plans/2026-08-23-atlas-reboot-okf-wiki-v1.md\nconstruct_eval: deferred\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: implements\n  - path: experiences/2026-08-23-implement-atlas-phase1.md\n    kind: follows\n---\n# 2026-08-23 implement Phase 2: atlas validate/compile CLI\n\n## Context\n\nPhase 1 delivered skill skeleton, adversarial scenario, SCHEMA contract. Phase 2 builds the first deterministic gate agents can call.\n\n## What was implemented\n\n### Changed files\n\n- `atlas/scripts/atlas.py` — shim entrypoint\n- `atlas/scripts/atlas_cli/` — agent-cli layout (`cli.py`, `commands/validate.py`, `core/{paths,frontmatter,schema}.py`)\n- `atlas/references/templates/experience.md` — default template with frontmatter rules copy\n- `atlas/references/templates/decision.md` — default template\n- `atlas/fixtures/mini-atlas/` — SCHEMA.json, indexes, sample decision + experience\n- `atlas/SKILL.md` — version 0.2.0-phase2, CLI usage note\n\n### Smokes exercised\n\n| Smoke | Result |\n|-------|--------|\n| Clean mini-atlas validate | exit 0 |\n| Non-empty staging | exit 2, `no_answerable_in_staging` |\n| Thin link-list page | exit 2, `not_just_links` |\n| Missing SCHEMA.json | exit 2, `schema_present` |\n\n### Deferred\n\n- BM25 search / Rust binary\n- mesh consolidation in compile\n- atlas migrate / promote commands\n- construct adversarial run (still deferred until more of CLI surface exists)\n- section-level template enforcement (frontmatter simplicity budget is read; section body checks not yet)\n\n## Outcome\n\nAgents can run:\n\n```bash\npython3 /home/workdir/.grok/skills/atlas/scripts/atlas.py validate --root <atlas>\npython3 /home/workdir/.grok/skills/atlas/scripts/atlas.py compile --root <atlas>\n```\n\nCompile stays red while staging has files — matching the approved Structure + Compile pins.\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **implements:** [2026-08-23-atlas-design-plan](2026-08-23-atlas-design-plan.md)\n- **follows:** [2026-08-23-implement-atlas-phase1](2026-08-23-implement-atlas-phase1.md)\n",
      "experiences/2026-08-23-implement-atlas-phase3.md": "---\ntype: experience\ntitle: \"2026-08-23 implement Phase 3: atlas search (grep pilot + bm25 flag)\"\ncreated: 2026-08-23\nstatus: raw\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Phase 3 — atlas search with SCHEMA query.search_engine grep|bm25; pilot default grep; agentic guidance; bm25 falls back with WARNING.\"\ntags: \"[memory, implement, atlas, search, work_id]\"\norigin: internal\nsensitivity: internal\nimplements: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\nplan_path: /home/workdir/artifacts/autogenesis-plans/2026-08-23-atlas-reboot-okf-wiki-v1.md\nconstruct_eval: deferred\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: implements\n  - path: experiences/2026-08-23-implement-atlas-phase2.md\n    kind: follows\n---\n# 2026-08-23 implement Phase 3: atlas search\n\n## Context\n\nUser directed Phase 3 with a pilot change: grep search is approved under configuration; BM25 later. When mode is grep, CLI must instruct standard agentic search patterns.\n\n## What was implemented\n\n### Changed files\n\n- `atlas/scripts/atlas_cli/commands/search.py` — ranked grep search + bm25 stub/fallback + agentic guidance\n- `atlas/scripts/atlas_cli/cli.py` — `search` subcommand (`--engine`, `--limit`, `--json`)\n- `atlas/fixtures/mini-atlas/SCHEMA.json` — `query.search_engine: grep`\n- `atlas/references/SCHEMA.contract.json` — pilot default grep\n- `atlas/SKILL.md` — v0.3.0-phase3, search contract updated\n\n### Behaviour\n\n| Config | CLI behaviour |\n|--------|----------------|\n| `search_engine: grep` (default) | Ranked full-text over concept pages; prints agentic guidance |\n| `search_engine: bm25` or `--engine bm25` | If no index/engine → WARNING + grep fallback + guidance |\n| Agent unbounded tree grep | Still forbidden; use `atlas search` |\n\n### Smokes\n\n- `atlas search \"Atlas naming\"` → ranked hits including decisions/naming.md\n- `--engine bm25` without index → WARNING + grep fallback\n- `--json` includes `agentic_guidance` when engine_used is grep\n\n## Deferred\n\n- Real BM25 index build / query\n- migrate, promote, mesh consolidate\n- construct adversarial run\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **implements:** [2026-08-23-atlas-design-plan](2026-08-23-atlas-design-plan.md)\n- **follows:** [2026-08-23-implement-atlas-phase2](2026-08-23-implement-atlas-phase2.md)\n",
      "experiences/2026-08-23-implement-atlas-phase4.md": "---\ntype: experience\ntitle: \"2026-08-23 implement Phase 4: atlas migrate + promote\"\ncreated: 2026-08-23\nstatus: raw\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Phase 4 — migrate copies into staging only; promote scaffolds from template and clears staging; compile fails on thin scaffolds until agent writes claims.\"\ntags: \"[memory, implement, atlas, migrate, promote, work_id]\"\norigin: internal\nsensitivity: internal\nimplements: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\nplan_path: /home/workdir/artifacts/autogenesis-plans/2026-08-23-atlas-reboot-okf-wiki-v1.md\nconstruct_eval: deferred\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: implements\n  - path: experiences/2026-08-23-implement-atlas-phase3.md\n    kind: follows\n---\n# 2026-08-23 implement Phase 4: migrate + promote\n\n## Context\n\nMigration pin required an explicit path for external/old content into staging, and a optional promote helper that only scaffolds.\n\n## What was implemented\n\n### Changed files\n\n- `atlas/scripts/atlas_cli/commands/migrate.py`\n- `atlas/scripts/atlas_cli/commands/promote.py`\n- `atlas/scripts/atlas_cli/cli.py` — wired `migrate` and `promote`\n- `atlas/scripts/atlas_cli/core/frontmatter.py` — strip HTML comments in not-just-links heuristic\n- `atlas/SKILL.md` — v0.4.0-phase4\n- Fixture gained `decisions/mesh-access.md` as a completed example from the smoke path\n\n### Behaviour\n\n```text\natlas migrate <source> [--into staging/]\n  → copy into staging + provenance sidecar\n  → atlas compile FAILS (staging non-empty)\n\natlas promote <staging-file> --to <target> [--type decision]\n  → template skeleton, index stub, remove staging file\n  → prints agent checklist\n  → atlas compile FAILS while body is thin (not_just_links)\n\nagent writes claims + links\n  → atlas compile GREEN\n```\n\n### Smokes\n\n| Step | Result |\n|------|--------|\n| migrate rough file | staging has file; compile exit 2 |\n| promote to decisions/… | scaffold + checklist; staging cleared |\n| thin scaffold | compile exit 2 `not_just_links` |\n| agent-completed page | compile exit 0 |\n\n## Deferred\n\n- BM25 engine, mesh consolidate, construct eval, live okf-wiki store migration\n\n\n## Exit criterion: Click migration (same session)\n\n- `atlas_cli/cli.py` rewired from argparse to **Click** (microsoft/apm-aligned).\n- `commands/` and `core/` unchanged (`run()` contract preserved).\n- Regression: validate, search, migrate, promote help + fixture compile green.\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **implements:** [2026-08-23-atlas-design-plan](2026-08-23-atlas-design-plan.md)\n- **follows:** [2026-08-23-implement-atlas-phase3](2026-08-23-implement-atlas-phase3.md)\n",
      "experiences/2026-08-23-implement-atlas-phase5.md": "---\ntype: experience\ntitle: \"2026-08-23 implement Phase 5: mesh consolidate in compile\"\ncreated: 2026-08-23\nstatus: raw\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Phase 5 — partial mesh fragments merged by id inside atlas compile; conflict hard-fail; mesh.json written.\"\ntags: \"[memory, implement, atlas, mesh, work_id]\"\norigin: internal\nsensitivity: internal\nimplements: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\nplan_path: /home/workdir/artifacts/autogenesis-plans/2026-08-23-atlas-reboot-okf-wiki-v1.md\nconstruct_eval: deferred\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: implements\n  - path: experiences/2026-08-23-implement-atlas-phase4.md\n    kind: follows\n---\n# 2026-08-23 implement Phase 5: mesh consolidate\n\n## Context\n\nComposition pin required mesh consolidation as a clear step inside atlas compile/validate.\n\n## What was implemented\n\n### Changed files\n\n- `atlas/scripts/atlas_cli/core/mesh.py` — discover fragments, validate entries, merge by id, write mesh.json\n- `atlas/scripts/atlas_cli/commands/validate.py` — mesh step before staging checks\n- Fixture: `fixtures/mini-atlas/mesh/fragments/*.json`\n- `atlas/SKILL.md` — v0.5.0-phase5\n\n### Behaviour\n\n- Fragments: `mesh/fragments/*.json`, `*.mesh.fragment.json`, `mesh.fragment.json`, …\n- Required entry fields: `id`, `root`, `access` (`read` | `read/write`)\n- Optional: `contribution.type`, `contribution.repository`\n- Same `id` with differing `root` or `access` → **mesh_conflict** critical (exit 2)\n- Success → writes `mesh.json` at Atlas root\n\n### Smokes\n\n| Case | Result |\n|------|--------|\n| Two compatible fragments | exit 0, mesh.json with 2 atlases |\n| Conflicting root/access | exit 2, mesh_conflict |\n| No fragments | exit 0, mesh step skipped |\n\n## Deferred\n\n- BM25 engine, construct adversarial suite, live okf-wiki migration\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **implements:** [2026-08-23-atlas-design-plan](2026-08-23-atlas-design-plan.md)\n- **follows:** [2026-08-23-implement-atlas-phase4](2026-08-23-implement-atlas-phase4.md)\n",
      "experiences/2026-08-23-implement-atlas-phase6.md": "---\ntype: experience\ntitle: \"2026-08-23 implement Phase 6: construct adversarial report\"\ncreated: 2026-08-23\nstatus: raw\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Phase 6 — adversarial smokes run against Atlas CLI; construct_eval green (8 green, 0 red, 2 deferred).\"\ntags: \"[memory, implement, atlas, construct, work_id]\"\norigin: internal\nsensitivity: internal\nimplements: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\nplan_path: /home/workdir/artifacts/autogenesis-plans/2026-08-23-atlas-reboot-okf-wiki-v1.md\nconstruct_eval: green\nconstruct_report: /home/workdir/artifacts/atlas-phase6-construct-report.json\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: implements\n  - path: experiences/2026-08-23-implement-atlas-phase5.md\n    kind: follows\n  - path: experiences/2026-08-23-construct-adversarial-green.md\n    kind: related\n---\n# 2026-08-23 implement Phase 6: construct adversarial\n\n## Context\n\nImplement path requires adversarial construct evaluation for behaviour-changing new-surface work.\n\n## Results\n\nReport: `/home/workdir/artifacts/atlas-phase6-construct-report.json`\n\n| Status | Count | Smokes |\n|--------|-------|--------|\n| green | 8 | staging-blocks-compile, search-not-whole-grep, mesh-conflict-on-compile, promote-does-not-compile, sources-refresh-profile, fuzzy-query-smoke, cold-start-fallback-warning, schema-simplicity-budget |\n| deferred | 2 | relative-index-portable (BM25 not in scope), answerability-concrete (live migration not in scope) |\n| red | 0 | — |\n\n**construct_eval: green**\n\nDeferred counters are out of this change’s current scope (grep pilot; no live store cut-over yet).\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **implements:** [2026-08-23-atlas-design-plan](2026-08-23-atlas-design-plan.md)\n- **follows:** [2026-08-23-implement-atlas-phase5](2026-08-23-implement-atlas-phase5.md)\n- **related:** [2026-08-23-construct-adversarial-green](2026-08-23-construct-adversarial-green.md)\n",
      "experiences/2026-08-23-okf-wiki-design-challenge-karpathy-realign.md": "---\ntype: experience\ntitle: \"2026-08-23 design challenge: okf-wiki vs pure OKF / Karpathy — compile failure and realignment\"\ncreated: 2026-08-23\nstatus: raw\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Session diagnosis that compile is broken (pointer-memory + ceremony), agents fall back to grep; comparison to public OKF; challenge that modular composition was the right aim but the heavy path was wrong; emerging direction toward minimal OKF surface + smallest possible compilation + composition.\"\ntags: \"[memory, design, challenge, okf, karpathy, compile, composition, work_id]\"\norigin: internal\nsensitivity: internal\nrelates_to:\n  - path: work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md\n    kind: implements\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: related\n  - path: decisions/type-vocabulary.md\n    kind: related\n---\n# 2026-08-23 design challenge: okf-wiki realignment\n\n## Context\n\nOngoing Autogenesis design path (work_id `okf-wiki-karpathy-realign-simplify-compose-migrate-v1`, change-class new-surface) with objectives:\n\n1. Reconsider structure vs original Karpathy LLM-wiki gist (raw + compile vs direct folders + connections).\n2. Simplify query discipline for minimal/fast path while respecting okf.\n3. Make knowledge modules + composition first-class so users can compound wiki knowledge.\n4. Design migration discipline to any new agreed folder structure.\n\nCross-cutting constraint: skills ship as APM packages → no phone-home telemetry; all quality/usage ledgers must stay local.\n\n## Diagnosis that triggered the deep challenge\n\nUser reported that the “compile” process is not working well. Agents fall back to unbounded grep. Quality snapshot on the meta-wiki itself still shows stubs, inventory digests, core_digest_only, and stale_compiled pages under E1. This is the same failure class first named a blocker on 2026-08-16 (pointer-memory).\n\nRoot causes identified:\n\n- Structure is easy; semantic compile is hard. Gates mostly reward file-graph health.\n- OKF + type vocabulary + progressive disclosure + activation cards + type-normalise gates create high process load. Models optimise for green gates instead of writing claim-bearing knowledge.\n- Hybrid query + gaps was a correct reaction to unbounded grep, but treats the symptom while the compiled layer remains untrustworthy.\n\n## Comparison performed\n\n### Karpathy LLM Wiki (original)\n- raw/ immutable sources → LLM compiles persistent interlinked wiki/.\n- Query the compiled wiki.\n- SCHEMA/operating contract is lightweight.\n- Success = can the agent answer ordinary questions from the wiki without falling back to raw.\n\n### Pure / public Open Knowledge Format (Google Cloud, v0.1 → v0.2)\n- Directory of Markdown + YAML frontmatter.\n- **Only hard requirement: non-empty `type` field.**\n- Directory structure free.\n- Reserved: `index.md` (progressive disclosure), `log.md` (history).\n- Consumers must tolerate unknown types and unknown frontmatter keys.\n- Practical tools (Google reference agent, openknowledge.sh, okfcli, Obsidian plugins, starters) stay thin: write good concepts, keep indexes useful, validate the tiny bar.\n- Modular hierarchical composition is already native via ordinary folders + `index.md` + Markdown links. No promote ceremony required.\n\n### Our okf-wiki implementation\n- Added dual-axis ingest, pointer-memory completion contract, recommended type vocabulary + origin/sensitivity, E0–E3 quality efforts, hybrid L0/L1/L2 query + mandatory gaps/relevance, type-normalise gates, activation cards, substrate contracts, promote-to-module, mesh composition axes, etc.\n- Local `okf` skill correctly stays close to the public minimal bar; okf-wiki layered a heavy operational system on top.\n\n## Gaps we created\n- Structure over substance (gates certify structure, not answerability).\n- Compile is optional in practice (contracts exist on paper; runtime still accepts pointer-memory).\n- Process load displaced content work.\n- Query complexity treated the symptom.\n- Over-constrained what “OKF-compliant” means operationally.\n- Success metrics drifted from “does it answer?” to “do the structural gates pass?”.\n\n## Challenge exchange\n\nUser agreed with the over-engineering diagnosis but clarified the original aim:\n\n> The aim of okf-wiki was to produce an implementation of the standard that could support modular knowledge composition and compilation (what was wrongly named “ingestion”). What I did was create the next step in the journey, but I took the right direction.\n\nCounter returned (and accepted in spirit by the user):\n\n- Modular composition is already native to public OKF via free directories + index.md progressive disclosure + ordinary links. We did not need a parallel heavyweight system (promote, earned modules with special nested index rules, etc.).\n- Compilation was the right goal; the machinery built for it is what broke the models.\n- A “next step” that adds composition on top of a still-broken compile step is not progress.\n- The legitimate next step is: take the public OKF minimal surface and add the *smallest* possible mechanisms that deliver reliable claim-bearing compilation + modular composition that agents can actually execute without falling back to grep.\n\nUser response: “I like your idea.” Requested that the discussion be stored as long-term memory.\n\n## Emerging direction (not yet pinned or approved)\n\n- Move toward public OKF minimalism on the compile and query surfaces.\n- Keep the legitimate aims: durable compilation and modular composition.\n- Cut or make strictly optional the ceremony that currently prevents models from producing usable knowledge.\n- Simplified query stays pure L0 → L1 first; whole-tree/raw grep remains forbidden.\n- Any enrichment for non-related ideas belongs to mesh / explicit explore / housekeep, not core query.\n- Migration discipline must include answerability smoke, not only structural gates.\n- Local-only telemetry remains mandatory (APM packaging constraint).\n\n## Related existing memory\n\n- [[raw/experiences/2026-08-16-skill-feedback-pointer-memory]]\n- [[raw/experiences/2026-08-16-apm-ingest-pointer-memory]]\n- [[learning-2026-08-16-pointer-memory-blocker]]\n- [[learning-coverage-not-answerability]]\n- [[decision-pointer-memory-completion-contract]]\n- [[decision-hybrid-query-and-gaps]]\n- [[decision-flat-knowledge-earned-modules]]\n- [[decision-module-progressive-disclosure]]\n- [[composition-axis-pins]]\n\n## Explicit deferral\n\nKnowledge-page creation / dual-axis ingest / formal pinning of the new direction is deferred to a later wiki-ingest or design-approval step. This remember only captures the session diagnosis and challenge outcome.\n\n## Status\n\nDesign path still open (stops for approval). No product files beyond this experience and telemetry were written in this turn.\n\n## Related\n\n- **implements:** [okf-wiki-karpathy-realign-simplify-compose-migrate-v1](../work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md)\n- **related:** [2026-08-23-atlas-design-plan](2026-08-23-atlas-design-plan.md)\n- **related:** [type-vocabulary](../decisions/type-vocabulary.md)\n",
      "experiences/index.md": "# Experiences\n\n- [Atlas name pin](2026-08-23-atlas-name-pin.md)\n- [Design challenge (Karpathy realign)](2026-08-23-okf-wiki-design-challenge-karpathy-realign.md)\n- [Design plan approved](2026-08-23-atlas-design-plan.md)\n- [Implement phase 1](2026-08-23-implement-atlas-phase1.md)\n- [Implement phase 2](2026-08-23-implement-atlas-phase2.md)\n- [Implement phase 3](2026-08-23-implement-atlas-phase3.md)\n- [Implement phase 4](2026-08-23-implement-atlas-phase4.md)\n- [Implement phase 5](2026-08-23-implement-atlas-phase5.md)\n- [Implement phase 6](2026-08-23-implement-atlas-phase6.md)\n- [Construct adversarial green](2026-08-23-construct-adversarial-green.md)\n- [Cartograph Atlas port](2026-08-23-cartograph-atlas-port.md)\n",
      "index.md": "# Atlas skill memory\n\nProcess memory for the **Atlas** skill (successor to okf-wiki operational layer).\n\n## Folders\n\n- [experiences/](experiences/) — implement and design session experiences\n- [decisions/](decisions/) — pinned design decisions\n- [work/](work/) — task hubs (`work_id` clusters)\n- `staging/` — short-lived buffer (must be empty for green compile)\n\n## Work\n\n- work_id: `okf-wiki-karpathy-realign-simplify-compose-migrate-v1`\n- plan: `artifacts/autogenesis-plans/2026-08-23-atlas-reboot-okf-wiki-v1.md`\n",
      "work/index.md": "# Work\n\nTask hubs (`type: work`) — one page per `work_id`.\n\n- [Atlas reboot of okf-wiki](okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md) — `okf-wiki-karpathy-realign-simplify-compose-migrate-v1`\n",
      "work/okf-wiki-karpathy-realign-simplify-compose-migrate-v1.md": "---\ntype: work\ntitle: \"Atlas reboot of okf-wiki\"\ncreated: 2026-08-23\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\nstatus: implementing\ndescription: \"Design and implement Atlas as the operational successor to okf-wiki — structure, compile, search, migrate/promote, mesh, relations, opening-test store.\"\nrelates_to:\n  - path: experiences/2026-08-23-okf-wiki-design-challenge-karpathy-realign.md\n    kind: related\n  - path: experiences/2026-08-23-atlas-design-plan.md\n    kind: related\n  - path: experiences/2026-08-23-atlas-name-pin.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase1.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase2.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase3.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase4.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase5.md\n    kind: related\n  - path: experiences/2026-08-23-implement-atlas-phase6.md\n    kind: related\n  - path: experiences/2026-08-23-construct-adversarial-green.md\n    kind: related\n  - path: experiences/2026-08-23-cartograph-atlas-port.md\n    kind: related\n  - path: decisions/cartograph-fork-in-atlas.md\n    kind: related\n  - path: decisions/atlas-name.md\n    kind: related\n  - path: decisions/type-vocabulary.md\n    kind: related\n---\n\n## Scope\n\nReboot the okf-wiki operational layer as **Atlas**: OKF v0.2-aligned knowledge substrate with schema-driven free layout, staging, lean CLI (validate/compile/search/migrate/promote), mesh consolidate, frontmatter-authoritative relations, and skill process memory under `references/atlas/`.\n\n## Status\n\nImplementing — CLI and opening-test Atlas are green. Deferred: full BM25 index, live okf-wiki store migration.\n\n## Outcomes\n\n- Atlas skill + Click CLI\n- Opening-test store at `references/atlas/` with experiences, decisions, and this work hub\n- Relation vocabulary (`relates_to` / `kind`) and recommended types including `work`\n- Construct adversarial report green (2 deferred out of scope)\n- Cartograph forked into `addons/cartograph/` (Build-only sky; skill is the only Atlas viewer source)\n\n## Related\n\nSee `relates_to` frontmatter (authoritative).\n"
    }
  },
  "mini": {
    "id": "mini-atlas-fixture",
    "title": "Mini Atlas fixture for validate smokes",
    "schema": {
      "schema_version": "1.0",
      "atlas_id": "mini-atlas-fixture",
      "title": "Mini Atlas fixture for validate smokes",
      "structure": {
        "free_layout": true,
        "staging_dir": "staging",
        "require_index_in_folders": true,
        "reserved_names": [
          "index.md",
          "log.md",
          "staging"
        ]
      },
      "compile": {
        "hard_fail": true,
        "allow_inline_ignores": true,
        "min_body_chars": 40,
        "core_checks": [
          "okf_compliance",
          "frontmatter",
          "internal_links",
          "not_just_links",
          "schema_present",
          "no_answerable_in_staging",
          "index_md_present"
        ],
        "simplicity_budget": {
          "max_required_frontmatter_keys_per_type": 8,
          "max_required_sections_per_type": 6
        }
      },
      "templates": {
        "directory": "templates/",
        "by_type": {
          "experience": {
            "file": "templates/experience.md",
            "frontmatter": {
              "required": [
                "type",
                "title",
                "created",
                "work_id"
              ],
              "recommended": [
                "description",
                "tags",
                "status"
              ]
            },
            "sections": {
              "required": [
                "Context",
                "What happened",
                "Outcome"
              ],
              "recommended": [
                "Related",
                "Follow-ups"
              ]
            }
          },
          "decision": {
            "file": "templates/decision.md",
            "frontmatter": {
              "required": [
                "type",
                "title",
                "created"
              ],
              "recommended": [
                "status",
                "work_id"
              ]
            },
            "sections": {
              "required": [
                "Decision",
                "Rationale"
              ],
              "recommended": [
                "Alternatives considered",
                "Consequences"
              ]
            }
          }
        }
      },
      "query": {
        "default_mode": "local",
        "search_engine": "grep",
        "fallback": "rg",
        "staging_visible": false
      }
    },
    "pages": {
      "decisions/index.md": "# Decisions\n\n- [Naming decision](naming.md) — Atlas name pinned as successor to okf-wiki\n",
      "decisions/mesh-access.md": "---\ntype: decision\ntitle: \"Mesh access modes\"\ncreated: 2026-08-23\nstatus: accepted\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Each mesh entry declares read or read/write.\"\n---\n\n## Decision\n\nEvery Atlas entry in a mesh must declare `access: read` or `access: read/write`.\n\n## Rationale\n\nShared upstream knowledge stays safely read-only while owned Atlases remain mutable.\n\n## Alternatives considered\n\nImplicit write access for all peers was rejected as unsafe for APM-packaged knowledge.\n\n## Consequences\n\n`atlas compile` validates access values; write ops against `read` Atlases hard-fail.\n",
      "decisions/naming.md": "---\ntype: decision\ntitle: \"Atlas as successor name\"\ncreated: 2026-08-23\nstatus: accepted\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\ndescription: \"Pin the rebooted skill name to Atlas.\"\n---\n\n## Decision\n\nThe operational successor to okf-wiki is named **Atlas**.\n\n## Rationale\n\nAtlas best carries compiled, navigable, modular knowledge for skills and projects without the process baggage of the previous surface.\n\n## Alternatives considered\n\nCodex, tome, library, archive, and memory were evaluated; Atlas won on breadth and graph character.\n\n## Consequences\n\nAll new operational knowledge work targets the Atlas skill and CLI contracts.\n",
      "experiences/index.md": "# Experiences\n\n- [Name pin](name-pin.md) — session that locked the Atlas name\n",
      "experiences/name-pin.md": "---\ntype: experience\ntitle: \"Atlas name pin session\"\ncreated: 2026-08-23\nwork_id: okf-wiki-karpathy-realign-simplify-compose-migrate-v1\nstatus: raw\ndescription: \"Design session that pinned Atlas as the skill name.\"\ntags:\n  - naming\n  - design\n---\n\n## Context\n\nDesign path for the okf-wiki reboot needed a successor name that signalled compiled modular knowledge.\n\n## What happened\n\nAfter evaluating codex, library, archive, and others, the team pinned **Atlas**.\n\n## Outcome\n\nName locked; structure and compile pins followed in the same design path.\n\n## Related\n\nSee [Naming decision](../decisions/naming.md).\n\n## Follow-ups\n\nImplement the lean CLI and migrate stores under the Atlas contract.\n",
      "index.md": "# Mini Atlas fixture\n\n- [Naming decision](decisions/naming.md) — example compiled decision\n- [Name pin experience](experiences/name-pin.md) — example experience\n"
    }
  }
} as Record<string, BundledAtlas>;
