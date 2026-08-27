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

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import ApuracaoMes, Nota, NotaItem, Produto, RegraTTD

# Regra real do TTD 409: por produto (NCM) e ambito da operacao, nao por CFOP. Cobre, aluminio
# e magnesio saem do beneficio (aliquota 0, sem bloco) na operacao interna - so' tem linha para
# interestadual. Silicio cobra igual nos dois ambitos, por isso tem as duas linhas.
TABELA_TTD = [
    # ncm,        ambito,          bloco, descricao,                                   aliq,  presumido, carga
    ("74040000", "interestadual", "1", "Interestadual 12%",                        0.12, 0.114, 0.006),
    ("76020000", "interestadual", "2", "Interestadual - mercadoria importada 4%",  0.04, 0.030, 0.010),
    ("76011000", "interestadual", "2", "Interestadual - mercadoria importada 4%",  0.04, 0.030, 0.010),
    ("81042000", "interestadual", "2", "Interestadual - mercadoria importada 4%",  0.04, 0.030, 0.010),
    ("81041100", "interestadual", "2", "Interestadual - mercadoria importada 4%",  0.04, 0.030, 0.010),
    ("28046900", "interna",       "3", "Silicio metalico 12%",                     0.12, 0.099, 0.021),
    ("28046900", "interestadual", "3", "Silicio metalico 12%",                     0.12, 0.099, 0.021),
]

# NCM cadastral por produto - so' preenche Produto.ncm/NotaItem.ncm (descritivo), nunca bloco_ttd.
PRODUTO_NCM = {
    "SUCATA DE COBRE": "74040000",
    "SUCATA DE ALUMINIO": "76020000",
    "LINGOTE DE ALUMINIO": "76011000",
    "SUCATA DE MAGNESIO": "81042000",
    "LINGOTE DE MAGNESIO": "81041100",
    "SILICIO METALICO": "28046900",
}


def semear_regras(db: Session, inicio: dt.date = dt.date(2020, 1, 1)):
    if db.execute(select(RegraTTD.id)).first():
        return
    for ncm, ambito, bloco, desc, aliq, pres, carga in TABELA_TTD:
        db.add(RegraTTD(ncm=ncm, ambito=ambito, bloco=bloco, descricao=desc, aliquota=aliq,
                        aliq_presumido=pres, carga_efetiva=carga, vigencia_inicio=inicio,
                        alterado_por="migracao"))
    db.flush()


def backfill_ncm_produtos(db: Session) -> int:
    """Preenche o NCM cadastral dos 6 produtos conhecidos e propaga para nota_item que ainda
    nao tem NCM. So' descritivo/relatorio - nunca mexe em bloco_ttd, valor ou aliquota, que sao
    os campos que a apuracao soma."""
    alterados = 0
    for descricao, ncm in PRODUTO_NCM.items():
        p = db.execute(select(Produto).where(Produto.descricao == descricao)).scalars().first()
        if p and p.ncm != ncm:
            p.ncm = ncm
            alterados += 1
    db.flush()
    db.execute(update(NotaItem)
              .values(ncm=select(Produto.ncm).where(Produto.id == NotaItem.produto_id)
                      .scalar_subquery())
              .where(NotaItem.ncm.is_(None)))
    return alterados


def regra(db: Session, bloco: str, data: dt.date) -> RegraTTD | None:
    """Regra pelo bloco (1/2/3) - usada pela exportacao e pelo endpoint /regras, que ainda
    falam a linguagem de bloco. Varias linhas de NCM podem compartilhar bloco; a aliquota e'
    identica entre elas por desenho (mesma tabela), entao pegar qualquer uma que bate e' seguro."""
    return db.execute(
        select(RegraTTD).where(RegraTTD.bloco == bloco, RegraTTD.vigencia_inicio <= data,
                               (RegraTTD.vigencia_fim.is_(None)) | (RegraTTD.vigencia_fim >= data))
        .order_by(RegraTTD.vigencia_inicio.desc())).scalars().first()


def regra_produto(db: Session, ncm: str, ambito: str, data: dt.date) -> RegraTTD | None:
    """Regra por NCM + ambito - a que decide o bloco na importacao de XML."""
    return db.execute(
        select(RegraTTD).where(RegraTTD.ncm == ncm, RegraTTD.ambito == ambito,
                               RegraTTD.vigencia_inicio <= data,
                               (RegraTTD.vigencia_fim.is_(None)) | (RegraTTD.vigencia_fim >= data))
        .order_by(RegraTTD.vigencia_inicio.desc())).scalars().first()


def ncm_tem_regra(db: Session, ncm: str, data: dt.date) -> bool:
    """NCM reconhecido em algum ambito (mesmo que nao tenha linha para o ambito desta operacao -
    nesse caso e' aliquota 0/fora do beneficio, nao NCM desconhecido)."""
    return db.execute(
        select(RegraTTD.id).where(RegraTTD.ncm == ncm, RegraTTD.vigencia_inicio <= data,
                                  (RegraTTD.vigencia_fim.is_(None)) | (RegraTTD.vigencia_fim >= data))
        .limit(1)).scalar() is not None


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
