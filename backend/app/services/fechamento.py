"""Fechamento de competencia.

Decisao de 27/08/2026: mes fechado nao muda sozinho. Para lancar dentro dele alguem reabre
explicitamente, com motivo, e a reabertura fica gravada. E' o que sustenta um numero ja' entregue
a' contabilidade - na planilha, corrigir uma linha antiga mudava um mes fechado em silencio.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ApuracaoMes, Auditoria, Nota
from . import apuracao as ap


class CompetenciaFechada(Exception):
    def __init__(self, competencia: str, fechada_em, fechada_por):
        self.competencia = competencia
        self.mensagem = (
            f"A competência {competencia} está fechada desde "
            f"{fechada_em:%d/%m/%Y às %H:%M} por {fechada_por}. Para lançar nesta data, reabra a "
            "competência informando o motivo — a reabertura fica registrada.")
        super().__init__(self.mensagem)


def competencia_de(data: dt.date) -> str:
    return f"{data.year}-{data.month:02d}"


def registro(db: Session, competencia: str) -> ApuracaoMes | None:
    return db.execute(select(ApuracaoMes)
                      .where(ApuracaoMes.competencia == competencia)).scalars().first()


def exigir_aberta(db: Session, data: dt.date):
    comp = competencia_de(data)
    reg = registro(db, comp)
    if reg and reg.status == "fechada":
        raise CompetenciaFechada(comp, reg.fechada_em, reg.fechada_por)


def fechar(db: Session, competencia: str, usuario: str) -> ApuracaoMes:
    """Congela os totais da competencia. Os lancamentos continuam la': o que trava e' a edicao."""
    reg = registro(db, competencia)
    if reg and reg.status == "fechada":
        raise CompetenciaFechada(competencia, reg.fechada_em, reg.fechada_por)
    dados = ap.previa(db, competencia)
    if reg is None:
        reg = ApuracaoMes(competencia=competencia)
        db.add(reg)
    for campo in ("base_beneficiada", "debito", "credito_presumido", "estorno", "devolucao_icms",
                  "icms_recolher", "fundo_social", "fundo_educacao", "carga_efetiva"):
        setattr(reg, campo, dados[campo])
    reg.status = "fechada"
    reg.fechada_em = dt.datetime.now()
    reg.fechada_por = usuario
    db.flush()
    db.add(Auditoria(tabela="apuracao_mes", registro_id=reg.id, operacao="FECHAR", usuario=usuario,
                     antes=None, depois=dict(competencia=competencia,
                                             icms_recolher=dados["icms_recolher"],
                                             base=dados["base_beneficiada"])))
    db.commit()
    db.refresh(reg)
    return reg


def reabrir(db: Session, competencia: str, motivo: str, usuario: str) -> ApuracaoMes:
    reg = registro(db, competencia)
    if reg is None or reg.status != "fechada":
        raise ValueError(f"A competência {competencia} não está fechada")
    if not motivo or len(motivo.strip()) < 5:
        raise ValueError("Informe o motivo da reabertura (pelo menos algumas palavras).")
    db.add(Auditoria(tabela="apuracao_mes", registro_id=reg.id, operacao="REABRIR", usuario=usuario,
                     antes=dict(status="fechada", fechada_por=reg.fechada_por,
                                icms_recolher=float(reg.icms_recolher or 0)),
                     depois=dict(status="aberta", motivo=motivo)))
    reg.status = "aberta"
    db.commit()
    db.refresh(reg)
    return reg


def historico(db: Session, competencia: str) -> list[dict]:
    reg = registro(db, competencia)
    if reg is None:
        return []
    linhas = db.execute(
        select(Auditoria).where(Auditoria.tabela == "apuracao_mes", Auditoria.registro_id == reg.id)
        .order_by(Auditoria.em.desc())).scalars().all()
    return [dict(operacao=a.operacao, usuario=a.usuario, em=a.em, antes=a.antes, depois=a.depois)
            for a in linhas]


def comparar_com_fechamento(db: Session, competencia: str) -> dict | None:
    """Mostra se os lancamentos de hoje ainda batem com o que foi congelado no fechamento."""
    reg = registro(db, competencia)
    if reg is None or reg.status != "fechada":
        return None
    atual = ap.previa(db, competencia)
    campos = ("base_beneficiada", "debito", "credito_presumido", "estorno", "icms_recolher",
              "fundo_social", "fundo_educacao")
    difs = {c: round(atual[c] - float(getattr(reg, c) or 0), 2) for c in campos}
    return dict(congelado={c: float(getattr(reg, c) or 0) for c in campos}, atual=
                {c: atual[c] for c in campos}, diferencas=difs,
                coerente=all(abs(v) < 0.01 for v in difs.values()))


def lista(db: Session, limite: int = 36) -> list[dict]:
    """Todas as competencias que tem lancamento, com o status de cada uma."""
    comps = db.execute(select(Nota.data_mov).where(Nota.status != "cancelada")).scalars().all()
    meses = sorted({competencia_de(d) for d in comps if d}, reverse=True)[:limite]
    regs = {r.competencia: r for r in db.execute(select(ApuracaoMes)).scalars()}
    saida = []
    for m in meses:
        r = regs.get(m)
        saida.append(dict(competencia=m, status=r.status if r else "aberta",
                          icms_recolher=float(r.icms_recolher or 0) if r else None,
                          fechada_em=r.fechada_em if r else None,
                          fechada_por=r.fechada_por if r else None))
    return saida
