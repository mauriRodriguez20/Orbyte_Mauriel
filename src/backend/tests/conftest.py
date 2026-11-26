import os
import secrets
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from tests.proteccion_base import motivo_base_insegura

# TEST_DATABASE_URL vive en el .env de la raíz del repositorio, como el resto de la
# configuración local. override=False: si la variable ya está exportada en la terminal (o en
# un CI), manda la exportada y el archivo no la pisa.
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

# Las pruebas vacían todas las tablas. Antes de tocar nada se comprueba que la base de pruebas
# no sea la de desarrollo ni la de Render. Una base insegura se descarta aquí mismo, y
# pytest_configure (más abajo) aborta la sesión explicando el motivo.
MOTIVO_BASE_INSEGURA = None
if os.getenv("TEST_DATABASE_URL"):
    MOTIVO_BASE_INSEGURA = motivo_base_insegura(os.environ["TEST_DATABASE_URL"], os.getenv("DATABASE_URL"))
    if MOTIVO_BASE_INSEGURA:
        del os.environ["TEST_DATABASE_URL"]

# Las pruebas nunca usan la base de desarrollo: aunque el .env defina DATABASE_URL, aquí se
# reemplaza siempre por la base de pruebas o por una dirección donde no hay ninguna base.
os.environ["DATABASE_URL"] = "postgresql://test@localhost:5432/test"
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["DEFAULT_ADMIN_EMAIL"] = "admin@example.com"
os.environ["DEFAULT_ADMIN_PASSWORD"] = secrets.token_urlsafe(32)
os.environ["JWT_EXPIRES_MIN"] = "60"
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.config import get_settings

get_settings.cache_clear()

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def pytest_configure(config):
    """Aborta la sesión, antes de ejecutar ninguna prueba, si la base de pruebas no es segura."""
    if MOTIVO_BASE_INSEGURA:
        raise pytest.UsageError(
            f"TEST_DATABASE_URL no es segura para las pruebas: {MOTIVO_BASE_INSEGURA}. "
            "Las pruebas vacían todas las tablas (TRUNCATE). Usa una base local solo para pruebas "
            "cuyo nombre termine en _test, por ejemplo orbyte_test."
        )


def _vaciar_tablas(db: Session) -> None:
    """Deja la base sin datos, para que ninguna prueba dependa de lo que dejó otra.

    La lista de tablas se lee del esquema: una tabla nueva queda cubierta sin tocar esta función.
    El TRUNCATE de historial_estados funciona por DEF-26: la tabla es de solo inserción, pero su
    trigger es por fila (no se dispara con TRUNCATE) y el rol conserva ese privilegio. Si DEF-26
    se corrige (trigger BEFORE TRUNCATE o REVOKE TRUNCATE), esta limpieza tendrá que cambiar,
    por ejemplo recreando el esquema de pruebas.
    """
    db.rollback()
    tablas = db.scalars(
        text(
            "SELECT quote_ident(tablename) FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'alembic_version' ORDER BY tablename"
        )
    ).all()
    if tablas:
        # Si una prueba dejó una conexión con candados, mejor un error claro que una suite colgada.
        db.execute(text("SET LOCAL lock_timeout = '15s'"))
        db.execute(text(f"TRUNCATE {', '.join(tablas)} RESTART IDENTITY CASCADE"))
    db.commit()


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


@pytest.fixture(scope="session")
def base_migrada():
    """Aplica las migraciones una sola vez por sesión y devuelve la URL de la base de pruebas.

    Antes cada prueba lanzaba `alembic upgrade head` en un proceso aparte: más de un segundo
    por prueba aunque la base ya estuviera al día.
    """
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
    # Una ejecución anterior interrumpida pudo dejar datos: la sesión empieza con la base vacía.
    engine = create_engine(database_url)
    with Session(engine) as db:
        _vaciar_tablas(db)
    engine.dispose()
    return database_url


@pytest.fixture
def real_db(base_migrada):
    # El motor sigue siendo uno por prueba: ninguna conexión abierta pasa a la siguiente.
    engine = create_engine(base_migrada, pool_pre_ping=True)
    with Session(engine) as db:
        yield db
        _vaciar_tablas(db)
    engine.dispose()
