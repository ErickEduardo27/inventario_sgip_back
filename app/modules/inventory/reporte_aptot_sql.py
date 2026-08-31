"""SQL del reporte APTOT total (equivalente a ``sp_reporte_aptot_descarga_total`` en MySQL).

Tres clases en ``source_kind``:
- ``conciliado`` — bienes inventariados con ``itemcards.inv_sit = 'C'``
- ``sobrante``   — bienes inventariados con ``itemcards.inv_sit = 'S'``
- ``faltante``   — Margesi sin conciliar con inventario (sin vínculo en ``itemcards``).
  En datos legacy ``inv_sit`` puede ser ``C16``, ``C14``, etc.; no usar solo ``NULL``/``'N'``.
"""

from __future__ import annotations

# Etiqueta persona: apellidos + nombre (desde ``persons.extra``).
_PERSON_USUARIO = """
TRIM(BOTH FROM CONCAT(
    COALESCE(p.extra->>'apellido_paterno', ''), ' ',
    COALESCE(p.extra->>'apellido_materno', ''), ' , ',
    COALESCE(NULLIF(p.extra->>'nombre', ''), COALESCE(p.name, ''))
))
"""

_PERSON_USUARIO_PE = """
TRIM(BOTH FROM CONCAT(
    COALESCE(pe.extra->>'apellido_paterno', ''), ' ',
    COALESCE(pe.extra->>'apellido_materno', ''), ' , ',
    COALESCE(NULLIF(pe.extra->>'nombre', ''), COALESCE(pe.name, ''))
))
"""


def _ic(field: str) -> str:
    return f"COALESCE(itc.extra->>'{field}', '')"


def _piso_descripcion_itemcard_sql() -> str:
    """Descripción del piso (mismo local y código de piso que el ambiente físico)."""
    return """
(
    SELECT ep.description
    FROM enviroments ep
    WHERE ep.tenant_id = itc.tenant_id
      AND ep.establishment_id = ee.id
      AND COALESCE(TRIM(ep.floor), '') = COALESCE(TRIM(e.floor), '')
      AND NULLIF(TRIM(COALESCE(ep.description, '')), '') IS NOT NULL
    ORDER BY ep.code
    LIMIT 1
)
"""


def _piso_libre_ma_sql() -> str:
    return """
COALESCE(
    NULLIF(TRIM(
        CASE
            WHEN ma.extra IS NULL
              OR TRIM(COALESCE(ma.extra, '')) = ''
              OR UPPER(TRIM(ma.extra)) = 'NULL'
            THEN NULL
            ELSE ma.extra::jsonb->>'piso_libre'
        END
    ), ''),
    NULLIF(TRIM(COALESCE(itc.extra->>'piso_libre', '')), ''),
    ''
)
"""


def _piso_libre_m_sql() -> str:
    return """
COALESCE(
    NULLIF(TRIM(
        CASE
            WHEN m.extra IS NULL
              OR TRIM(COALESCE(m.extra, '')) = ''
              OR UPPER(TRIM(m.extra)) = 'NULL'
            THEN NULL
            ELSE m.extra::jsonb->>'piso_libre'
        END
    ), ''),
    ''
)
"""

