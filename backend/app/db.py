"""Conexao com o banco.

Em producao roda no Supabase, atras do pooler em modo transacao. Duas consequencias:
  - NullPool: cada requisicao abre e devolve a conexao. Guardar pool em funcao serverless nao
    ajuda (o processo morre) e ainda estoura o limite de conexoes do plano.
  - sslmode=require: o Supabase so' aceita conexao cifrada.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL

_serverless = bool(os.getenv("VERCEL") or os.getenv("SERVERLESS"))
_args = {}
if DATABASE_URL.startswith("postgresql") and "sslmode" not in DATABASE_URL:
    _args["sslmode"] = os.getenv("PGSSLMODE", "prefer")

engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool if _serverless else None,
    pool_pre_ping=not _serverless,
    connect_args=_args,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
