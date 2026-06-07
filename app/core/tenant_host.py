"""Resolución de tenant a partir del host (subdominio), estilo multi-tenant por DNS."""

from __future__ import annotations

import re

# Subdominios que no identifican tenant (van al tenant por defecto).
_RESERVED_SUBDOMAIN_SLUGS = frozenset(
    {"www", "api", "app", "cdn", "static", "assets", "mail", "smtp", "admin"}
)


def normalize_host_header(host: str | None) -> str | None:
    if not host or not str(host).strip():
        return None
    h = str(host).strip().lower()
    if h.startswith("["):
        # IPv6 literal; no soportamos subdominio tenant en IPv6.
        return h.split("%", 1)[0].rstrip("]")
    if ":" in h and not h.startswith("["):
        h = h.rsplit(":", 1)[0]
    return h or None


def parse_base_domains(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in (raw or "").split(",") if p.strip()]
    return parts or ["localhost"]


def extract_tenant_slug_from_host(host: str | None, base_domains: list[str]) -> str | None:
    """Devuelve el `slug` de tenant si el host es `{slug}.{base}` o cadena de subdominios bajo `base`.

    Convención: el **primer** segmento del prefijo respecto al dominio base es el slug del tenant
    (p. ej. `acme.localhost` → `acme`; `acme.staging.miapp.com` con base `miapp.com` → `acme`).
    """
    h = normalize_host_header(host)
    if not h:
        return None

    for base in sorted({b.lstrip(".") for b in base_domains}, key=len, reverse=True):
        if not base:
            continue
        if h == base or h == f"www.{base}":
            return None
        suffix = "." + base
        if not h.endswith(suffix):
            continue
        prefix = h[: -len(suffix)].lstrip(".")
        if not prefix:
            return None
        slug = prefix.split(".", 1)[0]
        if not slug or not re.match(r"^[a-z0-9]([a-z0-9-]{0,98}[a-z0-9])?$", slug):
            return None
        if slug in _RESERVED_SUBDOMAIN_SLUGS:
            return None
        return slug

    return None
