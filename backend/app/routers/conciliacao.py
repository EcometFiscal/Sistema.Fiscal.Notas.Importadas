"""Conciliação e Fechamento de ICMS (normal, empresa toda) - fase 1.

A ingestão de uma competência roda hoje por script local (scripts/importar_conciliacao_icms.py),
não por uma rota desta API - ver a nota em services/conciliacao/ingestao.py sobre o pdftotext
não estar disponível na função serverless. Estas rotas só leem/editam o que já foi gravado.
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ConcDivergencia, ConcPeriodo

router = APIRouter(prefix="/conciliacao", tags=["conciliacao"])


def _periodo_ou_404(db: Session, competencia: str) -> ConcPeriodo:
    p = db.execute(select(ConcPeriodo).where(ConcPeriodo.competencia == competencia)
                   ).scalars().first()
    if not p:
        raise HTTPException(404, detail=dict(
            mensagem=f"Nenhuma competência de conciliação de ICMS importada para {competencia}."))
    return p


@router.get("/periodos")
def periodos(db: Session = Depends(get_db)):
    linhas = db.execute(select(ConcPeriodo).order_by(ConcPeriodo.competencia.desc())).scalars().all()
    out = []
    for p in linhas:
        abertas = [d for d in p.divergencias if d.status == "aberta"]
        out.append(dict(
            id=p.id, competencia=p.competencia, inscricao_estadual=p.inscricao_estadual,
            status=p.status, saldo_credor_anterior=float(p.saldo_credor_anterior or 0),
            divergencias_abertas=len(abertas),
            divergencias_altas=len([d for d in abertas if d.severidade == "alto"]),
            criado_em=p.criado_em))
    return out


@router.get("/periodos/{competencia}")
def periodo(competencia: str, db: Session = Depends(get_db)):
    p = _periodo_ou_404(db, competencia)
    saldos = [dict(fonte=s.fonte, tipo=s.tipo, cfop=s.cfop, valor_contabil=float(s.valor_contabil),
                   base_calculo=float(s.base_calculo), imposto=float(s.imposto),
                   isentas=float(s.isentas), outras=float(s.outras), difal=float(s.difal))
              for s in p.saldos]
    divergencias = [dict(id=d.id, tipo=d.tipo, severidade=d.severidade, status=d.status,
                         cfop=d.cfop, numero_nota=d.numero_nota, descricao=d.descricao,
                         valor_contabilidade=(float(d.valor_contabilidade)
                                              if d.valor_contabilidade is not None else None),
                         valor_ecomet=float(d.valor_ecomet) if d.valor_ecomet is not None else None,
                         diferenca=float(d.diferenca) if d.diferenca is not None else None,
                         justificativa=d.justificativa)
                    for d in sorted(p.divergencias,
                                    key=lambda d: (d.status != "aberta", d.severidade != "alto"))]
    apuracao = [dict(grupo=l.grupo, ordem=l.ordem, rotulo=l.rotulo, valor=float(l.valor),
                     origem_texto=l.origem_texto, editavel=l.editavel)
               for l in sorted(p.linhas_apuracao, key=lambda l: (l.grupo, l.ordem))]
    documentos = [dict(tipo=d.tipo, origem=d.origem, nome_original=d.nome_original,
                       conferido=d.conferido, total_extraido=(float(d.total_extraido)
                                                               if d.total_extraido is not None else None),
                       lido_em=d.lido_em)
                 for d in p.documentos]
    return dict(id=p.id, competencia=p.competencia, inscricao_estadual=p.inscricao_estadual,
               status=p.status, saldo_credor_anterior=float(p.saldo_credor_anterior or 0),
               saldos=saldos, divergencias=divergencias, apuracao=apuracao, documentos=documentos)


class JustificativaIn(BaseModel):
    justificativa: str
    status: str = "justificada"   # justificada | corrigida_ecomet | devolvida_contabilidade


@router.post("/divergencias/{divergencia_id}/justificar")
def justificar(divergencia_id: int, dados: JustificativaIn, db: Session = Depends(get_db),
               x_usuario: str = Header(default="fiscal")):
    d = db.get(ConcDivergencia, divergencia_id)
    if not d:
        raise HTTPException(404, detail=dict(mensagem="Divergência não encontrada."))
    if dados.status not in ("justificada", "corrigida_ecomet", "devolvida_contabilidade", "aberta"):
        raise HTTPException(400, detail=dict(mensagem="Status inválido."))
    d.justificativa = dados.justificativa
    d.status = dados.status
    d.responsavel = x_usuario
    if dados.status != "aberta":
        import datetime as dt
        d.resolvido_em = dt.datetime.utcnow()
    else:
        d.resolvido_em = None
    db.commit()
    return dict(id=d.id, status=d.status, justificativa=d.justificativa)
