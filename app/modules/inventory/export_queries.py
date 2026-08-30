"""Consultas SQL para exportación CSV (COPY). LEFT JOIN donde aporta etiquetas legibles."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.inventory_numbers import try_parse_inventory_number
from app.modules.inventory import models as m
from app.modules.inventory.schemas import RecordQuery


def _item_photo_filename_sql(extra_key: str, legacy_key: str, alias: str) -> str:
    """Nombre de archivo de foto almacenada en ``itemcards.extra`` (URL GCS, ruta o nombre)."""
    raw = f"NULLIF(TRIM(COALESCE(ic.extra->>'{extra_key}', ic.extra->>'{legacy_key}', '')), '')"
    path = f"split_part({raw}, '?', 1)"
    filename = f"reverse(split_part(reverse({path}), '/', 1))"
    return f"""CASE
        WHEN {raw} IS NULL THEN ''
        ELSE COALESCE({filename}, '')
    END AS {alias}"""


def _margesi_column_list() -> str:
    cols = [c.name for c in m.InvMargesiItem.__table__.columns if c.name != "tenant_id"]
    return ", ".join(f"m.{c}" for c in cols)


def _margesi_report_select_sql() -> str:
    return """
        COALESCE(m.mar_sit_conta, '') AS "Sit.Contable",
        COALESCE(m.inv_num_1::text, '') AS "Inv -1",
        COALESCE(m.inv_num_2::text, '') AS "Inv -2",
        COALESCE(m.inv_num::text, '') AS "N Inventario",
        COALESCE(m.mar_num, '') AS "Cod.Interno",
        COALESCE(m.mar_cpat, '') AS "Cod.SBN",
        COALESCE(m.mar_des, '') AS "Descripcion",
        COALESCE(m.mar_esp, '') AS "Especificacion",
        COALESCE(m.mar_est::text, '') AS "Estado",
        COALESCE(m.mar_uso::text, '') AS "Uso",
        COALESCE(m.mar_col, '') AS "Color",
        COALESCE(m.mar_mar, '') AS "Marca",
        COALESCE(m.mar_mod, '') AS "Modelo",
        COALESCE(m.mar_ser, '') AS "Serie",
        COALESCE(m.mar_med, '') AS "Medidas",
        COALESCE(m.mar_obs, '') AS "Observacion",
        COALESCE(m.mar_ano, '') AS "Año",
        COALESCE(m.mar_npla, '') AS "Placa",
        COALESCE(m.mar_nmot, '') AS "N Motor",
        COALESCE(m.mar_ncha, '') AS "N Chasis",
        COALESCE(est.code, m.amb_cod, '') AS "Cod.Local",
        COALESCE(est.description, '') AS "Local",
        COALESCE(m.local_libre, '') AS "Local Libre",
        COALESCE(
            CASE
                WHEN m.extra IS NULL
                  OR TRIM(COALESCE(m.extra, '')) = ''
                  OR UPPER(TRIM(m.extra)) = 'NULL'
                THEN NULL
                ELSE (m.extra::jsonb)->>'piso_libre'
            END,
            ''
        ) AS "Piso Libre",
        COALESCE(m.ambiente_libre, '') AS "Ambiente Libre",
        COALESCE(m.usuario_libre, '') AS "Usuario Libre",
        COALESCE(m.ccosto_libre, '') AS "Centro Costo Libre",
        COALESCE(m.mar_cont_doc, '') AS "Documento Contable",
        COALESCE(to_char(m.mar_cont_fec, 'YYYY-MM-DD'), '') AS "Fecha Contable",
        COALESCE(m.mar_ing_val::text, '') AS "Valor Adquisicion",
        COALESCE(m.mar_dep_acum::text, '') AS "Depreciacion Acumulada",
        COALESCE(m.mar_net_val::text, '') AS "Valor Neto"
    """


EXPORT_QUERIES: dict[str, tuple[str, str]] = {
    "establishments": (
        """
        SELECT
            e.code AS codigo_local,
            e.description AS descripcion,
            COALESCE(e.address, '') AS direccion,
            COALESCE(e.country_id, '') AS pais,
            COALESCE(e.district_id, '') AS ubigeo,
            COALESCE(e.email, '') AS email,
            COALESCE(e.telephone, '') AS telefono,
            COALESCE(e.latitude::text, '') AS latitud,
            COALESCE(e.longitude::text, '') AS longitud,
            COALESCE(dep.description, '') AS departamento,
            COALESCE(prov.description, '') AS provincia,
            COALESCE(dist.description, '') AS distrito,
            e.created_at AS fecha_creacion
        FROM establishments e
        LEFT JOIN departments dep ON dep.id = e.department_id
        LEFT JOIN provinces prov ON prov.id = e.province_id
        LEFT JOIN districts dist ON dist.id = e.district_id
        WHERE e.tenant_id = %s::uuid
        ORDER BY e.id
        """,
        "locales_export",
    ),
    "persons": (
        """
        SELECT
            COALESCE(p.extra->>'codigo_interno', '') AS codigo_persona,
            COALESCE(p.identity_document_type_id, '') AS tipo_documento,
            COALESCE(p.number, '') AS numero_documento,
            COALESCE(p.extra->>'apellido_paterno', '') AS apellido_paterno,
            COALESCE(p.extra->>'apellido_materno', '') AS apellido_materno,
            COALESCE(p.extra->>'nombre', COALESCE(p.name, '')) AS nombres,
            COALESCE(p.extra->>'genero', '') AS genero,
            COALESCE(p.extra->>'movil', '') AS celular,
            COALESCE(p.telephone, '') AS telefono_fijo,
            COALESCE(p.extra->>'anexo', '') AS anexo,
            COALESCE(p.email, '') AS correo,
            COALESCE(p.extra->>'condicion', '') AS condicion,
            COALESCE(p.extra->>'job', COALESCE(p.type, '')) AS cargo,
            COALESCE(p.enviroment_code, '') AS codigo_ambiente,
            COALESCE(p.extra->>'boss_code', '') AS codigo_responsable,
            COALESCE(p.cc_code, '') AS codigo_centro_costo,
            COALESCE(p.observation, '') AS observaciones,
            p.created_at AS fecha_creacion
        FROM persons p
        WHERE p.tenant_id = %s::uuid
        ORDER BY p.id
        """,
        "personas_export",
    ),
    "cost_centers": (
        """
        SELECT
            cc.code AS codigo_cc,
            cc.description AS descripcion,
            COALESCE(enc.number, '') AS documento_encargado,
            COALESCE(parent.code, '') AS codigo_cc_principal,
            COALESCE(cc.personal_id::text, '') AS id_personal_encargado,
            COALESCE(enc.name, '') AS encargado,
            COALESCE(cc.principal_center_id::text, '') AS id_cc_principal,
            cc.created_at AS fecha_creacion
        FROM cost_center cc
        LEFT JOIN persons enc ON enc.id = cc.personal_id AND enc.tenant_id = cc.tenant_id
        LEFT JOIN cost_center parent ON parent.id = cc.principal_center_id AND parent.tenant_id = cc.tenant_id
        WHERE cc.tenant_id = %s::uuid
        ORDER BY cc.id
        """,
        "centros_costo_export",
    ),
    "environments": (
        """
        SELECT
            env.code AS codigo_ambiente,
            COALESCE(env.description, '') AS descripcion,
            COALESCE(est.code, '') AS codigo_local,
            COALESCE(est.description, '') AS local,
            COALESCE(env.floor, '') AS piso,
            COALESCE(env.observation, '') AS observacion,
            COALESCE(env.telephone, '') AS telefono,
            COALESCE(env.anex, '') AS anexo,
            env.created_at AS fecha_creacion
        FROM enviroments env
        LEFT JOIN establishments est
            ON est.id = env.establishment_id AND est.tenant_id = env.tenant_id
        WHERE env.tenant_id = %s::uuid
        ORDER BY env.id
        """,
        "ambientes_export",
    ),
    "list_sbn": (
        """
        SELECT
            ls.code AS codigo_sbn,
            COALESCE(ls.cat_des, '') AS descripcion,
            COALESCE(ls.cat_ulti, '') AS correlativo,
            COALESCE(ls.cat_clase, '') AS clase,
            COALESCE(ls.cat_cat, '') AS pertenece_cat_original,
            COALESCE(ls.cat_cont_vutil, '') AS vida_util,
            COALESCE(ls.cat_cont_pdep, '') AS porcentaje_depreciacion_anual,
            COALESCE(ls.cat_cont_gasto, '') AS clasificador_gastos,
            COALESCE(ls.cat_cont_cta_a, '') AS cuenta_activo,
            COALESCE(ls.cat_cont_cta_o, '') AS cuenta_orden,
            COALESCE(ls.cat_cont_valp, '') AS valor_aproximado,
            COALESCE(ls.cat_uso, '') AS flag_uso,
            COALESCE(ls.cat_raa, '') AS flag_raee,
            COALESCE(ls.cat_obs, '') AS observaciones,
            ls.created_at AS fecha_creacion
        FROM list_sbn ls
        WHERE ls.tenant_id = %s::uuid
        ORDER BY ls.id
        """,
        "catalogo_sbn_export",
    ),
    "margesi": (
        f"""
        SELECT
            {_margesi_column_list()},
            COALESCE(m.extra::text, '') AS extra_json
        FROM margesi m
        WHERE m.tenant_id = %s::uuid
        ORDER BY m.id
        """,
        "margesi_export",
    ),
}

_CARDS_EXPORT_SELECT = """
        SELECT
            c.hoj_num AS numero_hoja,
            CASE WHEN c.state = 2 THEN 'Cerrada' ELSE 'Abierta' END AS estado,
            c.hoj_fec AS fecha,
            c.hoj_can_tot AS cantidad_total,
            COALESCE(ic.cnt, 0) AS total_bienes,
            COALESCE(ic.cnt_con, 0) AS conciliados,
            COALESCE(ic.cnt_sob, 0) AS sobrantes,
            COALESCE(est.code, '') AS codigo_local,
            COALESCE(est.description, '') AS local,
            COALESCE(env.code, '') AS codigo_ambiente,
            COALESCE(env.description, '') AS ambiente,
            COALESCE(cc.code, '') AS codigo_centro_costo,
            COALESCE(cc.description, '') AS centro_costo,
            COALESCE(p.number, '') AS documento_usuario,
            COALESCE(p.name, '') AS usuario,
            COALESCE(p_inv_doc.number, '') AS dni_inventariador,
            COALESCE(p_inv_doc.name, u_inv.full_name, '') AS nombre_inventariador,
            COALESCE(p_dig_doc.number, '') AS dni_digitador,
            COALESCE(p_dig_doc.name, u_dig.full_name, '') AS nombre_digitador,
            CASE WHEN c.flag_firma THEN 'Si' ELSE 'No' END AS firma,
            COALESCE(c.nota_interna, '') AS nota_interna,
            COALESCE(c.nota_ficha, '') AS nota_ficha,
            COALESCE(c.pdf, '') AS pdf_hoja,
            COALESCE(c.pdf2, '') AS pdf_ficha,
            to_char(c.created_at AT TIME ZONE 'America/Lima', 'DD/MM/YYYY HH24:MI') AS fecha_creacion
        FROM cards c
        LEFT JOIN enviroments env ON env.id = c.id_ambiente AND env.tenant_id = c.tenant_id
        LEFT JOIN establishments est ON est.id = env.establishment_id AND est.tenant_id = c.tenant_id
        LEFT JOIN cost_center cc ON cc.id = c.id_ccosto AND cc.tenant_id = c.tenant_id
        LEFT JOIN persons p ON p.id = c.id_usuario AND p.tenant_id = c.tenant_id
        LEFT JOIN users u_inv ON u_inv.id = c.id_inventariador AND u_inv.tenant_id = c.tenant_id
        LEFT JOIN users u_dig ON u_dig.id = c.id_digitador AND u_dig.tenant_id = c.tenant_id
        LEFT JOIN LATERAL (
            SELECT pi.number, pi.name
            FROM persons pi
            WHERE pi.tenant_id = c.tenant_id
              AND u_inv.id IS NOT NULL
              AND (
                (
                    NULLIF(pi.email, '') IS NOT NULL
                    AND u_inv.email IS NOT NULL
                    AND lower(pi.email) = lower(u_inv.email)
                )
                OR pi.name = u_inv.full_name
              )
            LIMIT 1
        ) p_inv_doc ON true
        LEFT JOIN LATERAL (
            SELECT pi.number, pi.name
            FROM persons pi
            WHERE pi.tenant_id = c.tenant_id
              AND u_dig.id IS NOT NULL
              AND (
                (
                    NULLIF(pi.email, '') IS NOT NULL
                    AND u_dig.email IS NOT NULL
                    AND lower(pi.email) = lower(u_dig.email)
                )
                OR pi.name = u_dig.full_name
              )
            LIMIT 1
        ) p_dig_doc ON true
        LEFT JOIN LATERAL (
            SELECT
                count(*)::int AS cnt,
                count(*) FILTER (WHERE ic2.inv_sit = 'C')::int AS cnt_con,
                count(*) FILTER (WHERE ic2.inv_sit = 'S')::int AS cnt_sob
            FROM itemcards ic2
            WHERE ic2.id_card = c.id AND ic2.tenant_id = c.tenant_id
        ) ic ON true
