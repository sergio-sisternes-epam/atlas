from __future__ import annotations

import click

from . import __version__
from .commands import init as cmd_init
from .commands import migrate as cmd_migrate
from .commands import promote as cmd_promote
from .commands import search as cmd_search
from .commands import validate as cmd_validate
from .commands import idcmd as cmd_id
from .commands import mount as cmd_mount
from .commands import resolve as cmd_resolve
from .commands import authcmd as cmd_auth
from .commands import schema_cmd as cmd_schema
from .commands import recall as cmd_recall
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
def validate_cmd(
    root: str | None,
    as_json: bool,
    type_name: str | None,
    path_prefix: str | None,
) -> None:
    """Hard gate: SCHEMA contract, staging empty, OKF type, links, page contract."""
    raise SystemExit(cmd_validate.run(root, as_json, type_name, path_prefix))


@main.command("compile")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
@click.option("--type", "type_name", default=None, help="focus page walk on this frontmatter type")
@click.option("--path", "path_prefix", default=None, help="focus page walk on this store-relative prefix")
def compile_cmd(
    root: str | None,
    as_json: bool,
    type_name: str | None,
    path_prefix: str | None,
) -> None:
    """Alias for validate (compile success = validate green + staging empty)."""
    raise SystemExit(cmd_validate.run(root, as_json, type_name, path_prefix))


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
@click.option("--force", is_flag=True, help="overwrite existing SCHEMA.json")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
@click.option(
    "--schema-version",
    "schema_version",
    default="1.0",
    show_default=True,
    help="SCHEMA envelope version (1.0 stays current behaviour; 2.0 adds disabled recall)",
)
def init_cmd(root: str | None, force: bool, as_json: bool, schema_version: str) -> None:
    """Write a first SCHEMA.json and default templates."""
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


@main.command("search")
@click.argument("query")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--limit", default=10, show_default=True, help="max hits")
@click.option(
    "--engine",
    type=click.Choice(["grep", "bm25"], case_sensitive=False),
    default=None,
    help="override SCHEMA query.search_engine",
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
def search_cmd(
    query: str,
    root: str | None,
    limit: int,
    engine: str | None,
    as_json: bool,
    include_exits: bool,
    profile: str | None,
    allow_partial: bool,
) -> None:
    """Discover concepts (tool). Agent protocol is path query + B17 card."""
    raise SystemExit(
        cmd_search.run(
            root, query, limit, as_json, engine, include_exits, profile, allow_partial
        )
    )


@main.command("query")
@click.argument("query")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--limit", default=10, show_default=True)
@click.option(
    "--engine",
    type=click.Choice(["grep", "bm25"], case_sensitive=False),
    default=None,
)
@click.option("--json", "as_json", is_flag=True)
@click.option("--include-exits", is_flag=True)
@click.option("--profile", default=None)
@click.option("--allow-partial", is_flag=True)
def query_cmd(
    query: str,
    root: str | None,
    limit: int,
    engine: str | None,
    as_json: bool,
    include_exits: bool,
    profile: str | None,
    allow_partial: bool,
) -> None:
    """Alias of search (agent-facing verb from the mesh plan)."""
    raise SystemExit(
        cmd_search.run(
            root, query, limit, as_json, engine, include_exits, profile, allow_partial
        )
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
    """Inspect, validate, activate, or index SCHEMA 2.0 recall."""


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
    """Recall index generations."""


@recall_index_group.command("build")
@click.option("--root", default=None)
@click.option("--json", "as_json", is_flag=True)
def recall_index_build_cmd(root: str | None, as_json: bool) -> None:
    raise SystemExit(cmd_recall.run_index_build(root, as_json))


if __name__ == "__main__":
    main()
