"""Lancamento unico: uma nota, dois lados, e as travas que a planilha nunca teve."""
import datetime as dt

import pytest
from sqlalchemy import select

from app.models import Excecao, Nota, Produto
from app.services import estoque as est

HOJE = dt.date.today()


def _produto(db, descricao):
    return db.execute(select(Produto).where(Produto.descricao == descricao)).scalars().one()


def _nota(**extra):
    base = dict(tipo="S", numero=99001, serie="1", natureza="VENDA",
                data_mov=HOJE.isoformat(), parceiro="CLIENTE DE TESTE LTDA",
                itens=[dict(produto="SILICIO METALICO", quantidade=1000, valor=12000,
                            bloco_ttd="3")])
    base.update(extra)
    return base


def test_data_futura_e_recusada(cliente):
    r = cliente.post("/api/notas", json=_nota(numero=99010,
                                              data_mov=(HOJE + dt.timedelta(days=1)).isoformat()))
    assert r.status_code == 400
    assert "futura" in r.json()["detail"]["mensagem"]


def test_saida_dentro_do_saldo_grava_e_baixa_estoque(cliente, db):
    p = _produto(db, "SILICIO METALICO")
    antes = float(est.saldo(db, p.id))
    r = cliente.post("/api/notas", json=_nota(numero=99002))
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["avisos"] == []
    db.expire_all()
    assert abs(float(est.saldo(db, p.id)) - (antes - 1000)) < 0.001
    # o mesmo lancamento ja' aparece na apuracao da competencia
    assert corpo["apuracao"]["base_beneficiada"] >= 12000


def test_saida_sem_saldo_exige_justificativa(cliente, db):
    p = _produto(db, "LINGOTE DE MAGNESIO")
    demais = float(est.saldo(db, p.id)) + 5000
    payload = _nota(numero=99003,
                    itens=[dict(produto="LINGOTE DE MAGNESIO", quantidade=demais, valor=100000,
                                bloco_ttd="3")])
    r = cliente.post("/api/notas", json=payload)
    assert r.status_code == 422
    aviso = r.json()["detail"]["avisos"][0]
    assert aviso["codigo"] == "saldo_insuficiente"
    assert aviso["exige"] == "justificativa"
    assert aviso["dados"]["falta"] > 4999

    payload["justificativa"] = "Entrada de importacao ainda sem XML; sera' lancada nesta semana."
    r = cliente.post("/api/notas", json=payload)
    assert r.status_code == 201, r.text
    nota_id = r.json()["nota"]["id"]

    exc = db.execute(select(Excecao).where(Excecao.nota_id == nota_id,
                                           Excecao.tipo == "saida_sem_saldo")).scalars().all()
    assert len(exc) == 1 and exc[0].justificativa.startswith("Entrada de importacao")

    # Decisao de 30/08/2026: sem acerto - o saldo do produto fica negativo mesmo.
    assert float(est.saldo(db, p.id)) < 0
    acertos = db.execute(select(Nota).where(Nota.natureza == "ACERTO")).scalars().all()
    assert not acertos


def test_duplicata_exige_confirmacao(cliente):
    payload = _nota(numero=99004)
    assert cliente.post("/api/notas", json=payload).status_code == 201
    r = cliente.post("/api/notas", json=payload)
    assert r.status_code == 422
    assert r.json()["detail"]["avisos"][0]["codigo"] == "possivel_duplicata"
    payload["confirmar_duplicata"] = True
    assert cliente.post("/api/notas", json=payload).status_code == 201


def test_lancamento_retroativo_recalcula_o_custeio(cliente, db):
    """Entrada lancada com data antiga muda o custo das saidas posteriores."""
    p = _produto(db, "SUCATA DE COBRE")
    antes = [x for x in est.posicao(db) if x["produto_id"] == p.id][0]
    r = cliente.post("/api/notas", json=dict(
        tipo="E", numero=99100, serie="1", natureza="IMPORTACAO",
        data_mov=dt.date(2021, 6, 1).isoformat(), parceiro="FORNECEDOR RETROATIVO LTDA",
        itens=[dict(produto="SUCATA DE COBRE", quantidade=10000, valor=250000)]))
    assert r.status_code == 201, r.text
    depois = [x for x in est.posicao(db) if x["produto_id"] == p.id][0]
    assert abs(depois["saldo_kg"] - (antes["saldo_kg"] + 10000)) < 0.5
    assert depois["saldo_rs"] != antes["saldo_rs"]


def test_cancelamento_devolve_o_saldo(cliente, db):
    p = _produto(db, "SILICIO METALICO")
    r = cliente.post("/api/notas", json=_nota(numero=99005))
    nota_id = r.json()["nota"]["id"]
    antes = float(est.saldo(db, p.id))
    assert cliente.post(f"/api/notas/{nota_id}/cancelar",
                        params=dict(motivo="teste de cancelamento")).status_code == 200
    db.expire_all()
    assert abs(float(est.saldo(db, p.id)) - (antes + 1000)) < 0.001


def test_posicao_e_excecoes_pela_api(cliente):
    pos = cliente.get("/api/estoque/posicao").json()
    assert pos["total_kg"] > 0 and len(pos["produtos"]) >= 6
    exc = cliente.get("/api/excecoes").json()
    assert any(e["tipo"] == "nota_sem_data" for e in exc)
