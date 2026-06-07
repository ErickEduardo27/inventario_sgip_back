"""Llamadas a Graph API para crear plantillas de mensaje (WABA)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from urllib.parse import urlencode

from app.core.config import Settings
from app.core.exceptions import AppError

def _meta_error_message_from_response_body(err_body: str, fallback: str) -> str:
    try:
        err_json = json.loads(err_body)
        err_obj = err_json.get("error") if isinstance(err_json.get("error"), dict) else {}
        parts = [
            str(err_obj.get("message") or "").strip(),
            str(err_obj.get("error_user_msg") or "").strip(),
            str(err_obj.get("error_user_title") or "").strip(),
        ]
        fbtrace = err_obj.get("fbtrace_id")
        if fbtrace:
            parts.append(f"fbtrace_id={fbtrace}")
        return " — ".join(p for p in parts if p) or err_body or fallback
    except json.JSONDecodeError:
        return err_body or fallback


_META_NAME_RE = re.compile(r"[^a-z0-9_]+")
_VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

_NUMBERED_PLACEHOLDER = re.compile(r"\{\{\d+\}\}")

_VAR_SAMPLES: dict[str, str] = {
    "nombre": "María",
    "apellido": "Pérez",
    "sede": "CD Huachipa",
    "area": "Operaciones",
    "campaña": "Capacitación Q2",
    "fecha": "lunes 12 de mayo",
    "hora": "10:00",
}


def literal_word_count_meta_body(meta_text: str) -> int:
    """Palabras del cuerpo sin contar marcadores {{1}} (aprox. lo que usa Meta para la proporción)."""
    literal = _NUMBERED_PLACEHOLDER.sub(" ", meta_text or "")
    return len([w for w in re.split(r"\s+", literal.strip()) if w])


def validate_meta_template_body(meta_text: str, num_params: int) -> None:
    """Reglas de Meta que suelen disparar 'demasiadas variables / proporción parámetros-palabras'."""
    s = (meta_text or "").strip()
    if num_params == 0:
        return

    if _NUMBERED_PLACEHOLDER.match(s):
        raise AppError(
            "Meta no permite que el mensaje empiece directamente con una variable. "
            "Escribe al menos una palabra al inicio (por ejemplo: «Hola») antes del primer marcador.",
            400,
        )
    if re.search(r"\{\{\d+\}\}\s*$", s):
        raise AppError(
            "Meta no permite que el mensaje termine en una variable. "
            "Añade texto después del último marcador (por ejemplo un cierre o firma).",
            400,
        )
    if re.search(r"\{\{\d+\}\}\s*\{\{\d+\}\}", s):
        raise AppError(
            "Meta no permite dos variables seguidas sin palabras entre medias. "
            "Separa cada variable con texto descriptivo (no solo espacios).",
            400,
        )

    words = literal_word_count_meta_body(s)
    # Guía conservadora (BSP / Meta): palabras literales >= 2*n+1 (p. ej. 2 vars -> 5 palabras).
    min_literal = 2 * num_params + 1
    if words < min_literal:
        raise AppError(
            f"El cuerpo tiene {num_params} variable(s) pero solo {words} palabra(s) fuera de los marcadores. "
            f"Meta exige más texto descriptivo: añade al menos {min_literal - words} palabra(s) más "
            f"(orientación: con {num_params} variable(s) conviene al menos {min_literal} palabras sin contar {{nombre}}). "
            "Evita mensajes cortos con muchas variables.",
            400,
        )

    literal_compact = re.sub(r"\s+", "", _NUMBERED_PLACEHOLDER.sub("", s))
    min_chars = 14 * num_params
    if len(literal_compact) < min_chars:
        raise AppError(
            f"Con {num_params} variable(s), Meta suele pedir un mensaje más largo: el texto fijo (sin marcadores) "
            f"es corto ({len(literal_compact)} caracteres). Amplía el mensaje con frases claras entre variables "
            f"(orientación: al menos unas {min_chars} letras de texto fijo).",
            400,
        )


def sample_text_for_template_variable(var_name: str) -> str:
    """Valor de ejemplo para envíos por API cuando la plantilla Meta tiene parámetros en el BODY."""
    return _VAR_SAMPLES.get((var_name or "").lower(), (var_name or "ejemplo")[:120])[:120]


def normalize_whatsapp_template_language(code: str) -> str:
    """Meta exige códigos de la lista oficial; `es`/`en` sueltos suelen devolver error 100 Invalid parameter."""
    raw = (code or "").strip().replace("-", "_")
    if not raw:
        return "es_ES"
    parts = raw.split("_", 1)
    if len(parts) == 1:
        base = parts[0].lower()
        short_to_locale = {
            "es": "es_ES",
            "en": "en_US",
            "pt": "pt_BR",
            "fr": "fr_FR",
            "de": "de_DE",
            "it": "it_IT",
            "ar": "ar_AR",
            "hi": "hi_IN",
            "id": "id_ID",
            "ja": "ja_JP",
            "ko": "ko_KR",
            "tr": "tr_TR",
            "vi": "vi_VN",
            "zh": "zh_CN",
        }
        return short_to_locale.get(base, raw)
    lang, region = parts[0].lower(), parts[1].upper()
    return f"{lang}_{region}"


def slugify_meta_template_name(name: str, max_len: int = 512) -> str:
    s = (name or "").lower().strip()
    s = _META_NAME_RE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "plantilla"
    return s[:max_len]


def ordered_variable_names(body: str) -> list[str]:
    names: list[str] = []
    for m in _VARIABLE_PATTERN.finditer(body or ""):
        v = m.group(1)
        if v not in names:
            names.append(v)
    return names


def body_to_meta_body_and_example(body: str) -> tuple[str, list[str]]:
    """Convierte {{var}} a {{1}}… y devuelve fila de ejemplos para `example.body_text`."""
    order = ordered_variable_names(body)
    idx_map = {v: i + 1 for i, v in enumerate(order)}

    def repl(m: re.Match[str]) -> str:
        var = m.group(1)
        n = idx_map.get(var)
        if n is None:
            raise ValueError(f"Variable en cuerpo no listada: {var}")
        return f"{{{{{n}}}}}"

    meta_text = _VARIABLE_PATTERN.sub(repl, body or "")
    samples = [_VAR_SAMPLES.get(v.lower(), (v or "ejemplo")[:40]) for v in order]
    return meta_text, samples


def create_waba_message_template(
    settings: Settings,
    *,
    meta_name: str,
    language: str,
    category: str,
    body_text: str,
    example_row: list[str],
    header_format: str | None = None,
    quick_reply_buttons: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    token = settings.whatsapp_access_token.strip()
    waba = settings.whatsapp_business_account_id.strip()
    if not token or not waba:
        raise AppError(
            "Falta configurar WhatsApp para plantillas Meta: WHATSAPP_ACCESS_TOKEN y "
            "WHATSAPP_BUSINESS_ACCOUNT_ID (o WABA_ID) en el servidor.",
            503,
        )
    version = (settings.whatsapp_graph_api_version or "v25.0").strip().lstrip("/")
    url = f"https://graph.facebook.com/{version}/{waba}/message_templates"

    lang_norm = normalize_whatsapp_template_language(language)

    n_params = len(example_row)
    validate_meta_template_body(body_text, n_params)

    components: list[dict[str, Any]] = []
    hf = (header_format or "").strip().upper()
    if hf == "IMAGE":
        components.append({"type": "HEADER", "format": "IMAGE"})

    body_component: dict[str, Any] = {"type": "BODY", "text": body_text}
    if example_row:
        body_component["example"] = {"body_text": [example_row]}
    components.append(body_component)

    qrs = [str(x).strip()[:25] for x in (quick_reply_buttons or []) if str(x).strip()][:3]
    if qrs:
        components.append(
            {
                "type": "BUTTONS",
                "buttons": [{"type": "QUICK_REPLY", "text": t} for t in qrs],
            }
        )

    payload: dict[str, Any] = {
        "name": meta_name,
        "language": lang_norm,
        "category": category.strip().upper(),
        "components": components,
        "allow_category_change": True,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return parsed, lang_norm
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        msg = _meta_error_message_from_response_body(err_body, str(e))
        raise AppError(f"Meta (plantillas): {msg}", 502) from e
    except OSError as e:
        raise AppError(f"No se pudo contactar a Meta: {e}", 502) from e


_META_LIST_FIELDS = "name,status,language,category,id,quality_score,last_updated_time"


def list_waba_message_templates(settings: Settings) -> list[dict[str, Any]]:
    """Lista todas las plantillas de la WABA en Meta (paginado con paging.next)."""
    token = settings.whatsapp_access_token.strip()
    waba = settings.whatsapp_business_account_id.strip()
    if not token or not waba:
        raise AppError(
            "Falta configurar WhatsApp para plantillas Meta: WHATSAPP_ACCESS_TOKEN y "
            "WHATSAPP_BUSINESS_ACCOUNT_ID (o WABA_ID) en el servidor.",
            503,
        )
    version = (settings.whatsapp_graph_api_version or "v25.0").strip().lstrip("/")
    base = f"https://graph.facebook.com/{version}/{waba}/message_templates"
    qs: dict[str, str | int] = {"fields": _META_LIST_FIELDS, "limit": 100}
    url: str | None = f"{base}?{urlencode(qs)}"
    out: list[dict[str, Any]] = []
    while url:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                page = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            msg = _meta_error_message_from_response_body(err_body, str(e))
            raise AppError(f"Meta (listar plantillas): {msg}", 502) from e
        except OSError as e:
            raise AppError(f"No se pudo contactar a Meta: {e}", 502) from e

        rows = page.get("data")
        if isinstance(rows, list):
            out.extend([r for r in rows if isinstance(r, dict)])
        paging = page.get("paging")
        next_url = None
        if isinstance(paging, dict):
            nu = paging.get("next")
            if isinstance(nu, str) and nu.strip():
                next_url = nu.strip()
        url = next_url
    return out
