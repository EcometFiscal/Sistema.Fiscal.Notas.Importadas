"""Checagem de consistencia do bloco historico contra a nova tabela de TTD por NCM+ambito.

Nao muda nada. Os 6 anos migrados nao tem CFOP, NCM, origem nem UF gravados por nota (decisao
2 e 5 da Fase 1) - nao ha' como recalcular o bloco historico por NCM+ambito sem chutar UF. Este
script faz o que da' para fazer sem chutar: infere o NCM do item pelo produto (ja' preenchido
por backfill_ncm_produtos) e o ambito pelo PROPRIO bloco ja' gravado (bloco 3 = interna, 1/2 =
interestadual - e' assim que a tabela regra_ttd ja' rotulava esses blocos antes desta mudanca),
e confere se a nova tabela concorda com o bloco que ja' esta' no banco. Reporta divergencias -
nao aplica nenhuma.

    python -m scripts.checar_consistencia_ttd
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Nota, NotaItem, Produto  # noqa: E402
from app.services import apuracao as ap  # noqa: E402

AMBITO_DO_BLOCO = {"1": "interestadual", "2": "interestadual", "3": "interna"}


def main():
    with SessionLocal() as db:
        linhas = db.execute(
            select(NotaItem, Nota, Produto)
            .join(Nota, Nota.id == NotaItem.nota_id)
            .join(Produto, Produto.id == NotaItem.produto_id)
            .where(NotaItem.bloco_ttd.is_not(None), Nota.natureza != "ACERTO")).all()

        sem_ncm, sem_regra, divergentes, ok = [], [], [], 0
        for item, nota, produto in linhas:
            ncm = produto.ncm
            if not ncm:
                sem_ncm.append((nota.numero, produto.descricao))
                continue
            ambito = AMBITO_DO_BLOCO.get(item.bloco_ttd)
            if ambito is None:
                continue
            r = ap.regra_produto(db, ncm, ambito, nota.data_mov)
            if r is None:
                sem_regra.append((nota.numero, produto.descricao, ncm, ambito, item.bloco_ttd))
                continue
            if r.bloco != item.bloco_ttd:
                divergentes.append((nota.numero, produto.descricao, ncm, ambito,
                                    item.bloco_ttd, r.bloco))
            else:
                ok += 1

        print(f"itens com bloco no historico: {len(linhas)}")
        print(f"consistentes com a nova tabela: {ok}")
        print(f"produto sem NCM cadastrado (nao verificado): {len(sem_ncm)}")
        for numero, produto in sem_ncm[:20]:
            print(f"   NF {numero} - {produto}")
        print(f"NCM+ambito sem regra na nova tabela mas com bloco historico: {len(sem_regra)}")
        for numero, produto, ncm, ambito, bloco in sem_regra[:20]:
            print(f"   NF {numero} - {produto} (NCM {ncm}, {ambito}) tinha bloco {bloco}")
        print(f"DIVERGENCIAS (bloco historico != o que a nova tabela diria): {len(divergentes)}")
        for numero, produto, ncm, ambito, bloco_hist, bloco_novo in divergentes:
            print(f"   NF {numero} - {produto} (NCM {ncm}, {ambito}): "
                 f"tinha bloco {bloco_hist}, a nova tabela diria bloco {bloco_novo}")


if __name__ == "__main__":
    main()
