"""Compatibility facade for :mod:`app.manufacturing.seed`."""
from __future__ import annotations

from .manufacturing import seed as _canonical
from .manufacturing.seed import *  # noqa: F403

ensure_department_databases = _canonical.ensure_department_databases
db_session = _canonical.db_session
generate_database = _canonical.generate_database


def __getattr__(name: str):
    return getattr(_canonical, name)


def main(argv: list[str] | None = None) -> int:
    return _canonical._main(
        argv,
        ensure_databases=ensure_department_databases,
        session=db_session,
        generate=generate_database,
    )


if __name__ == "__main__":
    raise SystemExit(main())
