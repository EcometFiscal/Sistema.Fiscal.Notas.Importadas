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
ACERTOS_ESPERADOS = 24960.0 + 28059.5   # decisao 1 (revertida 30/08/2026): os dois pontos onde
                                        # a decisao antiga teria lancado acerto - agora ficam
                                        # negativos em vez disso. Produto 1 = LINGOTE DE ALUMINIO
                                        # (NF 596 + NF 640, dez/2020), produto 4 = SUCATA DE
                                        # ALUMINIO (NF 2050 + NF 2111, set/2022).


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


def test_saldo_fica_negativo_onde_antes_tinha_acerto(db):
    """Decisao de 30/08/2026: sem acerto datado, os dois pontos onde a saida excedeu o saldo
    (dez/2020 no Lingote de Aluminio, set/2022 na Sucata de Aluminio) ficam negativos na linha
    do tempo em vez de serem tapados por um lancamento fake."""
    linhas1 = est.razao(db, 1, de=dt.date(2020, 11, 1), ate=dt.date(2020, 12, 31))
    minimo1 = min(l["saldo"] for l in linhas1)
    assert abs(minimo1 - (-24960.0)) < 0.5, minimo1     # LINGOTE DE ALUMINIO, NF 596 + NF 640

    linhas4 = est.razao(db, 4, de=dt.date(2022, 9, 1), ate=dt.date(2022, 9, 30))
    minimo4 = min(l["saldo"] for l in linhas4)
    assert abs(minimo4 - (-28059.5)) < 0.5, minimo4     # SUCATA DE ALUMINIO, NF 2050 + NF 2111


def test_nenhuma_nota_acerto_e_criada(db):
    """Decisao de 30/08/2026: nao existe mais nota natureza=='ACERTO' - o saldo fica negativo em
    vez de ganhar um lote fake pra cobrir a diferenca."""
    acertos = db.execute(select(Nota).where(Nota.natureza == "ACERTO")).scalars().all()
    assert not acertos


def test_estoque_valorizado(db):
    pos = est.posicao(db)
    # 2.137.609,0 kg de quando a decisao 1 ainda tapava os dois pontos negativos com acerto,
    # menos os 53.019,5 kg (24.960,0 + 28.059,5) que eram lote fake e deixaram de existir.
    assert abs(sum(p["saldo_kg"] for p in pos) - (2137609.0 - ACERTOS_ESPERADOS)) < 1
    assert sum(p["saldo_rs"] for p in pos) > 0
    for p in pos:
        if p["saldo_kg"] > 0:
            assert p["custo_medio"] and p["custo_medio"] > 0
        else:
            assert p["custo_medio"] is None    # saldo <= 0 nao tem custo medio por kg positivo


def test_recalculo_e_idempotente(db):
    antes = est.posicao(db)
    ids = db.execute(select(Produto.id)).scalars().all()
    est.recalcular_varios(db, ids, "teste")
    db.commit()
    depois = est.posicao(db)
    for a, b in zip(antes, depois):
        assert abs(a["saldo_kg"] - b["saldo_kg"]) < 0.001
        assert abs(a["saldo_rs"] - b["saldo_rs"]) < 0.01
