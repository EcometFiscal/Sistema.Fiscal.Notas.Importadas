"""Migracao de schema para um banco JA' existente (ex.: Supabase em producao).

Amplia o modulo de Conciliacao de ICMS (conc_*) para tambem conciliar o Livro de Saidas
(contabilidade x Empresa), alem do Livro de Entradas ja' existente - pedido do usuario em
31/08/2026. So' schema, tres colunas novas:

  1. conc_lancamento_entrada.tipo (entrada|saida, default 'entrada') - a tabela agora guarda
     nota a nota de entrada OU de saida; o nome da tabela ficou de antes, quando so' existia
     entrada.
  2. conc_lancamento_entrada.cancelada (boolean, default false) - nota que a contabilidade zerou
     e o Ecomet manteve com anotacao "Cancelada" (achado real da competencia 07/2026).
  3. conc_divergencia.bloco (entrada|saida|null) - separa os 3 relatorios de divergencia (CFOP
     Dime x Livro Fiscal, Livro de Entradas, Livro de Saidas).

Tabelas ja' existem e estao vazias (nenhuma competencia com saida foi importada ainda) - ALTER
simples, sem backfill de dado.

    DATABASE_URL="postgresql+psycopg2://...supabase..." python -m scripts.migrar_conciliacao_saida
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402


def main():
    with engine.begin() as con:
        con.execute(text(
            "ALTER TABLE conc_lancamento_entrada "
            "ADD COLUMN IF NOT EXISTS tipo VARCHAR(8) NOT NULL DEFAULT 'entrada'"))
        con.execute(text(
            "ALTER TABLE conc_lancamento_entrada "
            "ADD COLUMN IF NOT EXISTS cancelada BOOLEAN NOT NULL DEFAULT false"))
        con.execute(text(
            "ALTER TABLE conc_lancamento_entrada DROP CONSTRAINT IF EXISTS ck_conclanc_tipo"))
        con.execute(text(
            "ALTER TABLE conc_lancamento_entrada ADD CONSTRAINT ck_conclanc_tipo "
            "CHECK (tipo in ('entrada','saida'))"))

        con.execute(text(
            "ALTER TABLE conc_divergencia ADD COLUMN IF NOT EXISTS bloco VARCHAR(8)"))
        con.execute(text(
            "ALTER TABLE conc_divergencia DROP CONSTRAINT IF EXISTS ck_concdiv_bloco"))
        con.execute(text(
            "ALTER TABLE conc_divergencia ADD CONSTRAINT ck_concdiv_bloco "
            "CHECK (bloco is null or bloco in ('entrada','saida'))"))
    print("conc_lancamento_entrada: colunas tipo (default 'entrada') e cancelada (default false) "
         "adicionadas.")
    print("conc_divergencia: coluna bloco (entrada|saida|null) adicionada.")


if __name__ == "__main__":
    main()
