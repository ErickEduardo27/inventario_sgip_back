"""Motor de detección y propuesta de Conciliación Margesi (Fase 1).

Filosofía: no buscar solo \"iguales\", sino evidencia suficiente de que el bien
inventariado es el mismo bien físico que el faltante Margesi.

NO concilia automáticamente: solo detecta, puntúa y propone.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Pesos configurables (no hardcodeados en múltiples sitios).
MATCH_WEIGHTS: dict[str, float] = {
    "serie_exacta": 40.0,
    "sbn_exacto": 22.0,
    "marca_modelo": 18.0,
    "modelo": 10.0,
    "local": 8.0,
    "responsable": 6.0,
    "estado_compatible": 6.0,
    "antiguedad_compatible": 4.0,
    # Penalizaciones (se restan)
    "estado_incompatible": -25.0,
    "antiguedad_muy_diferente": -15.0,
    "sbn_diferente": -50.0,  # bloqueo fuerte
}

# Umbrales de clasificación (configurables).
SCORE_STRONG = 70.0
SCORE_PROBABLE = 45.0

# Matriz de compatibilidad de estados (mar_est: N/B/R/M/I).
# compatible | revisar | incompatible
ESTADO_COMPAT: dict[tuple[str, str], str] = {
    ("B", "B"): "compatible",
    ("R", "R"): "compatible",
    ("M", "M"): "compatible",
    ("I", "I"): "compatible",
    ("N", "N"): "compatible",
    ("B", "R"): "compatible",
    ("R", "B"): "compatible",
    ("R", "M"): "revisar",
    ("M", "R"): "revisar",
    ("M", "B"): "incompatible",
    ("B", "M"): "incompatible",
    ("I", "B"): "incompatible",
    ("B", "I"): "incompatible",
    ("I", "R"): "revisar",
    ("R", "I"): "revisar",
    ("N", "B"): "revisar",
    ("B", "N"): "revisar",
}

ESTADO_LABELS = {
    "N": "Nuevo",
    "B": "Bueno",
    "R": "Regular",
    "M": "Malo",
    "I": "Inservible",
}


def normalize_text(value: Any) -> str:
    s = str(value or "").strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[\s\-_/\\|.,;:]+", "", s)
    return s


def normalize_serie(value: Any) -> str:
    return normalize_text(value)


def normalize_sbn(value: Any) -> str:
    digits = "".join(c for c in str(value or "") if c.isdigit())
    return digits


def normalize_model(value: Any) -> str:
    s = str(value or "").strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def model_similar(a: str, b: str) -> bool:
    na, nb = normalize_model(a), normalize_model(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Contención: "DELL LATITUDE 5420" vs "LATITUDE 5420"
    if na in nb or nb in na:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    inter = ta & tb
    # Al menos 2 tokens comunes o ratio alto
    return len(inter) >= 2 or (len(inter) / max(len(ta), len(tb)) >= 0.6)


def estado_compat(est_m: str | None, est_b: str | None) -> str:
    em = (est_m or "B").strip().upper()[:1] or "B"
    eb = (est_b or "B").strip().upper()[:1] or "B"
    return ESTADO_COMPAT.get((em, eb), "revisar")


def year_from_date(value: date | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.year
    raw = str(value).strip()
    if not raw:
        return None
    m = re.search(r"(19|20)\d{2}", raw)
    return int(m.group(0)) if m else None


@dataclass
class MatchEvidence:
    key: str
    label: str
    status: str  # match | partial | miss | penalty
    detail: str = ""
    weight: float = 0.0


@dataclass
class MatchProposal:
    margesi_id: int
    itemcard_id: int
    score: float
    tier: str  # fuerte | probable | revisar
    evidences: list[MatchEvidence] = field(default_factory=list)
    margesi: dict[str, Any] = field(default_factory=dict)
    bien: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "margesi_id": self.margesi_id,
            "itemcard_id": self.itemcard_id,
            "score": round(self.score, 1),
            "tier": self.tier,
            "evidences": [
                {
                    "key": e.key,
                    "label": e.label,
                    "status": e.status,
                    "detail": e.detail,
                    "weight": e.weight,
                }
                for e in self.evidences
            ],
            "margesi": self.margesi,
            "bien": self.bien,
            "summary": {
                "sbn": _ev_status(self.evidences, "sbn"),
                "serie": _ev_status(self.evidences, "serie"),
                "modelo": _ev_status(self.evidences, "modelo"),
                "marca_modelo": _ev_status(self.evidences, "marca_modelo"),
                "local": _ev_status(self.evidences, "local"),
                "responsable": _ev_status(self.evidences, "responsable"),
                "estado": _ev_status(self.evidences, "estado"),
                "antiguedad": _ev_status(self.evidences, "antiguedad"),
            },
        }


def _ev_status(evs: list[MatchEvidence], key: str) -> str:
    for e in evs:
        if e.key == key:
            return e.status
    return "miss"


def score_pair(
    *,
    sbn_m: str | None,
    sbn_b: str | None,
    serie_m: str | None,
    serie_b: str | None,
    marca_m: str | None,
    marca_b: str | None,
    modelo_m: str | None,
    modelo_b: str | None,
    local_m: str | None,
    local_b: str | None,
    resp_m: str | None,
    resp_b: str | None,
    estado_m: str | None,
    estado_b: str | None,
    year_m: int | None,
    year_b: int | None,
) -> tuple[float, list[MatchEvidence], str | None]:
    """Devuelve (score, evidencias, block_reason).

    Si SBN distinto y ambos presentes → block (no propuesta fuerte entre catálogos distintos).
    """
    evidences: list[MatchEvidence] = []
    score = 0.0

    ns_m, ns_b = normalize_sbn(sbn_m), normalize_sbn(sbn_b)
    if ns_m and ns_b:
        if ns_m == ns_b or ns_m[:8] == ns_b[:8]:
            w = MATCH_WEIGHTS["sbn_exacto"]
            score += w
            evidences.append(
                MatchEvidence("sbn", "Código SBN", "match", f"{ns_m} = {ns_b}", w)
            )
        else:
            # Bloqueo: no proponer entre catálogos distintos
            return 0.0, [
                MatchEvidence(
                    "sbn",
                    "Código SBN",
                    "penalty",
                    f"{ns_m} ≠ {ns_b}",
                    MATCH_WEIGHTS["sbn_diferente"],
                )
            ], "sbn_diferente"
    elif ns_m or ns_b:
        evidences.append(MatchEvidence("sbn", "Código SBN", "miss", "Solo un lado tiene SBN", 0))
    else:
        evidences.append(MatchEvidence("sbn", "Código SBN", "miss", "Sin SBN en ambos", 0))

    # Serie
    ser_m, ser_b = normalize_serie(serie_m), normalize_serie(serie_b)
    if ser_m and ser_b:
        if ser_m == ser_b:
            w = MATCH_WEIGHTS["serie_exacta"]
            score += w
            evidences.append(
                MatchEvidence("serie", "Serie", "match", f"{serie_m} ≈ {serie_b}", w)
            )
        else:
            evidences.append(
                MatchEvidence("serie", "Serie", "miss", f"{serie_m} ≠ {serie_b}", 0)
            )
    else:
        evidences.append(MatchEvidence("serie", "Serie", "miss", "Serie ausente en un lado", 0))

    # Marca + modelo
    marca_ok = bool(normalize_text(marca_m) and normalize_text(marca_b) and normalize_text(marca_m) == normalize_text(marca_b))
    modelo_ok = model_similar(modelo_m or "", modelo_b or "")
    if marca_ok and modelo_ok:
        w = MATCH_WEIGHTS["marca_modelo"]
        score += w
        evidences.append(
            MatchEvidence(
                "marca_modelo",
                "Marca + modelo",
                "match",
                f"{marca_m} {modelo_m} ≈ {marca_b} {modelo_b}",
                w,
            )
        )
    elif modelo_ok:
        w = MATCH_WEIGHTS["modelo"]
        score += w
        evidences.append(
            MatchEvidence("modelo", "Modelo", "partial", f"{modelo_m} ≈ {modelo_b}", w)
        )
        if normalize_text(marca_m) or normalize_text(marca_b):
            evidences.append(
                MatchEvidence(
                    "marca_modelo",
                    "Marca + modelo",
                    "miss",
                    f"Marca: {marca_m or '—'} vs {marca_b or '—'}",
                    0,
                )
            )
    else:
        evidences.append(MatchEvidence("modelo", "Modelo", "miss", "Modelo no similar", 0))

    # Local
    loc_m, loc_b = normalize_text(local_m), normalize_text(local_b)
    if loc_m and loc_b and loc_m == loc_b:
        w = MATCH_WEIGHTS["local"]
        score += w
        evidences.append(MatchEvidence("local", "Local", "match", str(local_m), w))
    elif loc_m or loc_b:
        evidences.append(
            MatchEvidence("local", "Local", "miss", f"{local_m or '—'} vs {local_b or '—'}", 0)
        )
    else:
        evidences.append(MatchEvidence("local", "Local", "miss", "Sin local", 0))

    # Responsable
    r_m, r_b = normalize_text(resp_m), normalize_text(resp_b)
    if r_m and r_b and (r_m == r_b or r_m in r_b or r_b in r_m):
        w = MATCH_WEIGHTS["responsable"]
        score += w
        evidences.append(MatchEvidence("responsable", "Responsable", "match", str(resp_m), w))
    else:
        evidences.append(
            MatchEvidence(
                "responsable",
                "Responsable",
                "miss",
                f"{resp_m or '—'} vs {resp_b or '—'}",
                0,
            )
        )

    # Estado
    compat = estado_compat(estado_m, estado_b)
    em = ESTADO_LABELS.get((estado_m or "B")[:1].upper(), estado_m or "—")
    eb = ESTADO_LABELS.get((estado_b or "B")[:1].upper(), estado_b or "—")
    if compat == "compatible":
        w = MATCH_WEIGHTS["estado_compatible"]
        score += w
        evidences.append(MatchEvidence("estado", "Estado", "match", f"{em} ↔ {eb}", w))
    elif compat == "incompatible":
        w = MATCH_WEIGHTS["estado_incompatible"]
        score += w
        evidences.append(MatchEvidence("estado", "Estado", "penalty", f"{em} ↔ {eb}", w))
    else:
        evidences.append(MatchEvidence("estado", "Estado", "partial", f"{em} ↔ {eb} (revisar)", 0))

    # Antigüedad
    if year_m and year_b:
        diff = abs(year_m - year_b)
        if diff <= 3:
            w = MATCH_WEIGHTS["antiguedad_compatible"]
            score += w
            evidences.append(
                MatchEvidence("antiguedad", "Antigüedad", "match", f"{year_m} vs {year_b}", w)
            )
        elif diff >= 10:
            w = MATCH_WEIGHTS["antiguedad_muy_diferente"]
            score += w
            evidences.append(
                MatchEvidence(
                    "antiguedad",
                    "Antigüedad",
                    "penalty",
                    f"{year_m} vs {year_b} (Δ{diff})",
                    w,
                )
            )
        else:
            evidences.append(
                MatchEvidence(
                    "antiguedad",
                    "Antigüedad",
                    "partial",
                    f"{year_m} vs {year_b} (Δ{diff})",
                    0,
                )
            )
    else:
        evidences.append(MatchEvidence("antiguedad", "Antigüedad", "miss", "Sin fecha", 0))

    return max(0.0, score), evidences, None


def classify_tier(score: float) -> str:
    if score >= SCORE_STRONG:
        return "fuerte"
    if score >= SCORE_PROBABLE:
        return "probable"
    return "revisar"
