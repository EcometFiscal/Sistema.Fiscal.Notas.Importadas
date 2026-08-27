import datetime as dt

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Auditoria, RegraTTD
from ..services import fechamento as fec
from ..services.apuracao import previa

router = APIRouter(tags=["apuracao"])


@router.get("/competencias")
def competencias(db: Session = Depends(get_db)):
    return fec.lista(db)


@router.get("/apuracao/{competencia}")
def apurar(competencia: str, db: Session = Depends(get_db)):
    dados = previa(db, competencia)
    reg = fec.registro(db, competencia)
    dados["fechamento"] = (None if not reg else dict(
        status=reg.status, fechada_em=reg.fechada_em, fechada_por=reg.fechada_por,
        icms_congelado=float(reg.icms_recolher or 0)))
    dados["conferencia"] = fec.comparar_com_fechamento(db, competencia)
    return dados


@router.post("/apuracao/{competencia}/fechar")
def fechar(competencia: str, db: Session = Depends(get_db),
           x_usuario: str = Header(default="fiscal")):
    try:
        reg = fec.fechar(db, competencia, x_usuario)
    except fec.CompetenciaFechada as e:
        raise HTTPException(409, detail=dict(mensagem=e.mensagem))
    return dict(competencia=reg.competencia, status=reg.status, fechada_em=reg.fechada_em,
                fechada_por=reg.fechada_por, icms_recolher=float(reg.icms_recolher or 0))


class Reabertura(BaseModel):
    motivo: str


@router.post("/apuracao/{competencia}/reabrir")
def reabrir(competencia: str, dados: Reabertura, db: Session = Depends(get_db),
            x_usuario: str = Header(default="fiscal")):
    try:
        reg = fec.reabrir(db, competencia, dados.motivo, x_usuario)
    except ValueError as e:
        raise HTTPException(400, detail=dict(mensagem=str(e)))
    return dict(competencia=reg.competencia, status=reg.status)


@router.get("/apuracao/{competencia}/historico")
def historico(competencia: str, db: Session = Depends(get_db)):
    return fec.historico(db, competencia)


class RegraIn(BaseModel):
    ncm: str
    ambito: str          # interna | interestadual
    bloco: str
    descricao: str
    aliquota: float
    aliq_presumido: float
    carga_efetiva: float
    vigencia_inicio: dt.date


@router.get("/regras")
def regras(db: Session = Depends(get_db)):
    linhas = db.execute(select(RegraTTD).order_by(RegraTTD.bloco, RegraTTD.ncm, RegraTTD.ambito,
                                                  RegraTTD.vigencia_inicio.desc())).scalars().all()
    return [dict(id=r.id, ncm=r.ncm, ambito=r.ambito, bloco=r.bloco, descricao=r.descricao,
                 aliquota=float(r.aliquota), aliq_presumido=float(r.aliq_presumido),
                 carga_efetiva=float(r.carga_efetiva), vigencia_inicio=r.vigencia_inicio,
                 vigencia_fim=r.vigencia_fim, alterado_por=r.alterado_por,
                 alterado_em=r.alterado_em) for r in linhas]


@router.post("/regras", status_code=201)
def nova_regra(dados: RegraIn, db: Session = Depends(get_db),
               x_usuario: str = Header(default="fiscal")):
    """Nova vigencia para um NCM+ambito: fecha a anterior no dia anterior e abre a nova.
    A virada de fase do TTD e' um registro, nao uma alteracao no codigo."""
    atual = db.execute(
        select(RegraTTD).where(RegraTTD.ncm == dados.ncm, RegraTTD.ambito == dados.ambito,
                               RegraTTD.vigencia_fim.is_(None))
        .order_by(RegraTTD.vigencia_inicio.desc())).scalars().first()
    if atual and dados.vigencia_inicio <= atual.vigencia_inicio:
        raise HTTPException(400, detail=dict(
            mensagem=(f"Já existe vigência de {dados.ncm}/{dados.ambito} a partir de "
                      f"{atual.vigencia_inicio:%d/%m/%Y}. A nova precisa começar depois disso.")))
    if atual:
        atual.vigencia_fim = dados.vigencia_inicio - dt.timedelta(days=1)
    nova = RegraTTD(**dados.model_dump(), alterado_por=x_usuario)
    db.add(nova)
    db.flush()
    db.add(Auditoria(tabela="regra_ttd", registro_id=nova.id, operacao="INSERT", usuario=x_usuario,
                     antes=(dict(vigencia_fim=str(atual.vigencia_fim)) if atual else None),
                     depois=dados.model_dump(mode="json")))
    db.commit()
    return dict(id=nova.id, ncm=nova.ncm, ambito=nova.ambito, bloco=nova.bloco,
               vigencia_inicio=nova.vigencia_inicio)
