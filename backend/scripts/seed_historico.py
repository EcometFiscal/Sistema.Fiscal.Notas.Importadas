"""Carrega os 6 anos migrados na Fase 1 dentro da base da aplicacao.

Fluxo: roda o saneamento da Fase 1 sobre os dois arquivos originais, joga o resultado em um
SQLite temporario e copia para o banco da aplicacao. Os lancamentos de ACERTO nao sao copiados:
quem os recria e' o proprio motor de custeio do sistema, para que a regra viva num lugar so'.

    python -m scripts.seed_historico --estoque ESTOQUE.xlsm --apuracao APURACAO.xlsx
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import subprocess
import sys
import tempfile
import warnings

import openpyxl
from sqlalchemy import delete, select, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

from app.db import Base, SessionLocal, engine            # noqa: E402
from app.models import (Auditoria, ConsumoEstoque, Excecao, Nota, NotaItem,  # noqa: E402
                        Parceiro, Produto)
from app.services import estoque as est                  # noqa: E402
from app.services.apuracao import backfill_ncm_produtos, semear_regras  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


def data(v):
    """O SQLite devolve data como texto; a base da aplicacao trabalha com date."""
    if not v:
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])


def roda_fase1(estoque: str, apuracao: str) -> str:
    destino = os.path.join(tempfile.mkdtemp(), "fase1.db")
    rel = os.path.join(os.path.dirname(destino), "relatorio.xlsx")
    subprocess.run([sys.executable, os.path.join(AQUI, "migracao_fase1.py"),
                    "--estoque", estoque, "--apuracao", apuracao,
                    "--db", destino, "--relatorio", rel], check=True)
    return destino


def blocos_da_apuracao(caminho: str) -> tuple[dict[int, str], dict[int, str]]:
    """Le o bloco de cada NF da planilha de apuracao - unica fonte de bloco no historico.
    Devolve (vendas, devolucoes)."""
    wb = openpyxl.load_workbook(caminho, data_only=True)
    ws = wb["OPERAÇÕES SAÍDA IMPORTADO"]
    vendas, devolucoes, atual, em_devolucao = {}, {}, None, False
    for r in ws.iter_rows(values_only=True):
        a = r[0]
        if isinstance(a, str) and "DEVOLUÇÃO DE VENDAS" in a:
            em_devolucao = True
        if isinstance(a, str) and a.strip().startswith(("Interestadual", "Interna")):
            carga = r[1]
            atual = {0.6: "1", 1.0: "2", 2.1: "3"}.get(round(float(carga), 1) if carga else None)
        if isinstance(r[1], (int, float)) and r[2] and r[4] is not None and atual:
            (devolucoes if em_devolucao else vendas)[int(r[1])] = atual
    return vendas, devolucoes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estoque", required=True)
    ap.add_argument("--apuracao", required=True)
    ap.add_argument("--limpar", action="store_true", default=True)
    args = ap.parse_args()

    Base.metadata.create_all(engine)
    origem = roda_fase1(args.estoque, args.apuracao)
    con = sqlite3.connect(origem)
    con.row_factory = sqlite3.Row
    blocos, blocos_dev = blocos_da_apuracao(args.apuracao)

    with SessionLocal() as db:
        if args.limpar:
            for tabela in (ConsumoEstoque, Excecao, Auditoria, NotaItem, Nota, Produto, Parceiro):
                db.execute(delete(tabela))
            db.commit()
            if engine.dialect.name == "postgresql":
                for t in ("parceiro", "produto", "nota", "nota_item", "consumo_estoque",
                          "excecao", "auditoria"):
                    db.execute(text(f"ALTER SEQUENCE {t}_id_seq RESTART WITH 1"))
                db.commit()

        semear_regras(db)

        for r in con.execute("SELECT * FROM parceiro"):
            db.add(Parceiro(id=r["id"], nome=r["nome"], exterior=bool(r["exterior"]),
                            papel=r["papel"], variantes=r["variantes"], status="ativo"))
        for r in con.execute("SELECT * FROM produto"):
            db.add(Produto(id=r["id"], descricao=r["descricao"], ncm=r["ncm"], unidade=r["unidade"],
                           categoria=r["categoria"], metal=r["metal"], variantes=r["variantes"]))
        db.flush()

        notas, sem_data = {}, []
        for r in con.execute("SELECT * FROM nota WHERE natureza <> 'ACERTO'"):
            if not r["data_mov"]:
                # A base da aplicacao nao aceita movimento sem data: sem data nao ha' competencia
                # nem posicao de estoque. O lancamento vai para o painel de pendencias com todos
                # os dados preservados, para alguem localizar a NF e informar a data.
                sem_data.append(dict(r))
                continue
            natureza = r["natureza"]
            if r["tipo"] == "E" and r["numero"] in blocos_dev:
                natureza = "DEVOLUCAO"      # devolucao de venda: volta ao estoque e estorna o credito
            n = Nota(id=r["id"], chave_acesso=r["chave_acesso"], numero=r["numero"],
                     serie=r["serie"] or "1", modelo=r["modelo"] or "55", tipo=r["tipo"],
                     cfop=r["cfop"], natureza=natureza, data_emissao=data(r["data_emissao"]),
                     data_mov=data(r["data_mov"]), parceiro_id=r["parceiro_id"],
                     valor_total=r["valor_total"], status="lancada",
                     origem_registro=r["origem_registro"], criado_por="migracao")
            db.add(n)
            notas[r["id"]] = n
        db.flush()

        for r in con.execute("SELECT * FROM nota_item"):
            if r["nota_id"] not in notas:
                continue
            n = notas[r["nota_id"]]
            db.add(NotaItem(nota_id=n.id, produto_id=r["produto_id"], ncm=r["ncm"],
                            origem_merc=r["origem_merc"], quantidade=r["quantidade"] or 0,
                            valor=r["valor"], base_calculo=r["valor"],
                            bloco_ttd=(blocos.get(n.numero) if n.tipo == "S"
                                       else blocos_dev.get(n.numero) if n.natureza == "DEVOLUCAO"
                                       else None),
                            custo_unit=r["custo_unit"] if n.tipo == "E" else None))
        for r in sem_data:
            db.add(Excecao(tipo="nota_sem_data", produto_id=None,
                           descricao=(f"NF {r['numero']} ({'entrada' if r['tipo']=='E' else 'saída'}) "
                                      f"veio da planilha sem data e não pode entrar no estoque. "
                                      f"Origem: {r['origem_registro']}. Valor: R$ {r['valor_total'] or 0:,.2f}."),
                           criado_por="migracao"))
        db.commit()

        if engine.dialect.name == "postgresql":
            for t in ("parceiro", "produto", "nota"):
                db.execute(text(f"SELECT setval('{t}_id_seq', COALESCE((SELECT MAX(id) FROM {t}),1))"))
            db.commit()

        ids = db.execute(select(Produto.id)).scalars().all()
        est.recalcular_varios(db, ids, "migracao")
        db.commit()

        # NCM cadastral dos 6 produtos conhecidos - descritivo, nao mexe em bloco_ttd nem valor.
        backfill_ncm_produtos(db)
        db.commit()

        n_notas = db.execute(select(Nota).where(Nota.natureza != "ACERTO")).scalars().all()
        acertos = db.execute(select(Nota).where(Nota.natureza == "ACERTO")).scalars().all()
        pos = est.posicao(db)
        print(f"parceiros: {len(db.execute(select(Parceiro)).scalars().all())}")
        print(f"produtos : {len(ids)}")
        print(f"notas    : {len(n_notas)} (+{len(acertos)} acertos gerados pelo custeio)")
        print(f"pendencia: {len(sem_data)} lancamento(s) sem data ficaram em excecoes")
        print(f"estoque  : {sum(p['saldo_kg'] for p in pos):,.1f} kg | "
              f"R$ {sum(p['saldo_rs'] for p in pos):,.2f}")
        for p in pos:
            print(f"   {p['produto']:<22} {p['saldo_kg']:>14,.1f} kg   R$ {p['saldo_rs']:>15,.2f}")


if __name__ == "__main__":
    main()
