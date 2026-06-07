def normalize_channel_value(channel_type: str, raw_value: str) -> str:
    """Valor normalizado para unicidad por tenant (email en minúsculas, resto recortado)."""
    t = (channel_type or "").strip().lower()
    v = (raw_value or "").strip()
    if t == "email":
        return v.lower()
    return v
