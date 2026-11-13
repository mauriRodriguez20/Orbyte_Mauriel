import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# TEST_DATABASE_URL vive en el .env de la raíz del repositorio, como el resto de la
# configuración local. override=False: si la variable ya está exportada en la terminal (o en
# un CI), manda la exportada y el archivo no la pisa.
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

# Las pruebas nunca usan la base de desarrollo: aunque el .env defina DATABASE_URL, aquí se
# reemplaza siempre por la base de pruebas o por una dirección donde no hay ninguna base.
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-tests"
os.environ["JWT_EXPIRES_MIN"] = "60"
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.config import get_settings

get_settings.cache_clear()

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


@pytest.fixture(scope="session", autouse=True)
def arranque_sin_base():
    """Sin base de pruebas, la app no busca PostgreSQL al arrancar dentro de las pruebas.

    Cada `with TestClient(app)` dispara el arranque de app/main.py, que aplica las migraciones
    y crea el administrador inicial. Sin PostgreSQL, cada intento de conexión tarda varios
    segundos y la suite parecía colgada, aunque esas pruebas usan sesiones falsas y no
    necesitan ninguna base. Aquí se desactivan solo esos dos pasos, solo dentro de las pruebas
    y solo cuando no hay TEST_DATABASE_URL. El arranque de producción no cambia: su doble
    migración (DEF-11) sigue pendiente y no se toca aquí.
    """
    if os.getenv("TEST_DATABASE_URL"):
        yield
        return

    from app import main as arranque_app

    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(arranque_app, "_run_database_migrations", lambda: None)
        parche.setattr(arranque_app, "ensure_seed_admin", lambda _db: None)
        yield


@pytest.fixture
def real_db():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Define TEST_DATABASE_URL en el .env de la raíz con una base PostgreSQL de pruebas "
            "para ejecutar las pruebas de integración"
        )

    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        check=True,
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    with Session(engine) as db:
        yield db
        # historial_estados es de solo inserción (#35): no admite DELETE, se limpia con TRUNCATE.
        db.execute(text("TRUNCATE idempotency_keys, historial_estados, rescates"))
        db.commit()
    engine.dispose()
