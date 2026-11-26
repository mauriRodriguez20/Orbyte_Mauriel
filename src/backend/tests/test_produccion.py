"""Protecciones que solo aplican con ENTORNO=produccion (#28)."""
import os
import secrets
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services import bootstrap


class FakeSession:
    def __init__(self):
        self.agregados = []

    def scalar(self, _consulta):
        return None

    def add(self, usuario):
        self.agregados.append(usuario)

    def commit(self):
        pass


def _crear_admin(monkeypatch, entorno):
    ajustes = SimpleNamespace(
        es_produccion=entorno == "produccion",
        default_admin_email=os.environ.get("DEFAULT_ADMIN_EMAIL", ""),
        default_admin_password=os.environ.get("DEFAULT_ADMIN_PASSWORD", ""),
    )
    monkeypatch.setattr(bootstrap, "get_settings", lambda: ajustes)
    db = FakeSession()
    bootstrap.ensure_seed_admin(db)
    return db.agregados


@pytest.mark.parametrize("contrasena", ["", "   ", "corta"])
def test_produccion_rechaza_clave_vacia_o_demasiado_corta(monkeypatch, contrasena):
    monkeypatch.setenv("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", contrasena)
    assert _crear_admin(monkeypatch, "produccion") == []


def test_produccion_crea_admin_con_contrasena_propia(monkeypatch):
    monkeypatch.setenv("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", secrets.token_urlsafe(32))
    assert len(_crear_admin(monkeypatch, "produccion")) == 1


def test_desarrollo_crea_admin_con_credenciales_configuradas(monkeypatch):
    monkeypatch.setenv("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", secrets.token_urlsafe(32))
    assert len(_crear_admin(monkeypatch, "desarrollo")) == 1


def test_cors_de_localhost_solo_en_desarrollo():
    assert Settings(_env_file=None, entorno="desarrollo").cors_origin_regex is not None
    assert Settings(_env_file=None, entorno="produccion").cors_origin_regex is None
    assert Settings(_env_file=None, entorno=" Produccion ").cors_origin_regex is None
