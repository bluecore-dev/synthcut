"""Migration entry point.

    python -m synthcut_core.migrate upgrade [revision]
    python -m synthcut_core.migrate current
    python -m synthcut_core.migrate revision -m "message" [--autogenerate]

Migrations run with the application's own database role, so every table is
owned by the role that later reads and writes it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from .settings import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", (database_url or get_settings().database_url).replace("%", "%%"))
    return cfg


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthcut-migrate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("upgrade")
    up.add_argument("revision", nargs="?", default="head")
    sub.add_parser("current")
    sub.add_parser("history")
    rev = sub.add_parser("revision")
    rev.add_argument("-m", "--message", required=True)
    rev.add_argument("--autogenerate", action="store_true")
    args = parser.parse_args(argv)

    cfg = alembic_config()
    if args.cmd == "upgrade":
        command.upgrade(cfg, args.revision)
    elif args.cmd == "current":
        command.current(cfg, verbose=True)
    elif args.cmd == "history":
        command.history(cfg)
    elif args.cmd == "revision":
        command.revision(cfg, message=args.message, autogenerate=args.autogenerate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
