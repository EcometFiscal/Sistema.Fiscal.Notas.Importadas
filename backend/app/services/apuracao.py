"""Motor de apuracao TTD 409/410/411.

As formulas foram extraidas da planilha atual e validadas contra julho/2026 centavo a centavo,
inclusive a que estava implicita e nao aparecia escrita em lugar nenhum:
    ICMS a recolher = (debito + estorno) - (credito presumido + devolucao de ICMS)

Fase 2 entrega isto como PREVIA: o lancamento ja' alimenta os dois lados. O fechamento de
competencia com trava e' Fase 3/4.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ApuracaoMes, Nota, NotaItem, RegraTTD

PADRAO = [
    ("1", "Interestadual 12%", 0.12, 0.114, 0.006),
    ("2", "Interestadual - mercadoria importada 4%", 0.04, 0.030, 0.010),
    ("3", "Interna 12%", 0.12, 0.099, 0.021),
]


def semear_regras(db: Session, inicio: dt.date = dt.date(2020, 1, 1)):
    if db.execute(select(RegraTTD.id)).first():
        return
    for bloco, desc, aliq, pres, carga in PADRAO:
        db.add(RegraTTD(bloco=bloco, descricao=desc, aliquota=aliq, aliq_presumido=pres,
                        carga_efetiva=carga, vigencia_inicio=inicio, alterado_por="migracao"))
    db.flush()


def regra(db: Session, bloco: str, data: dt.date) -> RegraTTD | None:
    return db.execute(
        select(RegraTTD).where(RegraTTD.bloco == bloco, RegraTTD.vigencia_inicio <= data,
                               (RegraTTD.vigencia_fim.is_(None)) | (RegraTTD.vigencia_fim >= data))
        .order_by(RegraTTD.vigencia_inicio.desc())).scalars().first()


def _d(v):
    return Decimal(str(v or 0))


def previa(db: Session, competencia: str) -> dict:
    """Apuracao derivada dos lancamentos da competencia. Nada e' congelado em celula."""
    ano, mes = (int(x) for x in competencia.split("-"))
    ini = dt.date(ano, mes, 1)
    fim = dt.date(ano + (mes == 12), (mes % 12) + 1, 1) - dt.timedelta(days=1)
    linhas = db.execute(
        select(NotaItem, Nota).join(Nota, Nota.id == NotaItem.nota_id)
        .where(Nota.data_mov.between(ini, fim), Nota.status != "cancelada",
               Nota.natureza != "ACERTO", NotaItem.bloco_ttd.is_not(None))).all()

    blocos: dict[str, dict] = {}
    debito = cp = dev_icms = estorno = base = base_dev = _d(0)
    detalhe = []
    for item, nota in linhas:
        r = regra(db, item.bloco_ttd, nota.data_mov)
        if r is None:
            continue
        b = _d(item.base_calculo if item.base_calculo is not None else item.valor)
        icms, pres = b * _d(r.aliquota), b * _d(r.aliq_presumido)
        devolucao = nota.natureza == "DEVOLUCAO"
        k = f"{item.bloco_ttd}{'D' if devolucao else ''}"
        d = blocos.setdefault(k, dict(bloco=item.bloco_ttd, devolucao=devolucao,
                                      descricao=r.descricao, aliquota=float(r.aliquota),
                                      aliq_presumido=float(r.aliq_presumido),
                                      base=0.0, icms=0.0, credito_presumido=0.0, notas=0))
        d["base"] += float(b); d["icms"] += float(icms)
        d["credito_presumido"] += float(pres); d["notas"] += 1
        if devolucao:
            dev_icms += icms; estorno += pres; base_dev += b
        else:
            debito += icms; cp += pres; base += b
        detalhe.append(dict(nota_id=nota.id, numero=nota.numero, data=nota.data_mov,
                            parceiro=nota.parceiro.nome if nota.parceiro else None,
                            produto=item.produto.descricao, bloco=k, base=float(b),
                            icms=float(icms), credito_presumido=float(pres)))

    icms_recolher = (debito + estorno) - (cp + dev_icms)
    a, b2, c = base * _d(0.004), cp * _d(0.02), cp * _d(0.025)
    fs_v = c + (a - (b2 + c))
    a2, b3, c2 = base_dev * _d(0.004), estorno * _d(0.02), estorno * _d(0.025)
    fs_d = c2 + (a2 - (b3 + c2))
    return dict(
        competencia=competencia,
        base_beneficiada=float(base), debito=float(debito), credito_presumido=float(cp),
        devolucao_icms=float(dev_icms), estorno=float(estorno),
        icms_deduzir=float(debito - dev_icms), icms_recolher=float(icms_recolher),
        fundo_social=float(fs_v - fs_d), fundo_educacao=float(cp * _d(0.02) - estorno * _d(0.02)),
        carga_efetiva=float(icms_recolher / base * 100) if base else 0.0,
        blocos=sorted(blocos.values(), key=lambda x: (x["devolucao"], x["bloco"])),
        lancamentos=sorted(detalhe, key=lambda x: (x["bloco"], x["data"])),
        status=(db.execute(select(ApuracaoMes.status)
                           .where(ApuracaoMes.competencia == competencia)).scalar() or "aberta"))


def bloco_sugerido(uf_destino: str | None, exterior: bool = False) -> str | None:
    """Sugestao, nao imposicao. Sem origem por item (decisao 5) o sistema nao decide sozinho
    entre o bloco 1 e o 2 - quem lanca confirma."""
    if exterior:
        return None
    if not uf_destino:
        return None
    return "3" if uf_destino.upper() == "SC" else "2"
