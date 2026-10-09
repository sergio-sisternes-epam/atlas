from __future__ import annotations

import click

from . import __version__
from .commands import init as cmd_init
from .commands import migrate as cmd_migrate
from .commands import memory_migrate as cmd_memory_migrate
from .commands import promote as cmd_promote
from .commands import search as cmd_search
from .commands import validate as cmd_validate
from .commands import idcmd as cmd_id
from .commands import mount as cmd_mount
from .commands import resolve as cmd_resolve
from .commands import authcmd as cmd_auth
from .commands import schema_cmd as cmd_schema
from .commands import recall as cmd_recall
from .commands import index as cmd_index
from .commands import graph as cmd_graph
from .commands import storecmd as cmd_store


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Exit: 0 ok/non-blocking dependency warnings · 1 actionable warnings · 2 critical",
)
@click.version_option(__version__, prog_name="atlas")
def main() -> None:
    """Atlas CLI — lean deterministic gates for OKF v0.2 knowledge substrates."""


@main.command("validate")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
@click.option("--type", "type_name", default=None, help="focus page walk on this frontmatter type")
@click.option("--path", "path_prefix", default=None, help="focus page walk on this store-relative prefix")
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="report findings only; never write mesh.json or publish the recall index",
)
def validate_cmd(
    root: str | None,
    as_json: bool,
    type_name: str | None,
    path_prefix: str | None,
    dry_run: bool,
) -> None:
    """Hard gate: SCHEMA contract, staging empty, OKF type, links, page contract."""
    raise SystemExit(cmd_validate.run(root, as_json, type_name, path_prefix, dry_run))


@main.command("compile")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
@click.option("--type", "type_name", default=None, help="focus page walk on this frontmatter type")
@click.option("--path", "path_prefix", default=None, help="focus page walk on this store-relative prefix")
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="report findings only; never write mesh.json or publish the recall index",
)
def compile_cmd(
    root: str | None,
    as_json: bool,
    type_name: str | None,
    path_prefix: str | None,
    dry_run: bool,
) -> None:
    """Alias for validate (compile success = validate green + staging empty)."""
    raise SystemExit(cmd_validate.run(root, as_json, type_name, path_prefix, dry_run))


@main.command("id")
@click.argument("pointer")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def id_cmd(pointer: str, as_json: bool) -> None:
    """Normalise a pointer to a scheme-free atlas-id (host/org/repo)."""
    raise SystemExit(cmd_id.run(pointer, as_json))


