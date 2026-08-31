"""Cria as tabelas do modulo de Conciliacao e Fechamento de ICMS (conc_*). Roda uma vez por
banco - sao tabelas novas, sem nenhuma chave estrangeira para o schema existente, entao
create_all(tables=[...]) resolve sozinho sem tocar em mais nada.

    DATABASE_URL="postgresql+psycopg2://...supabase..." python -m scripts.migrar_conciliacao_icms

Equivalente em SQL puro (para rodar pelo SQL Editor do Supabase em vez deste script):
supabase/migrations/20260901000000_conciliacao_icms.sql
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import Base, engine  # noqa: E402
from app.models import (ConcApuracaoLinha, ConcDivergencia, ConcDocumentoFonte,  # noqa: E402,F401
                        ConcFechamento, ConcLancamentoEntrada, ConcPeriodo, ConcRegraJustificativa,
                        ConcSaldoCfop)

TABELAS = [ConcPeriodo.__table__, ConcDocumentoFonte.__table__, ConcLancamentoEntrada.__table__,
          ConcSaldoCfop.__table__, ConcRegraJustificativa.__table__, ConcDivergencia.__table__,
          ConcApuracaoLinha.__table__, ConcFechamento.__table__]


def main():
    Base.metadata.create_all(engine, tables=TABELAS)
    print("tabelas de conciliacao de ICMS criadas:", ", ".join(t.name for t in TABELAS))


if __name__ == "__main__":
    main()
