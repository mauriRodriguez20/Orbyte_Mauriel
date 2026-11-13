"""Pruebas de la propia infraestructura de pruebas: protección y limpieza de la base."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.proteccion_base import motivo_base_insegura

BASE_DE_PRUEBAS = "postgresql://orbyte_dev:clave@localhost:5432/orbyte_test"
BASE_DE_DESARROLLO = "postgresql://orbyte_dev:clave@localhost:5432/orbyte"


def test_proteccion_acepta_una_base_local_terminada_en_test():
    assert motivo_base_insegura(BASE_DE_PRUEBAS, BASE_DE_DESARROLLO) is None


def test_proteccion_acepta_la_base_de_pruebas_cuando_no_hay_database_url():
    assert motivo_base_insegura(BASE_DE_PRUEBAS, None) is None


@pytest.mark.parametrize(
    "url_aplicacion",
    [
        BASE_DE_PRUEBAS,
        # La misma base escrita de otra forma: otro usuario, sin puerto y con parámetros.
        "postgresql://otro_usuario:otra_clave@LOCALHOST/orbyte_test?connect_timeout=5",
    ],
    ids=["cadena_identica", "misma_base_escrita_distinto"],
)
def test_proteccion_rechaza_la_misma_base_que_database_url(url_aplicacion):
    assert motivo_base_insegura(BASE_DE_PRUEBAS, url_aplicacion) == "es la misma base que DATABASE_URL"


def test_proteccion_rechaza_un_servidor_de_render():
    url = "postgresql://usuario:clave@dpg-abc123-a.virginia-postgres.render.com/orbyte_test"
    assert motivo_base_insegura(url, None) == "apunta a un servidor de Render (render.com)"


@pytest.mark.parametrize(
    "base",
    ["orbyte", "orbyte_testing", "test_orbyte", ""],
    ids=["desarrollo", "sufijo_parecido", "prefijo_test", "sin_nombre"],
)
def test_proteccion_rechaza_una_base_que_no_termina_en_test(base):
    motivo = motivo_base_insegura(f"postgresql://usuario:clave@localhost:5432/{base}", None)
    assert motivo == f"el nombre de la base («{base}») no termina en _test"


@pytest.mark.parametrize("url", ["", "no-es-una-url"], ids=["vacia", "sin_formato"])
def test_proteccion_rechaza_una_url_invalida(url):
    assert motivo_base_insegura(url, None) == "no es una URL de PostgreSQL válida"


def test_proteccion_nunca_revela_la_contrasena_en_el_motivo():
    motivo = motivo_base_insegura("postgresql://usuario:secreto123@localhost:5432/orbyte", None)
    assert "secreto123" not in motivo


def test_pytest_aborta_antes_de_ejecutar_si_la_base_de_pruebas_no_es_segura():
    """La protección está conectada: con una base insegura, pytest no ejecuta ninguna prueba."""
    entorno = dict(os.environ, TEST_DATABASE_URL=BASE_DE_DESARROLLO, PYTHONUTF8="1")
    resultado = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_produccion.py"],
        cwd=Path(__file__).resolve().parents[1],
        env=entorno,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    salida = resultado.stdout + resultado.stderr
    assert resultado.returncode == pytest.ExitCode.USAGE_ERROR
    assert "TEST_DATABASE_URL no es segura para las pruebas" in salida
    assert "passed" not in salida


def test_real_db_entrega_la_base_vacia(real_db):
    """Ninguna prueba recibe datos de otra: la limpieza cubre todas las tablas."""
    tablas = real_db.scalars(
        text(
            "SELECT quote_ident(tablename) FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        )
    ).all()
    assert tablas, "la base de pruebas debería tener las tablas de las migraciones"
    con_datos = {}
    for tabla in tablas:
        filas = real_db.scalar(text(f"SELECT count(*) FROM {tabla}"))
        if filas:
            con_datos[tabla] = filas
    assert con_datos == {}
