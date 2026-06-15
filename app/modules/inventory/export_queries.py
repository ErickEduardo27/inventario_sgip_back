"""Consultas SQL para exportación CSV (COPY). LEFT JOIN donde aporta etiquetas legibles."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.inventory_numbers import try_parse_inventory_number
from app.modules.inventory import models as m
from app.modules.inventory.schemas import RecordQuery


def _margesi_column_list() -> str:
    cols = [c.name for c in m.InvMargesiItem.__table__.columns if c.name != "tenant_id"]
    return ", ".join(f"m.{c}" for c in cols)


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
            COALESCE(ic.cnt, 0) AS items,
            COALESCE(est.code, '') AS codigo_local,
            COALESCE(est.description, '') AS local,
            COALESCE(env.code, '') AS codigo_ambiente,
            COALESCE(env.description, '') AS ambiente,
            COALESCE(cc.code, '') AS codigo_centro_costo,
            COALESCE(cc.description, '') AS centro_costo,
            COALESCE(p.number, '') AS documento_usuario,
            COALESCE(p.name, '') AS usuario,
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
        LEFT JOIN LATERAL (
            SELECT count(*)::int AS cnt
            FROM itemcards ic2
            WHERE ic2.id_card = c.id AND ic2.tenant_id = c.tenant_id
        ) ic ON true
"""

EXPORT_QUERIES["cards"] = (
    f"{_CARDS_EXPORT_SELECT} WHERE c.tenant_id = %s::uuid ORDER BY c.hoj_num, c.id",
    "hoja_captura_export",
)

_ITEM_CARDS_EXPORT_SELECT = """
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


def build_cards_export_query(tenant_id: UUID, q: RecordQuery) -> tuple[str, tuple[Any, ...], str]:
    """SQL parametrizado para exportar hojas con los mismos filtros que el listado."""
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

    sql = f"{_CARDS_EXPORT_SELECT} WHERE {' AND '.join(where)} ORDER BY c.hoj_num, c.id"
    return sql, tuple(params), "hoja_captura_export"


def build_item_cards_export_query(tenant_id: UUID, q: RecordQuery) -> tuple[str, tuple[Any, ...], str]:
    """SQL parametrizado para exportar bienes con los mismos filtros que el listado."""
    where = ["ic.tenant_id = %s::uuid"]
    params: list[Any] = [str(tenant_id)]
    allowed = {"inv_num", "mar_cpat", "mar_num", "mar_des", "inv_sit", "id_card", "num_card"}

    if q.inv_sit_filter in ("C", "S"):
        where.append("ic.inv_sit = %s")
        params.append(q.inv_sit_filter)

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
