"""Protección de la base de datos que usan las pruebas.

Las pruebas de integración vacían todas las tablas con TRUNCATE. Si TEST_DATABASE_URL
apuntara por error a la base de desarrollo o a la de Render, se perderían datos reales.
Este módulo solo decide si una URL es segura; tests/conftest.py aborta la sesión si no lo es.
"""

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def _destino(url: str) -> tuple[str, int, str]:
    """Servidor, puerto y nombre de la base, sin usuario, contraseña ni parámetros."""
    partes = make_url(url)
    return (partes.host or "").lower(), partes.port or 5432, partes.database or ""


def motivo_base_insegura(url_pruebas: str, url_aplicacion: str | None) -> str | None:
    """Devuelve por qué `url_pruebas` no sirve para las pruebas, o None si es segura.

    `url_aplicacion` es la DATABASE_URL del entorno (la base de desarrollo). El motivo nunca
    incluye la URL, porque lleva la contraseña de la base.
    """
    try:
        destino = _destino(url_pruebas)
    except ArgumentError:
        return "no es una URL de PostgreSQL válida"

    if url_aplicacion:
        try:
            misma_base = destino == _destino(url_aplicacion)
        except ArgumentError:
            misma_base = False
        # Se compara el destino, no el texto: la misma base puede escribirse con otro usuario
        # o con otros parámetros.
        if misma_base or url_pruebas == url_aplicacion:
            return "es la misma base que DATABASE_URL"

    servidor, _puerto, base = destino
    if "render.com" in servidor:
        return "apunta a un servidor de Render (render.com)"
    # Es la regla que más protege: ni la base de desarrollo ni la de Render terminan en _test.
    if not base.endswith("_test"):
        return f"el nombre de la base («{base}») no termina en _test"
    return None
