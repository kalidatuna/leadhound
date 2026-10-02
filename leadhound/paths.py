"""Where leadhound keeps its config and database.

Order: explicit flag, then a leadhound.ini / leadhound.db in the current folder (older setups),
then the per-user data folder (~/.leadhound, or $LEADHOUND_HOME).
"""
from __future__ import annotations

import os


def data_dir() -> str:
    return os.environ.get("LEADHOUND_HOME") or os.path.join(os.path.expanduser("~"), ".leadhound")


def resolve(config_arg: str | None = None, db_arg: str | None = None) -> tuple[str, str]:
    def pick(arg, local_name, home_name):
        if arg:
            return arg
        if os.path.exists(local_name):
            return os.path.abspath(local_name)
        return os.path.join(data_dir(), home_name)

    cfg = pick(config_arg, "leadhound.ini", "config.ini")
    db = pick(db_arg, "leadhound.db", "leadhound.db")
    for p in (cfg, db):
        folder = os.path.dirname(os.path.abspath(p))
        os.makedirs(folder, exist_ok=True)
    return cfg, db