@main.command("auth")
@click.argument("action", default="login", required=False)
@click.option("--host", default="github.com", show_default=True)
@click.option("--org", default=None, help="optional org override grain")
@click.option("--ssh", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def auth_cmd(action: str, host: str, org: str | None, ssh: bool, as_json: bool) -> None:
    """login | list | logout | status. Records host/backend only, never a PAT."""
    raise SystemExit(cmd_auth.run(action, host, ssh, as_json, org))


@main.command("mount")
@click.argument("source")
@click.option("--ref", default=None, help="branch or tag to check out")
@click.option("--target", default=None, help="override mount path")
@click.option("--ssh", is_flag=True, help="use SSH remote")
@click.option("--cwd", "start", default=None, help="project directory")
@click.option("--json", "as_json", is_flag=True)
def mount_cmd(
    source: str,
    ref: str | None,
    target: str | None,
    ssh: bool,
    start: str | None,
    as_json: bool,
) -> None:
    """Mount a git-backed Atlas in-repo; default: .atlas/<id>/."""
    raise SystemExit(cmd_mount.run(source, ref, target, ssh, start, as_json))


@main.command("resolve")
@click.argument("pointer")
@click.option("--cwd", "start", default=None, help="project directory")
@click.option("--json", "as_json", is_flag=True)
def resolve_cmd(pointer: str, start: str | None, as_json: bool) -> None:
    """Map an id to the mount root, or a page URI to a file."""
    raise SystemExit(cmd_resolve.run(pointer, start, as_json))


@main.command("init")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option(
    "--force",
    is_flag=True,
    help="overwrite existing CONTRACT.json (and remove a stale SCHEMA.json after the new file is written)",
)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
@click.option(
    "--schema-version",
    "schema_version",
    default="1.0",
    show_default=True,
    help="SCHEMA envelope version (1.0 stays current behaviour; 2.0 adds disabled recall)",
)
def init_cmd(root: str | None, force: bool, as_json: bool, schema_version: str) -> None:
    """Write a first CONTRACT.json and default templates."""
    raise SystemExit(cmd_init.run(root, force, as_json, schema_version))


@main.group("store")
def store_group() -> None:
    """Shared (consumer atlas branch) or dedicated (separate repo) storage."""


@store_group.command("init")
@click.option(
    "--strategy",
    type=click.Choice(["shared", "dedicated"], case_sensitive=False),
    default="shared",
    show_default=True,
)
@click.option("--remote", default=None, help="git URL; shared defaults to consumer origin")
@click.option("--ssh", is_flag=True)
@click.option("--cwd", "start", default=None, help="project directory")
@click.option("--json", "as_json", is_flag=True)
@click.option(
    "--schema-version",
    "schema_version",
    default="1.0",
    show_default=True,
)
def store_init_cmd(
    strategy: str,
    remote: str | None,
    ssh: bool,
    start: str | None,
    as_json: bool,
    schema_version: str,
) -> None:
    """Bootstrap a store. Default strategy is shared. Never creates a host repo."""
    raise SystemExit(cmd_store.run_init(strategy.lower(), remote, start, ssh, as_json, schema_version))


@store_group.command("rehost")
@click.option(
    "--destination-strategy",
    "destination_strategy",
    type=click.Choice(["shared", "dedicated"], case_sensitive=False),
    required=True,
)
@click.option("--remote", default=None, help="existing dedicated remote (required when destination is dedicated)")
@click.option("--id", "atlas_id", default=None, help="source store id (default: sole mesh row)")
@click.option("--ssh", is_flag=True)
@click.option("--cwd", "start", default=None)
@click.option("--json", "as_json", is_flag=True)
def store_rehost_cmd(
    destination_strategy: str,
    remote: str | None,
    atlas_id: str | None,
    ssh: bool,
    start: str | None,
    as_json: bool,
) -> None:
    """Move store history between shared and dedicated. Does not import pages."""
    raise SystemExit(
        cmd_store.run_rehost(destination_strategy.lower(), remote, atlas_id, start, ssh, as_json)
    )


@main.command("migrate")
@click.argument("source")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option(
    "--into",
    default=None,
    help="staging directory name (default from SCHEMA or 'staging')",
)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def migrate_cmd(
    source: str,
    root: str | None,
    into: str | None,
    as_json: bool,
) -> None:
    """Copy external/old content into staging/ only (no compile)."""
    raise SystemExit(cmd_migrate.run(root, source, into, as_json))


@main.command("memory-migrate")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option(
    "--operation",
    required=True,
    type=click.Choice(["assess", "inventory", "apply"]),
    help=(
        "assess/inventory write nothing; apply rewrites a pre-beta contract or an empty "
        "unstamped full beta.2 init, or restamps a current store with --batch restamp"
    ),
)
@click.option(
    "--batch",
    default=None,
    help=(
        "explicit batch token for apply: 'contract-file' (pre-beta or empty beta.2 "
        "init -> CONTRACT.json stamped 0.13.0) or 'restamp' (current CONTRACT.json "
        "stamped 0.13.0-beta.3/beta.4/beta.7 -> 0.13.0; atlas_release only)"
    ),
)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def memory_migrate_cmd(
    root: str | None,
    operation: str,
    batch: str | None,
    as_json: bool,
) -> None:
    """Pre-beta -> 0.13.0 contract-file migration and opt-in restamp (path memory-migrate)."""
    raise SystemExit(cmd_memory_migrate.run(root, operation, batch, as_json))


@main.command("promote")
@click.argument("staging_file")
@click.option(
    "--to",
    "to_path",
    required=True,
    help="target path relative to atlas root, e.g. decisions/foo.md",
)
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option(
    "--type",
    "type_hint",
    default=None,
    help="template type hint, e.g. experience | decision",
)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def promote_cmd(
    staging_file: str,
    to_path: str,
    root: str | None,
    type_hint: str | None,
    as_json: bool,
) -> None:
    """Scaffold staging file into durable page; agent finishes claims/links."""
    raise SystemExit(
        cmd_promote.run(root, staging_file, to_path, type_hint, as_json)
    )


@main.group("schema")
def schema_group() -> None:
    """Create, install, or uninstall SCHEMA overlays (CLI is the only writer)."""


@schema_group.command("new")
@click.argument("cid")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--claim", "claims", multiple=True, help="claimed folder prefix (repeatable)")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def schema_new_cmd(cid: str, root: str | None, claims: tuple[str, ...], as_json: bool) -> None:
    """Start a project-local overlay under schema.d/<id>.json."""
    raise SystemExit(cmd_schema.run_new(cid, root, claims, as_json))


@schema_group.command("install")
@click.argument("source")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--force", is_flag=True, help="overwrite existing overlay (required if required-keys changed)")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def schema_install_cmd(source: str, root: str | None, force: bool, as_json: bool) -> None:
    """Copy a skill or file overlay into schema.d/."""
    raise SystemExit(cmd_schema.run_install(source, root, force, as_json))


@schema_group.command("uninstall")
@click.argument("cid")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def schema_uninstall_cmd(cid: str, root: str | None, as_json: bool) -> None:
    """Remove an overlay and receipt-listed CLI writes. Does not delete later pages."""
    raise SystemExit(cmd_schema.run_uninstall(cid, root, as_json))


@schema_group.command("memory-rung")
@click.option(
    "--set",
    "rung",
    required=True,
    type=click.Choice(["info", "warn", "error"]),
    help="memory.rung severity for legacy_document/missing_gist/gist_parent/frame_members",
)
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def schema_memory_rung_cmd(rung: str, root: str | None, as_json: bool) -> None:
    """Write SCHEMA.memory.rung (the only writer of that block)."""
    raise SystemExit(cmd_schema.run_memory_rung(rung, root, as_json))


@schema_group.command("upgrade")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--to", "to_version", default="2.0", show_default=True)
@click.option(
    "--apply/--dry-run",
    "apply_upgrade",
    default=False,
    help="write SCHEMA 2.0 and compatibility overlay / preview (default)",
)
@click.option("--json", "as_json", is_flag=True)
def schema_upgrade_cmd(
    root: str | None,
    to_version: str,
    apply_upgrade: bool,
    as_json: bool,
) -> None:
    """Upgrade SCHEMA 1.0 to 2.0. Does not enable recall."""
    raise SystemExit(cmd_schema.run_upgrade(root, apply_upgrade, as_json, to_version))


@main.group("recall")
def recall_group() -> None:
    """Discover (recall run), inspect, validate, activate, or index SCHEMA 2.0 recall."""


@recall_group.command("run")
@click.argument("query")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--limit", default=10, show_default=True, help="max hits")
@click.option(
    "--engine",
    type=click.Choice(["grep", "bm25", "nanograph"], case_sensitive=False),
    default=None,
    help="override the preferred engine (ATLAS_RECALL_ENGINE, atlas-mesh.json recall.engine, SCHEMA query.search_engine); nanograph: optional, macOS arm64, falls back to bm25",
)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
@click.option(
    "--include-exits",
    is_flag=True,
    help="include kva/status terminated|deprecated|superseded (also via kva:terminated)",
)
@click.option("--profile", default=None, help="request-scoped SCHEMA 2.0 recall profile")
@click.option(
    "--allow-partial",
    is_flag=True,
    help="SCHEMA 2.0: return incomplete corpus results (exit 1)",
)
def recall_run_cmd(
    query: str,
    root: str | None,
    limit: int,
    engine: str | None,
    as_json: bool,
    include_exits: bool,
    profile: str | None,
    allow_partial: bool,
) -> None:
    """Discover concepts (tool). Agent protocol is path recall + B17 card."""
    raise SystemExit(
        cmd_search.run(
            root, query, limit, as_json, engine, include_exits, profile, allow_partial
        )
    )


@recall_group.command("profiles")
@click.option("--root", default=None)
@click.option("--json", "as_json", is_flag=True)
def recall_profiles_cmd(root: str | None, as_json: bool) -> None:
    raise SystemExit(cmd_recall.run_profiles(root, as_json))


@recall_group.command("show")
@click.option("--root", default=None)
@click.option("--json", "as_json", is_flag=True)
def recall_show_cmd(root: str | None, as_json: bool) -> None:
    raise SystemExit(cmd_recall.run_show(root, as_json))


@recall_group.command("status")
@click.option("--root", default=None)
@click.option("--json", "as_json", is_flag=True)
def recall_status_cmd(root: str | None, as_json: bool) -> None:
    raise SystemExit(cmd_recall.run_status(root, as_json))


@recall_group.command("validate")
@click.option("--root", default=None)
@click.option("--config", default=None, help="recall JSON file")
@click.option("--json", "as_json", is_flag=True)
def recall_validate_cmd(root: str | None, config: str | None, as_json: bool) -> None:
    raise SystemExit(cmd_recall.run_validate(root, config, as_json))


@recall_group.command("activate")
@click.option("--profile", default="atlas:ranked", show_default=True)
@click.option("--root", default=None)
@click.option("--json", "as_json", is_flag=True)
def recall_activate_cmd(profile: str, root: str | None, as_json: bool) -> None:
    raise SystemExit(cmd_recall.run_activate(root, profile, as_json))


@recall_group.command("disable")
@click.option("--root", default=None)
@click.option("--json", "as_json", is_flag=True)
def recall_disable_cmd(root: str | None, as_json: bool) -> None:
    raise SystemExit(cmd_recall.run_disable(root, as_json))


@recall_group.group("index")
def recall_index_group() -> None:
    """Deprecated: use `atlas index`."""


@recall_index_group.command("build")
@click.option("--root", default=None)
@click.option("--json", "as_json", is_flag=True)
def recall_index_build_cmd(root: str | None, as_json: bool) -> None:
    """Deprecated alias of `atlas index build` (removal after 0.14.x)."""
    raise SystemExit(cmd_recall.run_index_build(root, as_json))


_ENGINE_ARG = "grep|bm25|nanograph"
_STORE_HELP = "atlas id of a store row in the project's atlas-mesh.json (any spelling that normalises to it)"


@main.group("index")
def index_group() -> None:
    """Manage the preferred recall engine (grep|bm25|nanograph) and its indexes."""


@index_group.command("set")
@click.argument("engine", metavar=_ENGINE_ARG)
@click.option("--root", default=None, help="store or project directory (default: cwd)")
@click.option("--store", "store", default=None, help=_STORE_HELP)
@click.option("--default", "default", is_flag=True, help="set the default for all Atlases in the project")
@click.option("--build", is_flag=True, help="build or refresh the affected indexes now")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def index_set_cmd(engine: str, root: str | None, store: str | None, default: bool, build: bool, as_json: bool) -> None:
    """Write recall.engine for one store (default: the store at --root) or the project default."""
    raise SystemExit(cmd_index.run_set(engine, root, store, default, build, as_json))


@index_group.command("unset")
@click.option("--root", default=None, help="store or project directory (default: cwd)")
@click.option("--store", "store", default=None, help=_STORE_HELP)
@click.option("--default", "default", is_flag=True, help="remove the project-wide default")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def index_unset_cmd(root: str | None, store: str | None, default: bool, as_json: bool) -> None:
    """Remove recall.engine (index files are left in place)."""
    raise SystemExit(cmd_index.run_unset(root, store, default, as_json))


@index_group.command("show")
@click.option("--root", default=None, help="store or project directory (default: cwd)")
@click.option("--store", "store", default=None, help=_STORE_HELP)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def index_show_cmd(root: str | None, store: str | None, as_json: bool) -> None:
    """Configured values per level, winning engine, effective engine and index freshness for one store."""
    raise SystemExit(cmd_index.run_show(root, store, as_json))


@index_group.command("status")
@click.option("--root", default=None, help="store or project directory (default: cwd)")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def index_status_cmd(root: str | None, as_json: bool) -> None:
    """Every store in the project: configured and effective engine, freshness, index directory."""
    raise SystemExit(cmd_index.run_status(root, as_json))


@index_group.command("build")
@click.option("--root", default=None, help="store or project directory (default: cwd)")
@click.option("--store", "store", default=None, help=_STORE_HELP)
@click.option("--all", "all_stores", is_flag=True, help="every mounted store in the project")
@click.option("--force", is_flag=True, help="rebuild even when the index is fresh")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def index_build_cmd(root: str | None, store: str | None, all_stores: bool, force: bool, as_json: bool) -> None:
    """Build or refresh the index for the effective engine (exit 1 when any build failed)."""
    raise SystemExit(cmd_index.run_build(root, store, all_stores, force, as_json))


@main.group("graph")
def graph_group() -> None:
    """Structural lookups over relates_to and frontmatter (read-only; no index required)."""


_ROOT_HELP = "Atlas store root (default: cwd)"
_PARTIAL_HELP = "report an incomplete corpus (exit 1) instead of failing on projection errors"
_EXITS_HELP = "include kva/status terminated|deprecated|superseded pages"


@graph_group.command("nodes")
@click.option("--root", default=None, help=_ROOT_HELP)
@click.option("--where", "where", multiple=True, help="field=value on top-level frontmatter (repeatable, ANDed)")
@click.option("--path", "path_prefix", default=None, help="store-relative path prefix")
@click.option("--include-exits", is_flag=True, help=_EXITS_HELP)
# min=1: 0 has no documented meaning for nodes and would only return an empty list.
@click.option("--limit", type=click.IntRange(min=1), default=None, help="max nodes (at least 1)")
@click.option("--allow-partial", is_flag=True, help=_PARTIAL_HELP)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def graph_nodes_cmd(
    root: str | None,
    where: tuple[str, ...],
    path_prefix: str | None,
    include_exits: bool,
    limit: int | None,
    allow_partial: bool,
    as_json: bool,
) -> None:
    """Pages whose frontmatter matches every --where."""
    raise SystemExit(
        cmd_graph.run_nodes(root, where, path_prefix, include_exits, limit, allow_partial, as_json)
    )


@graph_group.command("edges")
@click.option("--root", default=None, help=_ROOT_HELP)
@click.option("--from", "from_page", default=None, help="edges authored by this page")
@click.option("--to", "to_page", default=None, help="edges targeting this path")
@click.option("--all", "all_edges", is_flag=True, help="every edge in the store")
@click.option("--kind", "kinds", multiple=True, help="relation kind (repeatable)")
@click.option("--include-exits", is_flag=True, help=_EXITS_HELP)
@click.option("--allow-partial", is_flag=True, help=_PARTIAL_HELP)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def graph_edges_cmd(
    root: str | None,
    from_page: str | None,
    to_page: str | None,
    all_edges: bool,
    kinds: tuple[str, ...],
    include_exits: bool,
    allow_partial: bool,
    as_json: bool,
) -> None:
    """relates_to edges in authored direction, unresolved ones included."""
    raise SystemExit(
        cmd_graph.run_edges(
            root, from_page, to_page, all_edges, kinds, include_exits, allow_partial, as_json
        )
    )


@graph_group.command("neighbours")
@click.argument("page")
@click.option("--root", default=None, help=_ROOT_HELP)
@click.option("--kind", "kinds", multiple=True, help="traverse only this relation kind (repeatable)")
@click.option(
    "--direction",
    type=click.Choice(["in", "out", "both"]),
    default="both",
    show_default=True,
)
@click.option("--hops", type=click.IntRange(min=1, max=3), default=1, show_default=True, help="1..3")
@click.option("--where", "where", multiple=True, help="filter returned nodes (traversal passes through)")
@click.option("--max-nodes", type=click.IntRange(min=1), default=200, show_default=True)
@click.option("--max-edges", type=click.IntRange(min=1), default=500, show_default=True)
@click.option("--include-exits", is_flag=True, help=_EXITS_HELP)
@click.option("--allow-partial", is_flag=True, help=_PARTIAL_HELP)
@click.option(
    "--driver",
    type=click.Choice(["native", "nanograph"]),
    default="native",
    show_default=True,
    help="traversal driver (nanograph: optional, macOS arm64, falls back to native)",
)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def graph_neighbours_cmd(
    page: str,
    root: str | None,
    kinds: tuple[str, ...],
    direction: str,
    hops: int,
    where: tuple[str, ...],
    max_nodes: int,
    max_edges: int,
    include_exits: bool,
    allow_partial: bool,
    driver: str,
    as_json: bool,
) -> None:
    """Bounded breadth-first neighbourhood of PAGE."""
    raise SystemExit(
        cmd_graph.run_neighbours(
            root, page, kinds, direction, hops, where, max_nodes, max_edges,
            include_exits, allow_partial, as_json, driver,
        )
    )


@graph_group.command("drivers")
@click.option("--root", default=None, help=_ROOT_HELP)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def graph_drivers_cmd(root: str | None, as_json: bool) -> None:
    """Driver registry, platform matrix and what this machine can use."""
    raise SystemExit(cmd_graph.run_drivers(root, as_json))


@graph_group.command("export")
@click.option("--root", default=None, help=_ROOT_HELP)
@click.option("--format", "fmt", type=click.Choice(["json", "nanograph"]), required=True)
@click.option("--out", "out", required=True, help="output directory outside the store")
@click.option("--allow-partial", is_flag=True, help=_PARTIAL_HELP)
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def graph_export_cmd(
    root: str | None, fmt: str, out: str, allow_partial: bool, as_json: bool
) -> None:
    """Deterministic graph export (graph.json, or nanograph schema.pg + seed.jsonl)."""
    raise SystemExit(cmd_graph.run_export(root, fmt, out, allow_partial, as_json))


if __name__ == "__main__":
    main()
