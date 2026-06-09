"""Consultas SQL para exportación CSV (COPY). LEFT JOIN donde aporta etiquetas legibles."""

from __future__ import annotations

from app.modules.inventory import models as m


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
    "cards": (
        """
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
            c.created_at AS fecha_creacion
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
        WHERE c.tenant_id = %s::uuid
        ORDER BY c.id
        """,
        "hoja_captura_export",
    ),
    "item_cards": (
        """
        SELECT
            ic.id AS id_bien,
            COALESCE(c.hoj_num, '') AS numero_hoja,
            COALESCE(ic.inv_num, '') AS numero_inventario,
            COALESCE(ic.mar_sit_conta, '') AS situacion_contable,
            COALESCE(ic.inv_sit, '') AS situacion,
            CASE WHEN ic.inv_con = '1' THEN 'Si' ELSE COALESCE(ic.inv_con, '') END AS conciliado,
            COALESCE(ic.mar_num, '') AS codigo_interno,
            COALESCE(ic.extra->>'mar_eti', '') AS etiqueta_fisica,
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
            COALESCE(est.code, '') AS codigo_local,
            COALESCE(est.description, '') AS local,
            COALESCE(env.code, '') AS codigo_ambiente,
            COALESCE(env.description, '') AS ambiente,
            COALESCE(cc.code, '') AS codigo_centro_costo,
            COALESCE(cc.description, '') AS centro_costo,
            COALESCE(p.number, '') AS documento_usuario,
            COALESCE(p.name, '') AS usuario,
            ic.created_at AS fecha_creacion
        FROM itemcards ic
        LEFT JOIN cards c ON c.id = ic.id_card AND c.tenant_id = ic.tenant_id
        LEFT JOIN enviroments env ON env.id = c.id_ambiente AND env.tenant_id = c.tenant_id
        LEFT JOIN establishments est ON est.id = env.establishment_id AND est.tenant_id = c.tenant_id
        LEFT JOIN cost_center cc ON cc.id = c.id_ccosto AND cc.tenant_id = c.tenant_id
        LEFT JOIN persons p ON p.id = c.id_usuario AND p.tenant_id = c.tenant_id
        WHERE ic.tenant_id = %s::uuid
        ORDER BY ic.id DESC
        """,
        "bienes_inventariados_export",
    ),
}


def get_export_query(module: str) -> tuple[str, str]:
    try:
        return EXPORT_QUERIES[module]
    except KeyError as exc:
        raise ValueError(f"Módulo de exportación desconocido: {module}") from exc
