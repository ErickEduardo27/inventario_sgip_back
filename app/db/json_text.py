"""JSON almacenado como ``TEXT`` (importación CSV/psql y valores legacy ``NULL``)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


class NullableJSONText(TypeDecorator):
    """``dict`` ↔ texto JSON en columna ``TEXT``; ``NULL``/vacío/``'NULL'`` → ``None``."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            s = value.strip()
            if not s or s.upper() == "NULL":
                return None
            return s
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value: Any, dialect: object) -> dict[str, Any] | None:
        if value is None:
            return None
        s = str(value).strip()
        if not s or s.upper() == "NULL":
            return None
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
