USER_STATUS_ACTIVE = "active"
USER_STATUS_INACTIVE = "inactive"

CONTACT_STATUS_ACTIVE = "activo"
CONTACT_STATUS_INACTIVE = "inactivo"
CONTACT_STATUS_OBSERVED = "observado"
CONTACT_STATUS_INVALID = "numero_invalido"

CAMPAIGN_STATUS_DRAFT = "borrador"
CAMPAIGN_STATUS_SCHEDULED = "programada"
CAMPAIGN_STATUS_IN_PROGRESS = "en_curso"
CAMPAIGN_STATUS_SENT = "enviada"
CAMPAIGN_STATUS_FINISHED = "finalizada"
CAMPAIGN_STATUS_FAILED = "fallida"

CAMPAIGN_TYPES = [
    "comunicado",
    "recordatorio",
    "encuesta",
    "beneficio",
    "capacitacion",
    "emergencia",
    "evento",
]

TEMPLATE_CATEGORIES = [
    "comunicado",
    "recordatorio",
    "encuesta",
    "felicitacion",
    "beneficio",
    "emergencia",
    "capacitacion",
]

SURVEY_RESPONSE_TYPES = ["si_no", "opcion_multiple", "escala_5", "texto_libre"]

# Códigos de `ui_components` del inventario SGIP (sidebar + permisos por módulo).
INVENTORY_UI_COMPONENT_CODES: frozenset[str] = frozenset(
    {
        "dashboard",
        "locales",
        "locales_mapa",
        "ambientes",
        "centro_costo",
        "personas",
        "list_sbn",
        "margesi",
        "hoja_captura",
        "bienes",
        "imagenes",
        "reporte_aptot",
        "conciliacion",
        "conciliacion_sbn",
        "desconciliacion",
        "desconciliacion_sbn",
        "no_conciliables",
        "usuarios",
        "perfiles",
        "settings",
        "auditoria",
    }
)

# Alias histórico del portal Conectados Directo.
PORTAL_UI_COMPONENT_CODES = INVENTORY_UI_COMPONENT_CODES
