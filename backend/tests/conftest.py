import os
import subprocess
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

DB_TESTE = os.getenv("TEST_DATABASE_URL",
                     "postgresql+psycopg2://lastro:lastro@localhost:5432/lastro_test")
# Precisa valer ANTES de qualquer import de app.db: a engine e' criada no import do modulo.
os.environ["DATABASE_URL"] = DB_TESTE
_PADRAO = os.path.join(os.path.dirname(RAIZ), "planilhas")
ESTOQUE = os.getenv("ARQ_ESTOQUE", os.path.join(_PADRAO, "ESTOQUE FISCAL IMPORTADO.xlsm"))
APURACAO = os.getenv("ARQ_APURACAO",
                     os.path.join(_PADRAO, "Apuração ICMS Nacional e Importado  072026.xlsx"))


def _planilhas_existem() -> bool:
    return os.path.isfile(ESTOQUE) and os.path.isfile(APURACAO)


def pytest_collection_modifyitems(config, items):
    """A suite roda sobre os 6 anos migrados. Sem os dois arquivos originais nao ha' base para
    conferir contra - a integracao continua (CI, maquina nova), mas dizendo o que pulou e por que."""
    if _planilhas_existem():
        return
    motivo = pytest.mark.skip(reason=(
        "Os dois arquivos originais nao estao neste ambiente. Aponte ARQ_ESTOQUE e ARQ_APURACAO "
        "para a planilha de estoque e a de apuracao, ou coloque-as em planilhas/."))
    for item in items:
        item.add_marker(motivo)


@pytest.fixture(scope="session", autouse=True)
def base_carregada():
    if not _planilhas_existem():
        yield
        return
    nome = DB_TESTE.rsplit("/", 1)[-1]
    for sql in (f'DROP DATABASE IF EXISTS {nome}', f'CREATE DATABASE {nome} OWNER lastro'):
        subprocess.run(["psql", "-U", "lastro", "-h", "localhost", "-d", "postgres", "-c", sql],
                       check=True, capture_output=True, env={**os.environ, "PGPASSWORD": "lastro"})
    subprocess.run([sys.executable, "-m", "scripts.seed_historico",
                    "--estoque", ESTOQUE, "--apuracao", APURACAO],
                   check=True, cwd=RAIZ, capture_output=True,
                   env={**os.environ, "DATABASE_URL": DB_TESTE})
    yield


@pytest.fixture()
def db():
    from app.db import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def cliente():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