# Bienes inventariados: conciliados (C) y sobrantes (S).
_ITEMCARD_SELECT = f"""
SELECT
    itc.tenant_id,
    CASE
        WHEN UPPER(TRIM(COALESCE(itc.inv_sit, ''))) = 'C' THEN 'conciliado'
        ELSE 'sobrante'
    END AS source_kind,
    itc.id AS source_ref_id,
    :refreshed_at AS refreshed_at,
    itc.id AS itemcard_id,
    itc.mar_sit_conta,
    itc.mar_cpat,
    itc.inv_sit AS state,
    itc.inv_sit,
    itc.inv_con,
    {_ic("mar_npri")},
    itc.mar_num,
    {_ic("mar_ccat")},
    itc.mar_des,
    {_ic("mar_esp")},
    {_ic("mar_est")},
    {_ic("mar_uso")},
    {_ic("mar_seg")},
    {_ic("mar_col")},
    {_ic("mar_mar")},
    {_ic("mar_mod")},
    {_ic("mar_tip")},
    {_ic("mar_ser")},
    {_ic("mar_med")},
    {_ic("mar_npla")},
    {_ic("mar_nmot")},
    {_ic("mar_ncha")},
    {_ic("mar_obs")},
    itc.inv_num_1,
    itc.inv_num_2,
    itc.inv_num,
    itc.created_at,
    itc.updated_at,
    ca.hoj_num,
    ca.hoj_fec,
    cc.code,
    cc.description,
    e.code,
    e.description,
    e.floor,
    e.floor,
    ee.description,
    ee.code,
    d.description,
    p.number,
    {_PERSON_USUARIO},
    ma.mar_cont_fec,
    ma.mar_cont_doc,
    ma.mar_cont_cta,
    ma.mar_cont_val,
    ma.mar_ccat,
    cct.description,
    de.description,
    est.description,
    env.description,
    {_PERSON_USUARIO_PE},
    ma.mar_des,
    ma.mar_mar,
    ma.mar_mod,
    ma.mar_tip,
    ma.mar_ser,
    est.code,
    est.id,
    ma.mar_obs,
    ma.local_libre,
    ma.ccosto_libre,
    ma.ambiente_libre,
    ma.usuario_libre,
    ma.campo_libre
FROM itemcards itc
LEFT JOIN cards ca ON ca.id = itc.id_card AND ca.tenant_id = itc.tenant_id
LEFT JOIN margesi ma ON ma.id = itc.id_margesi AND ma.tenant_id = itc.tenant_id
LEFT JOIN cost_center cc ON cc.id = ca.id_ccosto AND cc.tenant_id = itc.tenant_id
LEFT JOIN enviroments e ON e.id = ca.id_ambiente AND e.tenant_id = itc.tenant_id
LEFT JOIN establishments ee ON ee.id = e.establishment_id AND ee.tenant_id = itc.tenant_id
LEFT JOIN departments d ON d.id = ee.department_id
LEFT JOIN persons p ON p.id = ca.id_usuario AND p.tenant_id = itc.tenant_id
LEFT JOIN cost_center cct ON cct.code = ma.cct_cod AND cct.tenant_id = itc.tenant_id
LEFT JOIN enviroments env ON env.code = CONCAT(COALESCE(ma.amb_cod, ''), '01') AND env.tenant_id = itc.tenant_id
LEFT JOIN establishments est ON est.id = env.establishment_id AND est.tenant_id = itc.tenant_id
LEFT JOIN departments de ON de.id = est.department_id
LEFT JOIN persons pe ON pe.tenant_id = itc.tenant_id AND pe.extra->>'codigo_interno' = ma.usu_cod
WHERE itc.tenant_id = CAST(:tenant_id AS uuid)
  AND UPPER(TRIM(COALESCE(itc.inv_sit, ''))) IN ('C', 'S')
"""

# Patrimonio Margesi sin conciliar (faltantes): no enlazado a itemcards.
_MARGESI_FALTANTE_SELECT = f"""
SELECT
    m.tenant_id,
    'faltante'::varchar AS source_kind,
    m.id AS source_ref_id,
    :refreshed_at AS refreshed_at,
    NULL AS itemcard_id,
    NULL AS mar_sit_conta,
    NULL AS mar_cpat,
    CASE
        WHEN UPPER(TRIM(COALESCE(m.inv_sit, ''))) = 'N' THEN 'N'
        ELSE 'F'
    END AS state,
    NULL AS inv_sit,
    NULL AS inv_con,
    NULL AS mar_npri,
    NULL AS mar_num,
    NULL AS mar_ccat,
    NULL AS mar_des,
    NULL AS mar_esp,
    NULL AS mar_est,
    NULL AS mar_uso,
    NULL AS mar_seg,
    NULL AS mar_col,
    NULL AS mar_mar,
    NULL AS mar_mod,
    NULL AS mar_tip,
    NULL AS mar_ser,
    NULL AS mar_med,
    NULL AS mar_npla,
    NULL AS mar_nmot,
    NULL AS mar_ncha,
    NULL AS mar_obs,
    NULL AS inv_num_1,
    NULL AS inv_num_2,
    NULL AS inv_num,
    NULL AS item_created_at,
    NULL AS item_updated_at,
    NULL AS hoj_num,
    NULL AS hoj_fec,
    NULL AS area_code,
    NULL AS area_description,
    NULL AS ambiente_code,
    NULL AS ambiente_description,
    NULL AS ambiente_piso,
    NULL AS ambiente_piso_des,
    NULL AS local_description,
    NULL AS local_code,
    NULL AS local_departamento,
    NULL AS usuario_code,
    NULL AS usuario,
    m.mar_cont_fec,
    m.mar_cont_doc,
    m.mar_cont_cta,
    m.mar_cont_val,
    m.mar_ccat,
    cct.description,
    de.description,
    est.description,
    env.description,
    {_PERSON_USUARIO_PE},
    m.mar_des,
    m.mar_mar,
    m.mar_mod,
    m.mar_tip,
    m.mar_ser,
    est.code,
    NULL AS local_id,
    m.mar_obs,
    m.local_libre,
    m.ccosto_libre,
    m.ambiente_libre,
    m.usuario_libre,
    m.campo_libre
FROM margesi m
LEFT JOIN cost_center cct ON cct.code = m.cct_cod AND cct.tenant_id = m.tenant_id
LEFT JOIN enviroments env ON env.code = CONCAT(COALESCE(m.amb_cod, ''), '01') AND env.tenant_id = m.tenant_id
LEFT JOIN establishments est ON est.id = env.establishment_id AND est.tenant_id = m.tenant_id
LEFT JOIN departments de ON de.id = est.department_id
LEFT JOIN persons pe ON pe.tenant_id = m.tenant_id AND pe.extra->>'codigo_interno' = m.usu_cod
WHERE m.tenant_id = CAST(:tenant_id AS uuid)
  AND NOT EXISTS (
      SELECT 1
      FROM itemcards ic
      WHERE ic.tenant_id = m.tenant_id
        AND ic.id_margesi = m.id
  )
  AND NOT (
      UPPER(TRIM(COALESCE(m.inv_sit, ''))) = 'C'
      AND NULLIF(TRIM(COALESCE(m.inv_num, '')), '') IS NOT NULL
  )
"""