"""

EXPORT_QUERIES["cards"] = (
    f"{_CARDS_EXPORT_SELECT} WHERE c.tenant_id = %s::uuid ORDER BY c.hoj_num, c.id",
    "hoja_captura_export",
)

_ITEM_CARDS_EXPORT_SELECT = f"""
        SELECT
            ic.id AS id_bien,
            COALESCE(c.hoj_num::text, '') AS numero_hoja,
            COALESCE(ic.inv_num::text, '') AS numero_inventario,
            COALESCE(ic.mar_sit_conta, '') AS situacion_contable,
            COALESCE(ic.inv_sit, '') AS situacion,
            CASE WHEN ic.inv_con = '1' THEN 'Si' ELSE COALESCE(ic.inv_con, '') END AS conciliado,
            COALESCE(ic.mar_num, '') AS codigo_interno,
            COALESCE(ic.extra->>'mar_ccat', '') AS etiqueta_fisica,
            COALESCE(ic.mar_cpat, '') AS codigo_sbn,
            COALESCE(ic.mar_des, '') AS descripcion,
            COALESCE(ic.extra->>'mar_est', '') AS estado,
            COALESCE(ic.extra->>'mar_uso', '') AS uso,
            COALESCE(ic.extra->>'mar_seg', '') AS seguro,
            COALESCE(ic.extra->>'mar_col', '') AS color,
            COALESCE(ic.extra->>'mar_mar', '') AS marca,
            COALESCE(ic.extra->>'mar_mod', '') AS modelo,
            COALESCE(ic.extra->>'mar_tip', '') AS tipo,
            COALESCE(ic.extra->>'mar_ser', '') AS serie,
            COALESCE(ic.inv_num_1, '') AS inv_num_1,
            COALESCE(ic.inv_num_2, '') AS inv_num_2,
            COALESCE(u_inv.full_name, '') AS inventariador,
            COALESCE(u_dig.full_name, '') AS digitador,
            COALESCE(ic.extra->>'mar_ano', '') AS vehiculo_ano,
            COALESCE(ic.extra->>'mar_npla', ic.extra->>'num_placa', '') AS vehiculo_placa,
            COALESCE(ic.extra->>'mar_nmot', '') AS vehiculo_motor,
            COALESCE(ic.extra->>'mar_ncha', '') AS vehiculo_chasis,
            COALESCE(est.code, '') AS codigo_local,
            COALESCE(est.description, '') AS local,
            COALESCE(env.code, '') AS codigo_ambiente,
            COALESCE(env.description, '') AS ambiente,
            COALESCE(cc.code, '') AS codigo_centro_costo,
            COALESCE(cc.description, '') AS centro_costo,
            COALESCE(p.number, '') AS documento_usuario,
            COALESCE(p.name, '') AS usuario,
            {_item_photo_filename_sql("mar_foto", "foto_bien", "foto_1")},
            {_item_photo_filename_sql("mar_foto2", "foto2_bien", "foto_2")},
            {_item_photo_filename_sql("mar_foto3", "foto3_bien", "foto_3")},
            to_char(ic.created_at AT TIME ZONE 'America/Lima', 'DD/MM/YYYY HH24:MI') AS fecha_creacion
        FROM itemcards ic
        LEFT JOIN cards c ON c.id = ic.id_card AND c.tenant_id = ic.tenant_id
        LEFT JOIN enviroments env ON env.id = c.id_ambiente AND env.tenant_id = c.tenant_id
        LEFT JOIN establishments est ON est.id = env.establishment_id AND est.tenant_id = c.tenant_id
        LEFT JOIN cost_center cc ON cc.id = c.id_ccosto AND cc.tenant_id = c.tenant_id
        LEFT JOIN persons p ON p.id = c.id_usuario AND p.tenant_id = c.tenant_id
        LEFT JOIN users u_inv ON u_inv.id = c.id_inventariador AND u_inv.tenant_id = c.tenant_id
        LEFT JOIN users u_dig ON u_dig.id = c.id_digitador AND u_dig.tenant_id = c.tenant_id
