"""Reglas SIT_PAT / SIT_CONT del reporte APTOT por local (equivalente Blade legacy)."""

from __future__ import annotations

# Colores de fila Excel según SIT_PAT (AptotLocalExport.php).
APTOT_LOCAL_SIT_PAT_ROW_COLORS: dict[str, str | None] = {
    "FALTANTE CONCILIADO": "D9D9D9",
    "SOBRANTE CONCILIADO": "FCF8C0",
    "CONCILIADO": "FFFFFF",
    "SOBRANTE": "DAEEF3",
    "FALTANTE": "FDE9D9",
}

# Expresiones SQL sobre alias ``aptot`` (state, local_code, margesi_cod_local).
_SIT_PAT_SQL = """
CASE
    WHEN aptot.state = 'N' THEN 'NO CONCIABLE'
    WHEN aptot.state = 'CR'
         AND NULLIF(TRIM(COALESCE(aptot.margesi_cod_local, '')), '') IS NOT NULL
        THEN 'FALTANTE CONCILIADO'
    WHEN aptot.state = 'C'
         AND NULLIF(TRIM(COALESCE(aptot.margesi_cod_local, '')), '') IS NOT NULL
         AND TRIM(COALESCE(aptot.margesi_cod_local, ''))
             IS DISTINCT FROM TRIM(COALESCE(aptot.local_code, ''))
        THEN 'SOBRANTE CONCILIADO'
    WHEN aptot.state = 'C' THEN 'CONCILIADO'
    WHEN aptot.state = 'S' THEN 'SOBRANTE'
    WHEN aptot.state = 'F' THEN 'FALTANTE'
    ELSE COALESCE(aptot.state, '')
END
"""

_SIT_CONT_SQL = """
CASE
    WHEN aptot.state = 'N' THEN 'CONTABLE'
    WHEN aptot.state = 'S' THEN 'SOBRANTE'
    WHEN aptot.state = 'C'
         AND NULLIF(TRIM(COALESCE(aptot.margesi_cod_local, '')), '') IS NOT NULL
         AND TRIM(COALESCE(aptot.margesi_cod_local, ''))
             IS DISTINCT FROM TRIM(COALESCE(aptot.local_code, ''))
        THEN 'CONTABLE.OTRO'
    ELSE 'CONTABLE'
END
"""
