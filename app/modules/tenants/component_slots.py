"""Custom Component Registry: slots de UI reemplazables por tenant.

El front registra variantes en código. Aquí solo se guarda qué variante usa cada tenant.
Si el front no conoce la variante, cae a `default`.
"""

from __future__ import annotations

from typing import Any

DEFAULT_VARIANT = "default"

COMPONENT_SLOTS: tuple[dict[str, Any], ...] = (
    {
        "slot": "login.brand",
        "label": "Marca del login",
        "variants": [DEFAULT_VARIANT],
    },
    {
        "slot": "sidebar.brand",
        "label": "Marca del menú lateral",
        "variants": [DEFAULT_VARIANT],
    },
    {
        "slot": "header.title",
        "label": "Título del encabezado",
        "variants": [DEFAULT_VARIANT],
    },
    {
        "slot": "dashboard.extra",
        "label": "Bloque extra del dashboard",
        "variants": [DEFAULT_VARIANT],
    },
)

KNOWN_SLOTS: frozenset[str] = frozenset(item["slot"] for item in COMPONENT_SLOTS)


def default_custom_components() -> dict[str, str]:
    return {item["slot"]: DEFAULT_VARIANT for item in COMPONENT_SLOTS}


def merge_custom_components(stored: dict[str, Any] | None) -> dict[str, str]:
    out = default_custom_components()
    if not stored:
        return out
    for key, value in stored.items():
        if key not in KNOWN_SLOTS:
            continue
        variant = str(value or DEFAULT_VARIANT).strip() or DEFAULT_VARIANT
        out[key] = variant[:80]
    return out