# Filtro por local (``sp_reporte_aptot_local``): físico en el local o Margesi apunta al local.
_LOCAL_FILTER_ITEMCARD = """
  AND (
    ee.id = %s
    OR (ee.id IS DISTINCT FROM %s AND est.id = %s)
  )
"""

# Margesi del local sin inventario: ``inv_sit`` NULL o no conciliable (``N``).
_LOCAL_FILTER_MARGESI = """
  AND est.id = %s
  AND (
    m.inv_sit IS NULL
    OR UPPER(TRIM(COALESCE(m.inv_sit, ''))) = 'N'
  )
"""

# Export CSV por local sin pasar por ``reporte_aptot_cache``.
_ITEMCARD_LIVE_EXPORT_SELECT = f"""
SELECT
    CASE
        WHEN UPPER(TRIM(COALESCE(itc.inv_sit, ''))) = 'C' THEN 'conciliado'
        ELSE 'sobrante'
    END AS source_kind,
    itc.id AS source_ref_id,
    NOW() AT TIME ZONE 'UTC' AS refreshed_at,
    itc.id AS itemcard_id,
    itc.mar_sit_conta,
    itc.mar_cpat,
    CASE
        WHEN ee.id IS DISTINCT FROM %s THEN 'CR'
        ELSE UPPER(TRIM(COALESCE(itc.inv_sit, '')))
    END AS state,
    itc.inv_sit,
    itc.inv_con,
    {_ic("mar_npri")} AS mar_npri,
    itc.mar_num,
    {_ic("mar_ccat")} AS mar_ccat,
    itc.mar_des,
    {_ic("mar_esp")} AS mar_esp,
    {_ic("mar_est")} AS mar_est,
    {_ic("mar_uso")} AS mar_uso,
    {_ic("mar_seg")} AS mar_seg,
    {_ic("mar_col")} AS mar_col,
    {_ic("mar_mar")} AS mar_mar,
    {_ic("mar_mod")} AS mar_mod,
    {_ic("mar_tip")} AS mar_tip,
    {_ic("mar_ser")} AS mar_ser,
    {_ic("mar_med")} AS mar_med,
    {_ic("mar_npla")} AS mar_npla,
    {_ic("mar_nmot")} AS mar_nmot,
    {_ic("mar_ncha")} AS mar_ncha,
    {_ic("mar_obs")} AS mar_obs,
    itc.inv_num_1,
    itc.inv_num_2,
    itc.inv_num,
    itc.created_at AS item_created_at,
    itc.updated_at AS item_updated_at,
    ca.hoj_num,
    ca.hoj_fec,
    cc.code AS area_code,
    cc.description AS area_description,
    e.code AS ambiente_code,
    e.description AS ambiente_description,
    e.floor AS ambiente_piso,
    COALESCE({_piso_descripcion_itemcard_sql()}, e.description, '') AS ambiente_piso_des,
    ee.description AS local_description,
    ee.code AS local_code,
    d.description AS local_departamento,
    p.number AS usuario_code,
    {_PERSON_USUARIO} AS usuario,
    ma.mar_cont_fec AS fecha_margesi,
    ma.mar_cont_doc AS doc_margesi,
    ma.mar_cont_cta AS cuenta_margesi,
    ma.mar_cont_val AS valor_margesi,
    ma.mar_ccat AS margesi_sbn,
    cct.description AS margesi_area,
    de.description AS margesi_departamento,
    est.description AS margesi_local,
    env.description AS margesi_ambiente,
    {_PERSON_USUARIO_PE} AS margesi_usuario,
    ma.mar_des AS margesi_description,
    ma.mar_mar AS margesi_marca,
    ma.mar_mod AS margesi_modelo,
    ma.mar_tip AS margesi_tipo,
    ma.mar_ser AS margesi_serie,
    est.code AS margesi_cod_local,
    est.id AS local_id,
    ma.mar_obs AS margesi_obs,
    ma.local_libre,
    ma.ccosto_libre,
    ma.ambiente_libre,
    ma.usuario_libre,
    ma.campo_libre,
    ma.mar_dep_acum,
    ma.mar_net_val,
    ma.inv_num AS margesi_inv_num,
    {_piso_libre_ma_sql()} AS piso_historico
FROM itemcards itc
LEFT JOIN cards ca ON ca.id = itc.id_card AND ca.tenant_id = itc.tenant_id
LEFT JOIN margesi ma ON ma.id = itc.id_margesi AND ma.tenant_id = itc.tenant_id
LEFT JOIN cost_center cc ON cc.id = ca.id_ccosto AND cc.tenant_id = itc.tenant_id
LEFT JOIN enviroments e ON e.id = ca.id_ambiente AND e.tenant_id = itc.tenant_id
LEFT JOIN establishments ee ON ee.id = e.establishment_id AND ee.tenant_id = itc.tenant_id
LEFT JOIN departments d ON d.id = ee.department_id
LEFT JOIN persons p ON p.id = ca.id_usuario AND p.tenant_id = itc.tenant_id
LEFT JOIN cost_center cct ON cct.code = ma.cct_cod AND cct.tenant_id = itc.tenant_id
LEFT JOIN enviroments env ON env.code = CONCAT(COALESCE(ma.amb_cod, ''), '01') AND env.tenant_id = itc.tenant_id
LEFT JOIN establishments est ON est.id = env.establishment_id AND est.tenant_id = itc.tenant_id
LEFT JOIN departments de ON de.id = est.department_id
LEFT JOIN persons pe ON pe.tenant_id = itc.tenant_id AND pe.extra->>'codigo_interno' = ma.usu_cod
WHERE itc.tenant_id = %s::uuid
  AND UPPER(TRIM(COALESCE(itc.inv_sit, ''))) IN ('C', 'S', 'F')
{_LOCAL_FILTER_ITEMCARD}
"""

