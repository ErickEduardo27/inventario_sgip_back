import logging

logger = logging.getLogger("conectados_directo")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
