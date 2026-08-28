"""Saldo e custeio PEPS.

Decisao 5: o controle e' pelo SALDO do produto. Nao existe vinculo fiscal entre a nota de
saida e uma nota de entrada especifica - o PEPS roda aqui apenas para custear o estoque.
Decisao 1 de 27/08/2026 (saida sem saldo gera lancamento de acerto, saldo nunca fica negativo)
foi REVERTIDA em 30/08/2026 a pedido do Victor: o sistema nao lanca mais acerto de estoque.
Quando uma saida excede o saldo, o saldo do produto fica negativo dali em diante - mas o custo
da parte sem lastro continua estimado e contabilizado (ver custo_estimado()), so' que direto no
NotaItem.custo_total da propria saida, sem nota fake nem ConsumoEstoque apontando pra lote que
nao existe.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Iterable

from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.orm import Session

from ..models import ConsumoEstoque, Excecao, Nota, NotaItem, Produto

ZERO = Decimal("0")
EPS = Decimal("0.0005")


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def movimentos(db: Session, produto_id: int, ate: dt.date | None = None):
    q = (select(NotaItem, Nota)
         .join(Nota, Nota.id == NotaItem.nota_id)
         .where(NotaItem.produto_id == produto_id,
                Nota.data_mov.is_not(None),
                Nota.status != "cancelada"))
    if ate:
        q = q.where(Nota.data_mov <= ate)
    # Entrada antes de saida no mesmo dia: a mercadoria chega para poder sair. Isso tambem
    # torna o recalculo idempotente - o acerto criado na data D e' consumido pela saida do dia D
    # na proxima passada, em vez de sobrar como lote solto.
    return db.execute(q.order_by(Nota.data_mov, Nota.tipo.asc(), Nota.id, NotaItem.id)).all()


def saldo(db: Session, produto_id: int, ate: dt.date | None = None) -> Decimal:
    q = (select(func.coalesce(func.sum(
            case((Nota.tipo == "E", NotaItem.quantidade), else_=-NotaItem.quantidade)), 0))
         .join(Nota, Nota.id == NotaItem.nota_id)
         .where(NotaItem.produto_id == produto_id, Nota.data_mov.is_not(None),
                Nota.status != "cancelada"))
    if ate:
        q = q.where(Nota.data_mov <= ate)
    return _d(db.execute(q).scalar_one())


def custo_estimado(db: Session, produto_id: int, data: dt.date) -> Decimal:
    """Custo do acerto: media ponderada das entradas reais anteriores; depois a primeira
    entrada posterior; por ultimo o preco medio de saida do proprio produto."""
    r = db.execute(
        select(func.sum(NotaItem.valor), func.sum(NotaItem.quantidade))
        .join(Nota, Nota.id == NotaItem.nota_id)
        .where(NotaItem.produto_id == produto_id, Nota.tipo == "E",
               Nota.natureza != "ACERTO", Nota.data_mov <= data,
               NotaItem.valor.is_not(None), NotaItem.quantidade > 0)).first()
    if r and r[0] and r[1]:
        return _d(r[0]) / _d(r[1])
    r = db.execute(
        select(NotaItem.custo_unit).join(Nota, Nota.id == NotaItem.nota_id)
        .where(NotaItem.produto_id == produto_id, Nota.tipo == "E",
               Nota.natureza != "ACERTO", NotaItem.custo_unit.is_not(None))
        .order_by(Nota.data_mov).limit(1)).first()
    if r and r[0]:
        return _d(r[0])
    r = db.execute(
        select(func.sum(NotaItem.valor), func.sum(NotaItem.quantidade))
        .join(Nota, Nota.id == NotaItem.nota_id)
        .where(NotaItem.produto_id == produto_id, Nota.tipo == "S",
               NotaItem.valor.is_not(None), NotaItem.quantidade > 0)).first()
    if r and r[0] and r[1]:
        return _d(r[0]) / _d(r[1])
    return ZERO


def _limpar_custeio(db: Session, produto_id: int):
    db.execute(delete(ConsumoEstoque).where(ConsumoEstoque.produto_id == produto_id))
    acertos = db.execute(
        select(Nota.id).join(NotaItem, NotaItem.nota_id == Nota.id)
        .where(Nota.natureza == "ACERTO", NotaItem.produto_id == produto_id)).scalars().all()
    if acertos:
        db.execute(delete(Excecao).where(Excecao.nota_id.in_(acertos)))
        db.execute(delete(NotaItem).where(NotaItem.nota_id.in_(acertos)))
        db.execute(delete(Nota).where(Nota.id.in_(acertos)))
    # "acerto_automatico" e' o tipo antigo (decisao revertida em 30/08/2026) - o filtro cobre os
    # dois nomes pra limpar o que ja existia na migracao E nao empilhar "saldo_negativo"
    # duplicado toda vez que o recalculo roda de novo (a cada nota nova, cancelamento, etc.).
    db.execute(delete(Excecao).where(and_(Excecao.tipo.in_(("acerto_automatico", "saldo_negativo")),
                                          Excecao.produto_id == produto_id)))
    db.flush()


def recalcular_custeio(db: Session, produto_id: int, usuario: str = "sistema") -> dict:
    """Refaz o PEPS do produto inteiro. Idempotente: rodar duas vezes da' o mesmo resultado."""
    _limpar_custeio(db, produto_id)
    lotes: list[list] = []          # [item_entrada_id, qtd_restante, custo]
    negativos, consumos = 0, 0
    for item, nota in movimentos(db, produto_id):
        qtd = _d(item.quantidade)
        if nota.tipo == "E":
            if qtd > 0:
                lotes.append([item.id, qtd, _d(item.custo_unit) if item.custo_unit is not None
                              else (_d(item.valor) / qtd if item.valor else ZERO)])
            continue
        restante, custo_total = qtd, ZERO
        while restante > EPS and lotes:
            lote = lotes[0]
            usa = min(restante, lote[1])
            db.add(ConsumoEstoque(item_saida_id=item.id, item_entrada_id=lote[0],
                                  produto_id=produto_id, quantidade=float(usa),
                                  custo_unitario=float(lote[2]), metodo="PEPS"))
            consumos += 1
            custo_total += usa * lote[2]
            lote[1] -= usa
            restante -= usa
            if lote[1] <= EPS:
                lotes.pop(0)
        if restante > EPS:
            # Decisao de 30/08/2026: nao cria mais lote fake (nota ACERTO) pra cobrir a
            # diferenca. O saldo do produto fica negativo dali em diante - so' o custo da parte
            # sem lastro continua estimado e vai direto no custo_total da propria saida.
            custo = custo_estimado(db, produto_id, nota.data_mov)
            custo_total += restante * custo
            db.add(Excecao(tipo="saldo_negativo", nota_id=nota.id, produto_id=produto_id,
                           quantidade=float(restante), valor=float(restante * custo),
                           criado_por=usuario,
                           descricao=(f"Saída NF {nota.numero} de "
                                      f"{nota.data_mov:%d/%m/%Y} excedeu o saldo em "
                                      f"{float(restante):.1f} kg. Custo estimado em R$ "
                                      f"{float(custo):.4f}/kg. Saldo do produto fica negativo "
                                      "até uma entrada real cobrir a diferença "
                                      "(decisão de 30/08/2026).")))
            negativos += 1
        item.custo_total = float(custo_total)
    db.flush()
    return dict(produto_id=produto_id, consumos=consumos, negativos=negativos)