_MARGESI_LIVE_EXPORT_SELECT = f"""
SELECT
    'faltante'::varchar AS source_kind,
    m.id AS source_ref_id,
    NOW() AT TIME ZONE 'UTC' AS refreshed_at,
    NULL AS itemcard_id,
    m.mar_sit_conta,
    NULL AS mar_cpat,
    CASE
        WHEN UPPER(TRIM(COALESCE(m.inv_sit, ''))) = 'N' THEN 'N'
        ELSE 'F'
    END AS state,
    NULL AS inv_sit,
    NULL AS inv_con,
    NULL AS mar_npri,
    NULL AS mar_num,
    NULL AS mar_ccat,
    NULL AS mar_des,
    NULL AS mar_esp,
    NULL AS mar_est,
    NULL AS mar_uso,
    NULL AS mar_seg,
    NULL AS mar_col,
    NULL AS mar_mar,
    NULL AS mar_mod,
    NULL AS mar_tip,
    NULL AS mar_ser,
    NULL AS mar_med,
    NULL AS mar_npla,
    NULL AS mar_nmot,
    NULL AS mar_ncha,
    NULL AS mar_obs,
    NULL AS inv_num_1,
    NULL AS inv_num_2,
    NULL AS inv_num,
    NULL AS item_created_at,
    NULL AS item_updated_at,
    NULL AS hoj_num,
    NULL AS hoj_fec,
    NULL AS area_code,
    NULL AS area_description,
    NULL AS ambiente_code,
    NULL AS ambiente_description,
    env.floor AS ambiente_piso,
    COALESCE(env.description, '') AS ambiente_piso_des,
    est.description AS local_description,
    est.code AS local_code,
    de.description AS local_departamento,
    NULL AS usuario_code,
    NULL AS usuario,
    m.mar_cont_fec AS fecha_margesi,
    m.mar_cont_doc AS doc_margesi,
    m.mar_cont_cta AS cuenta_margesi,
    m.mar_cont_val AS valor_margesi,
    m.mar_ccat AS margesi_sbn,
    cct.description AS margesi_area,
    de.description AS margesi_departamento,
    est.description AS margesi_local,
    env.description AS margesi_ambiente,
    {_PERSON_USUARIO_PE} AS margesi_usuario,
    m.mar_des AS margesi_description,
    m.mar_mar AS margesi_marca,
    m.mar_mod AS margesi_modelo,
    m.mar_tip AS margesi_tipo,
    m.mar_ser AS margesi_serie,
    est.code AS margesi_cod_local,
    NULL AS local_id,
    m.mar_obs AS margesi_obs,
    m.local_libre,
    m.ccosto_libre,
    m.ambiente_libre,
    m.usuario_libre,
    m.campo_libre,
    m.mar_dep_acum,
    m.mar_net_val,
    m.inv_num AS margesi_inv_num,
    {_piso_libre_m_sql()} AS piso_historico
FROM margesi m
LEFT JOIN cost_center cct ON cct.code = m.cct_cod AND cct.tenant_id = m.tenant_id
LEFT JOIN enviroments env ON env.code = CONCAT(COALESCE(m.amb_cod, ''), '01') AND env.tenant_id = m.tenant_id
LEFT JOIN establishments est ON est.id = env.establishment_id AND est.tenant_id = m.tenant_id
LEFT JOIN departments de ON de.id = est.department_id
LEFT JOIN persons pe ON pe.tenant_id = m.tenant_id AND pe.extra->>'codigo_interno' = m.usu_cod
WHERE m.tenant_id = %s::uuid
  AND NOT EXISTS (
      SELECT 1
      FROM itemcards ic
      WHERE ic.tenant_id = m.tenant_id
        AND ic.id_margesi = m.id
  )
{_LOCAL_FILTER_MARGESI}
"""

