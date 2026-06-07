"""Entrada del API para usar con el front (Vite).

- Arranque típico: ``uvicorn main:app --reload --host 0.0.0.0 --port 8000``
- O desde esta carpeta: ``python main.py`` (mismo puerto **8000** que usa el front por defecto en ``VITE_API_URL`` / ``src/lib/config.ts``).

Variables de entorno útiles: ``PORT``, ``HOST``, ``UVICORN_RELOAD``, ``CORS_EXTRA_ORIGINS``.
"""

from __future__ import annotations

import os

from app.main import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    reload = os.environ.get("UVICORN_RELOAD", "1").lower() in ("1", "true", "yes")
    uvicorn.run("main:app", host=host, port=port, reload=reload)
