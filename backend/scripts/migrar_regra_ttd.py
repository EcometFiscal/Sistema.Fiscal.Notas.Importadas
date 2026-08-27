"""Migracao de schema para um banco JA' existente (ex.: Supabase em producao) quando esta
mudanca (bloco por NCM+ambito) for implantada.

Base.metadata.create_all() so' cria tabela que nao existe - nao adiciona coluna em tabela
existente. Este script faz so' isso: adiciona as colunas novas em regra_ttd e limpa as 3 linhas
antigas (por bloco, sem NCM/ambito) para o proximo start da aplicacao semear a tabela nova
(main.py ja' chama semear_regras + backfill_ncm_produtos no lifespan - nao precisa rodar nada
alem deste script).

NAO mexe em nota, nota_item, produto nem em nenhum dado de lancamento - so' na tabela de regras.

    DATABASE_URL="postgresql+psycopg2://...supabase..." python -m scripts.migrar_regra_ttd
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402


def main():
    with engine.begin() as con:
        con.execute(text("ALTER TABLE regra_ttd ADD COLUMN IF NOT EXISTS ncm VARCHAR(8)"))
        con.execute(text("ALTER TABLE regra_ttd ADD COLUMN IF NOT EXISTS ambito VARCHAR(15)"))
        apagadas = con.execute(text("DELETE FROM regra_ttd WHERE ncm IS NULL")).rowcount
    print(f"colunas ncm/ambito adicionadas em regra_ttd. {apagadas} linha(s) antiga(s) "
         "(sem ncm/ambito) removida(s). No proximo start da aplicacao, o lifespan semeia as "
         "linhas novas e preenche o NCM dos produtos automaticamente.")


if __name__ == "__main__":
    main()
