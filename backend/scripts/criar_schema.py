"""Cria as tabelas e semeia as aliquotas do TTD. Roda uma vez por banco.

    DATABASE_URL="postgresql+psycopg2://...supabase..." python -m scripts.criar_schema
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import Base, SessionLocal, engine        # noqa: E402
from app.models import *                             # noqa: E402,F401,F403
from app.services.apuracao import semear_regras      # noqa: E402


def main():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        semear_regras(db)
        db.commit()
    print(f"schema criado em {engine.url.render_as_string(hide_password=True)}")
    print("tabelas:", ", ".join(sorted(Base.metadata.tables)))


if __name__ == "__main__":
    main()