"""

EXPORT_QUERIES.update({
    "item_cards": (
        f"{_ITEM_CARDS_EXPORT_SELECT} WHERE ic.tenant_id = %s::uuid ORDER BY ic.id DESC",
        "bienes_inventariados_export",
    ),
    "reporte_aptot": (
        """
        SELECT
            source_kind,
            source_ref_id,
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
            campo_libre,
            refreshed_at
        FROM reporte_aptot_cache
        WHERE tenant_id = %s::uuid
        ORDER BY source_kind, source_ref_id
        """,
        "reporte_aptot_export",
    ),
})


_REPORTE_APTOT_CACHE_COLUMNS = """
            source_kind,
            source_ref_id,
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
            campo_libre,
            refreshed_at
"""


def build_reporte_aptot_locales_export_query(
    tenant_id: UUID,
    establishment_id: int,
) -> tuple[str, tuple[Any, ...], str]:
    """CSV/Excel APTOT filtrado por local, generado en vivo (sin cache global)."""
    from app.modules.inventory.reporte_aptot_local_status import _SIT_CONT_SQL, _SIT_PAT_SQL
    from app.modules.inventory.reporte_aptot_sql import REPORTE_APTOT_LOCALES_LIVE_UNION_SQL

    tid = str(tenant_id)
    est_id = int(establishment_id)
    sql = f"""
        SELECT
            aptot.source_kind,
            aptot.source_ref_id,
            aptot.itemcard_id,
            aptot.mar_sit_conta,
            aptot.mar_cpat,
            aptot.state,
            aptot.inv_sit,
            aptot.inv_con,
            aptot.mar_npri,
            aptot.mar_num,
            aptot.mar_ccat,
            aptot.mar_des,
            aptot.mar_esp,
            aptot.mar_est,
            aptot.mar_uso,
            aptot.mar_seg,
            aptot.mar_col,
            aptot.mar_mar,
            aptot.mar_mod,
            aptot.mar_tip,
            aptot.mar_ser,
            aptot.mar_med,
            aptot.mar_npla,
            aptot.mar_nmot,
            aptot.mar_ncha,
            aptot.mar_obs,
            aptot.inv_num_1,
            aptot.inv_num_2,
            aptot.inv_num,
            aptot.item_created_at,
            aptot.item_updated_at,
            aptot.hoj_num,
            aptot.hoj_fec,
            aptot.area_code,
            aptot.area_description,
            aptot.ambiente_code,
            aptot.ambiente_description,
            aptot.ambiente_piso,
            aptot.ambiente_piso_des,
            aptot.local_description,
            aptot.local_code,
            aptot.local_departamento,
            aptot.usuario_code,
            aptot.usuario,
            aptot.fecha_margesi,
            aptot.doc_margesi,
            aptot.cuenta_margesi,
            aptot.valor_margesi,
            aptot.margesi_sbn,
            aptot.margesi_area,
            aptot.margesi_departamento,
            aptot.margesi_local,
            aptot.margesi_ambiente,
            aptot.margesi_usuario,
            aptot.margesi_description,
            aptot.margesi_marca,
            aptot.margesi_modelo,
            aptot.margesi_tipo,
            aptot.margesi_serie,
            aptot.margesi_cod_local,
            aptot.local_id,
            aptot.margesi_obs,
            aptot.local_libre,
            aptot.ccosto_libre,
            aptot.ambiente_libre,
            aptot.usuario_libre,
            aptot.campo_libre,
            aptot.refreshed_at,
            {_SIT_PAT_SQL} AS "SIT_PAT",
            {_SIT_CONT_SQL} AS "SIT_CONT"
        FROM (
{REPORTE_APTOT_LOCALES_LIVE_UNION_SQL}
        ) aptot
        ORDER BY aptot.source_kind, aptot.source_ref_id
    """
    params: tuple[Any, ...] = (
        est_id,
        tid,
        est_id,
        est_id,
        est_id,
        tid,
        est_id,
    )
    return sql, params, "reporte_aptot_locales_export"


def build_cards_export_query(tenant_id: UUID, q: RecordQuery) -> tuple[str, tuple[Any, ...], str]:
    where, params = _build_cards_list_where(tenant_id, q)
    sql = f"{_CARDS_EXPORT_SELECT} WHERE {' AND '.join(where)} ORDER BY c.hoj_num, c.id"
    return sql, tuple(params), "hoja_captura_export"


def _build_cards_list_where(tenant_id: UUID, q: RecordQuery) -> tuple[list[str], list[Any]]:
    where = ["c.tenant_id = %s::uuid"]
    params: list[Any] = [str(tenant_id)]

    if q.flag_firma is not None:
        where.append("c.flag_firma = %s")
        params.append(q.flag_firma)

    term = (q.search or "").strip()
    if term:
        pattern = f"%{term}%"
        where.append(
            """(
                CAST(c.hoj_num AS text) ILIKE %s
                OR c.nota_interna ILIKE %s
                OR c.nota_ficha ILIKE %s
                OR env.code ILIKE %s
                OR env.description ILIKE %s
                OR cc.code ILIKE %s
                OR cc.description ILIKE %s
            )"""
        )
        params.extend([pattern] * 7)
    elif q.value not in (None, ""):
        allowed = {"hoj_num", "state", "nota_interna"}
        col = q.column if q.column in allowed else "hoj_num"
        if col == "hoj_num":
            parsed = try_parse_inventory_number(q.value)
            if parsed is not None:
                where.append("c.hoj_num = %s")
                params.append(parsed)
            else:
                where.append("CAST(c.hoj_num AS text) ILIKE %s")
                params.append(f"%{q.value}%")
        elif col == "state":
            where.append("CAST(c.state AS text) ILIKE %s")
            params.append(f"%{q.value}%")
        else:
            where.append(f"c.{col} ILIKE %s")
            params.append(f"%{q.value}%")

    return where, params


_HOJA_CAPTURA_BIENES_EXPORT_SELECT = """
        SELECT
            c.hoj_num AS numero_hoja,
            ic.inv_num AS numero_inventario,
            COALESCE(ic.mar_des, m.mar_des, ic.extra->>'mar_des', '') AS descripcion,
            COALESCE(m.mar_mar, ic.extra->>'mar_mar', '') AS marca,
            COALESCE(m.mar_mod, ic.extra->>'mar_mod', '') AS modelo,
            COALESCE(m.mar_ser, ic.extra->>'mar_ser', '') AS serie,
            COALESCE(ic.mar_cpat, '') AS codigo_sbn,
            COALESCE(ic.mar_num, '') AS codigo_interno,
            COALESCE(m.mar_cont_val::text, NULLIF(ic.extra->>'mar_cont_val', ''), '') AS valor_contable,
            COALESCE(m.mar_net_val::text, NULLIF(ic.extra->>'mar_net_val', ''), '') AS valor_neto,
            COALESCE(est.code, '') AS codigo_local,
            COALESCE(env.code, '') AS codigo_ambiente,
            COALESCE(cc.code, '') AS codigo_centro_costo,
            to_char(ic.created_at AT TIME ZONE 'America/Lima', 'DD/MM/YYYY HH24:MI') AS fecha_creacion
        FROM itemcards ic
        INNER JOIN cards c ON c.id = ic.id_card AND c.tenant_id = ic.tenant_id
        LEFT JOIN margesi m ON m.id = ic.id_margesi AND m.tenant_id = ic.tenant_id
        LEFT JOIN enviroments env ON env.id = c.id_ambiente AND env.tenant_id = c.tenant_id
        LEFT JOIN establishments est ON est.id = env.establishment_id AND est.tenant_id = c.tenant_id
        LEFT JOIN cost_center cc ON cc.id = c.id_ccosto AND cc.tenant_id = c.tenant_id
