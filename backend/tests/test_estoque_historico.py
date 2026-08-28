"""O criterio de entrega da Fase 2: o saldo de hoje tem que bater com o painel da planilha."""
import datetime as dt

import pytest
from sqlalchemy import select

from app.models import Nota, NotaItem, Produto
from app.services import estoque as est

# Numeros lidos do painel da planilha (aba DASHBOARD, C9:C14).
PAINEL = {
    "LINGOTE DE ALUMINIO": -8.0,
    "LINGOTE DE MAGNESIO": 35119.5,
    "SILICIO METALICO": 428757.0,
    "SUCATA DE ALUMINIO": 1391085.1,
    "SUCATA DE COBRE": 180091.5,
    "SUCATA DE MAGNESIO": 7026.0,     # a planilha perde 41.528,4 kg gravados com acento
}
ACERTOS_ESPERADOS = 24960.0 + 28059.5   # decisao 1: o que saiu sem saldo virou acerto datado


def _saldo_planilha(db, produto_id):
    """Saldo puro entradas - saidas, ignorando os acertos, para comparar com a planilha."""
    itens = db.execute(
        select(NotaItem, Nota).join(Nota, Nota.id == NotaItem.nota_id)
        .where(NotaItem.produto_id == produto_id, Nota.natureza != "ACERTO",
               Nota.status != "cancelada", Nota.data_mov.is_not(None))).all()
    return sum(float(i.quantidade) * (1 if n.tipo == "E" else -1) for i, n in itens)


def test_saldo_por_produto_bate_com_o_painel(db):
    divergentes = []
    for produto in db.execute(select(Produto)).scalars():
        if produto.descricao not in PAINEL:
            continue    # produto novo, adicionado depois da migracao (ex.: Mini Lingote de Magnesio)
        esperado = PAINEL[produto.descricao]
        obtido = _saldo_planilha(db, produto.id)
        if produto.descricao == "SUCATA DE MAGNESIO":
            # Duas diferencas conhecidas e explicadas na Fase 1:
            #   +41.528,4 kg gravados como "SUCATA DE MAGNÉSIO" que a lista do painel nao soma
            #   +990,0 kg de uma saida sem data (NF 5802), que a base recusa e manda para excecoes
            assert abs(obtido - (esperado + 41528.4 + 990.0)) < 0.5, produto.descricao
            continue
        if abs(obtido - esperado) > 0.5:
            divergentes.append((produto.descricao, esperado, obtido))
    assert not divergentes, divergentes


def test_nenhum_saldo_negativo_em_nenhuma_data(db):
    """Decisao 1: o acerto datado tem que impedir o negativo em toda a linha do tempo."""
    for produto in db.execute(select(Produto)).scalars():
        for linha in est.razao(db, produto.id):
            assert linha["saldo"] >= -0.5, (produto.descricao, linha["data"], linha["saldo"])


def test_total_de_acertos_gerados(db):
    total = 0.0
    for produto in db.execute(select(Produto)).scalars():
        total += sum(
            float(i.quantidade) for i, n in db.execute(
                select(NotaItem, Nota).join(Nota, Nota.id == NotaItem.nota_id)
                .where(NotaItem.produto_id == produto.id, Nota.natureza == "ACERTO")).all())
    assert abs(total - ACERTOS_ESPERADOS) < 0.5


def test_estoque_valorizado(db):
    pos = est.posicao(db)
    assert abs(sum(p["saldo_kg"] for p in pos) - 2137609.0) < 1
    assert sum(p["saldo_rs"] for p in pos) > 0
    for p in pos:
        assert p["saldo_kg"] >= 0
        if p["saldo_kg"] > 0:
            assert p["custo_medio"] and p["custo_medio"] > 0


def test_recalculo_e_idempotente(db):
    antes = est.posicao(db)
    ids = db.execute(select(Produto.id)).scalars().all()
    est.recalcular_varios(db, ids, "teste")
    db.commit()
    depois = est.posicao(db)
    for a, b in zip(antes, depois):
        assert abs(a["saldo_kg"] - b["saldo_kg"]) < 0.001
        assert abs(a["saldo_rs"] - b["saldo_rs"]) < 0.01