def recalcular_varios(db: Session, produto_ids: Iterable[int], usuario: str = "sistema"):
    return [recalcular_custeio(db, p, usuario) for p in dict.fromkeys(produto_ids)]


def posicao(db: Session, ate: dt.date | None = None) -> list[dict]:
    """Saldo em kg e em R$ por produto. O valor vem dos lotes ainda nao consumidos - e quando a
    saida excede os lotes disponiveis (saldo negativo), o excedente entra pelo custo estimado,
    senao o valor ficaria subestimado exatamente onde o saldo fica negativo (decisao de
    30/08/2026: nao ha' mais lote fake de acerto pra "fechar a conta" sozinho)."""
    out = []
    for produto in db.execute(select(Produto).order_by(Produto.descricao)).scalars():
        lotes: list[list] = []
        saldo_kg = ZERO
        valor = ZERO
        for item, nota in movimentos(db, produto.id, ate):
            qtd = _d(item.quantidade)
            if nota.tipo == "E":
                saldo_kg += qtd
                if qtd > 0:
                    custo = _d(item.custo_unit) if item.custo_unit is not None \
                        else (_d(item.valor) / qtd if item.valor else ZERO)
                    lotes.append([qtd, custo])
                    valor += qtd * custo
            else:
                saldo_kg -= qtd
                restante = qtd
                while restante > EPS and lotes:
                    usa = min(restante, lotes[0][0])
                    valor -= usa * lotes[0][1]
                    lotes[0][0] -= usa
                    restante -= usa
                    if lotes[0][0] <= EPS:
                        lotes.pop(0)
                if restante > EPS:
                    custo = custo_estimado(db, produto.id, nota.data_mov)
                    valor -= restante * custo
        out.append(dict(produto_id=produto.id, produto=produto.descricao, unidade=produto.unidade,
                        saldo_kg=float(saldo_kg), saldo_rs=float(valor),
                        custo_medio=float(valor / saldo_kg) if saldo_kg > 0 else None))
    return out


def razao(db: Session, produto_id: int, de: dt.date | None = None, ate: dt.date | None = None):
    """Extrato linha a linha com saldo corrido - a conferencia que a planilha nunca teve."""
    linhas, corrente = [], ZERO
    for item, nota in movimentos(db, produto_id, ate):
        qtd = _d(item.quantidade)
        corrente += qtd if nota.tipo == "E" else -qtd
        if de and nota.data_mov < de:
            continue
        linhas.append(dict(data=nota.data_mov, tipo=nota.tipo, natureza=nota.natureza,
                           nota_id=nota.id, numero=nota.numero,
                           parceiro=nota.parceiro.nome if nota.parceiro else None,
                           quantidade=float(qtd), valor=float(_d(item.valor)),
                           custo_total=float(_d(item.custo_total)) if item.custo_total else None,
                           saldo=float(corrente)))
    return linhas


def cobertura_dias(db: Session, produto_id: int, saldo_kg: float, dias: int = 90) -> float | None:
    """Quantos dias o saldo dura no ritmo dos ultimos 90 dias de saida."""
    hoje = dt.date.today()
    r = db.execute(
        select(func.coalesce(func.sum(NotaItem.quantidade), 0))
        .join(Nota, Nota.id == NotaItem.nota_id)
        .where(NotaItem.produto_id == produto_id, Nota.tipo == "S",
               Nota.data_mov >= hoje - dt.timedelta(days=dias), Nota.status != "cancelada")).scalar_one()
    media = _d(r) / dias
    return float(_d(saldo_kg) / media) if media > 0 else None
