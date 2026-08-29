from __future__ import annotations

import click

from .commands import init as cmd_init
from .commands import migrate as cmd_migrate
from .commands import promote as cmd_promote
from .commands import search as cmd_search
from .commands import validate as cmd_validate
from .commands import view as cmd_view
from .commands import idcmd as cmd_id
from .commands import mount as cmd_mount
from .commands import resolve as cmd_resolve
from .commands import authcmd as cmd_auth


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Exit: 0 ok · 1 warnings · 2 critical (validate/compile)",
)
@click.version_option("0.8.1", prog_name="atlas")
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
    """Materialise a git-backed Atlas and write atlas-mesh.json."""
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
def init_cmd(root: str | None, force: bool, as_json: bool) -> None:
    """Write a first SCHEMA.json and default templates."""
    raise SystemExit(cmd_init.run(root, force, as_json))


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
def search_cmd(
    query: str,
    root: str | None,
    limit: int,
    engine: str | None,
    as_json: bool,
    include_exits: bool,
) -> None:
    """Discover concepts (tool). Agent protocol is path query + B17 card."""
    raise SystemExit(
        cmd_search.run(root, query, limit, as_json, engine, include_exits)
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
def query_cmd(
    query: str,
    root: str | None,
    limit: int,
    engine: str | None,
    as_json: bool,
    include_exits: bool,
) -> None:
    """Alias of search (agent-facing verb from the mesh plan)."""
    raise SystemExit(
        cmd_search.run(root, query, limit, as_json, engine, include_exits)
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


@main.command("view")
@click.option("--root", default=None, help="Atlas store root (default: cwd)")
@click.option("--host", default=None, help="Build preview host (default: http://127.0.0.1:8080)")
@click.option("--check", is_flag=True, help="probe the preview URL")
@click.option("--open", "open_browser", is_flag=True, help="open the viewer URL")
@click.option("--refresh", is_flag=True, help="bust listing cache then probe")
def view_cmd(
    root: str | None,
    host: str | None,
    check: bool,
    open_browser: bool,
    refresh: bool,
) -> None:
    """Point the Grok Build Cartograph preview at an Atlas (Build only)."""
    raise SystemExit(cmd_view.run(root, host, check, open_browser, refresh))


if __name__ == "__main__":
    main()
