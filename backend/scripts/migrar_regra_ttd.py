"""Migracao de schema para um banco JA' existente (ex.: Supabase em producao).

Base.metadata.create_all() so' cria tabela que nao existe - nao adiciona coluna em tabela
existente. Este script faz so' isso, em duas frentes acumuladas ate' agora:
  1. regra_ttd: colunas ncm/ambito (bloco do TTD passou a ser por NCM+ambito, nao por CFOP) -
     limpa as 3 linhas antigas (por bloco, sem NCM/ambito) para o proximo start da aplicacao
     semear a tabela nova (main.py ja' chama semear_regras + backfill_ncm_produtos no lifespan).
  2. lote_importacao: coluna complementadas (casamento do XML com nota migrada da planilha,
     sem chave de acesso - "complementada" e' situacao separada de "importada").

NAO mexe em nota, nota_item, produto nem em nenhum dado de lancamento - so' schema.

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
        con.execute(text("ALTER TABLE lote_importacao "
                         "ADD COLUMN IF NOT EXISTS complementadas INTEGER DEFAULT 0"))
    print(f"colunas ncm/ambito adicionadas em regra_ttd. {apagadas} linha(s) antiga(s) "
         "(sem ncm/ambito) removida(s). No proximo start da aplicacao, o lifespan semeia as "
         "linhas novas e preenche o NCM dos produtos automaticamente.")
    print("coluna complementadas adicionada em lote_importacao (default 0).")


if __name__ == "__main__":
    main()