REPORTE_APTOT_LOCALES_LIVE_UNION_SQL = f"""
{_ITEMCARD_LIVE_EXPORT_SELECT}

UNION ALL

{_MARGESI_LIVE_EXPORT_SELECT}
"""

REPORTE_APTOT_INSERT_SQL = f"""
INSERT INTO reporte_aptot_cache (
    tenant_id,
    source_kind,
    source_ref_id,
    refreshed_at,
    itemcard_id,
    mar_sit_conta,
    mar_cpat,
    state,
    inv_sit,
    inv_con,
    mar_npri,
    mar_num,
    mar_ccat,
    mar_des,
    mar_esp,
    mar_est,
    mar_uso,
    mar_seg,
    mar_col,
    mar_mar,
    mar_mod,
    mar_tip,
    mar_ser,
    mar_med,
    mar_npla,
    mar_nmot,
    mar_ncha,
    mar_obs,
    inv_num_1,
    inv_num_2,
    inv_num,
    item_created_at,
    item_updated_at,
    hoj_num,
    hoj_fec,
    area_code,
    area_description,
    ambiente_code,
    ambiente_description,
    ambiente_piso,
    ambiente_piso_des,
    local_description,
    local_code,
    local_departamento,
    usuario_code,
    usuario,
    fecha_margesi,
    doc_margesi,
    cuenta_margesi,
    valor_margesi,
    margesi_sbn,
    margesi_area,
    margesi_departamento,
    margesi_local,
    margesi_ambiente,
    margesi_usuario,
    margesi_description,
    margesi_marca,
    margesi_modelo,
    margesi_tipo,
    margesi_serie,
    margesi_cod_local,
    local_id,
    margesi_obs,
    local_libre,
    ccosto_libre,
    ambiente_libre,
    usuario_libre,
    campo_libre
)
{_ITEMCARD_SELECT}

UNION ALL

{_MARGESI_FALTANTE_SELECT}
"""