"""


def build_hoja_captura_bienes_export_query(tenant_id: UUID, q: RecordQuery) -> tuple[str, tuple[Any, ...], str]:
    """Bienes de las hojas que coinciden con los mismos filtros del listado/export de hojas."""
    where, params = _build_cards_list_where(tenant_id, q)
    where[0] = "ic.tenant_id = %s::uuid"
    sql = f"{_HOJA_CAPTURA_BIENES_EXPORT_SELECT} WHERE {' AND '.join(where)} ORDER BY c.hoj_num, ic.inv_num"
    return sql, tuple(params), "hoja_captura_bienes_export"


def build_margesi_export_query(
    tenant_id: UUID,
    q: RecordQuery,
    *,
    layout: str | None = None,
) -> tuple[str, tuple[Any, ...], str]:
    """SQL parametrizado para exportar margesi con los mismos filtros que el listado."""
    export_layout = layout or q.export_layout or "full"
    where = ["m.tenant_id = %s::uuid"]
    params: list[Any] = [str(tenant_id)]
    allowed = {"inv_num", "mar_cpat", "mar_des", "inv_sit", "mar_num", "mar_mar", "mar_mod", "inv_hoj"}

    if q.inv_sit_filter == "C":
        where.append("m.inv_sit = %s")
        params.append("C")
    elif q.inv_sit_filter in ("F", "S"):
        where.append(
            "(m.inv_sit IS NULL OR TRIM(COALESCE(m.inv_sit, '')) = '' OR m.inv_sit IN ('-', '—', '–'))"
        )
    elif q.inv_sit_filter == "N":
        where.append("m.inv_sit = %s")
        params.append("N")

    local_code = (q.local_code or "").strip()
    if local_code:
        where.append("m.amb_cod = %s")
        params.append(local_code)

    term = (q.search or "").strip()
    if term:
        like = f"%{term}%"
        where.append(
            """(
            m.inv_num ILIKE %s OR m.mar_cpat ILIKE %s OR m.mar_des ILIKE %s
            OR m.mar_num ILIKE %s OR m.mar_mar ILIKE %s OR m.mar_mod ILIKE %s OR m.inv_hoj ILIKE %s
        )"""
        )
        params.extend([like] * 7)
    elif q.value not in (None, ""):
        col = q.column if q.column in allowed else "mar_cpat"
        where.append(f"m.{col} ILIKE %s")
        params.append(f"%{q.value}%")

    if export_layout == "report":
        select_sql = _margesi_report_select_sql()
        from_sql = """
        FROM margesi m
        LEFT JOIN establishments est
            ON est.tenant_id = m.tenant_id AND est.code = m.amb_cod
        """
        filename_base = "margesi_reporte"
    else:
        select_sql = f"""
            {_margesi_column_list()},
            COALESCE(m.extra::text, '') AS extra_json
        """
        from_sql = "FROM margesi m"
        filename_base = "margesi_export"

    sql = f"""
        SELECT
            {select_sql}
        {from_sql}
        WHERE {' AND '.join(where)}
        ORDER BY m.id
    """
    return sql, tuple(params), filename_base


def build_item_cards_export_query(tenant_id: UUID, q: RecordQuery) -> tuple[str, tuple[Any, ...], str]:
    """SQL parametrizado para exportar bienes con los mismos filtros que el listado."""
    where = ["ic.tenant_id = %s::uuid"]
    params: list[Any] = [str(tenant_id)]
    allowed = {"inv_num", "mar_cpat", "mar_num", "mar_des", "inv_sit", "id_card", "num_card"}

    if q.inv_sit_filter in ("C", "S"):
        where.append("ic.inv_sit = %s")
        params.append(q.inv_sit_filter)

    if q.establishment_id is not None:
        where.append("env.establishment_id = %s")
        params.append(q.establishment_id)
    else:
        local_code = (q.local_code or "").strip()
        if local_code:
            where.append("est.code = %s")
            params.append(local_code)

    if q.column == "num_card" and q.value not in (None, ""):
        hoj_n = try_parse_inventory_number(q.value)
        if hoj_n is not None:
            where.append(
                """ic.id_card IN (
                    SELECT c2.id FROM cards c2
                    WHERE c2.tenant_id = %s::uuid AND c2.hoj_num = %s
                )"""
            )
            params.extend([str(tenant_id), hoj_n])
        else:
            where.append("ic.id = -1")
    elif q.column == "id_card" and q.value not in (None, ""):
        try:
            cid = int(q.value)
        except ValueError:
            cid = -1
        where.append("ic.id_card = %s")
        params.append(cid)
    elif q.value not in (None, ""):
        col = q.column if q.column in allowed else "inv_num"
        if col == "inv_num":
            parsed = try_parse_inventory_number(q.value)
            if parsed is not None:
                where.append("ic.inv_num = %s")
                params.append(parsed)
            else:
                where.append("CAST(ic.inv_num AS text) ILIKE %s")
                params.append(f"%{q.value}%")
        elif col == "id_card":
            try:
                cid = int(q.value)
            except ValueError:
                cid = -1
            where.append("ic.id_card = %s")
            params.append(cid)
        else:
            where.append(f"ic.{col} ILIKE %s")
            params.append(f"%{q.value}%")

    sql = f"{_ITEM_CARDS_EXPORT_SELECT} WHERE {' AND '.join(where)} ORDER BY ic.id DESC"
    return sql, tuple(params), "bienes_inventariados_export"


def get_export_query(module: str) -> tuple[str, str]:
    try:
        return EXPORT_QUERIES[module]
    except KeyError as exc:
        raise ValueError(f"Módulo de exportación desconocido: {module}") from exc
