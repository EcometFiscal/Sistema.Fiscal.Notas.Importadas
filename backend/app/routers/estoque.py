import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Excecao, Produto
from ..services import estoque as est
from ..services.apuracao import previa

router = APIRouter(tags=["estoque"])


@router.get("/estoque/posicao")
def posicao(ate: dt.date | None = None, cobertura: bool = True, db: Session = Depends(get_db)):
    linhas = est.posicao(db, ate)
    if cobertura:
        for l in linhas:
            l["cobertura_dias"] = est.cobertura_dias(db, l["produto_id"], l["saldo_kg"])
    return dict(data=ate or dt.date.today(),
                total_kg=sum(l["saldo_kg"] for l in linhas),
                total_rs=sum(l["saldo_rs"] for l in linhas),
                produtos=linhas)


@router.get("/estoque/saldo/{produto_id}")
def saldo(produto_id: int, data: dt.date | None = None, db: Session = Depends(get_db)):
    p = db.get(Produto, produto_id)
    return dict(produto_id=produto_id, produto=p.descricao if p else None,
                data=data or dt.date.today(), saldo=float(est.saldo(db, produto_id, data)))


@router.get("/estoque/razao/{produto_id}")
def razao(produto_id: int, de: dt.date | None = None, ate: dt.date | None = None,
          db: Session = Depends(get_db)):
    return est.razao(db, produto_id, de, ate)


@router.post("/estoque/recalcular")
def recalcular(produto_id: int | None = None, db: Session = Depends(get_db)):
    ids = [produto_id] if produto_id else db.execute(select(Produto.id)).scalars().all()
    r = est.recalcular_varios(db, ids)
    db.commit()
    return dict(recalculados=r)


@router.get("/excecoes")
def excecoes(resolvida: bool | None = None, limite: int = Query(200, le=1000),
             db: Session = Depends(get_db)):
    st = select(Excecao).order_by(Excecao.criado_em.desc(), Excecao.id.desc()).limit(limite)
    if resolvida is not None:
        st = st.where(Excecao.resolvida == resolvida)
    saida = []
    for e in db.execute(st).scalars():
        saida.append(dict(id=e.id, tipo=e.tipo, nota_id=e.nota_id, produto_id=e.produto_id,
                          descricao=e.descricao, justificativa=e.justificativa,
                          quantidade=float(e.quantidade or 0), valor=float(e.valor or 0),
                          resolvida=e.resolvida, criado_por=e.criado_por))
    return saida


@router.get("/resumo")
def resumo(db: Session = Depends(get_db)):
    hoje = dt.date.today()
    linhas = est.posicao(db)
    comp = f"{hoje.year}-{hoje.month:02d}"
    ap = previa(db, comp)
    pend = db.execute(select(Excecao).where(Excecao.resolvida.is_(False))).scalars().all()
    return dict(
        atualizado=hoje,
        estoque_kg=sum(l["saldo_kg"] for l in linhas),
        estoque_rs=sum(l["saldo_rs"] for l in linhas),
        produtos=linhas,
        apuracao=dict(competencia=comp, base=ap["base_beneficiada"],
                      icms_recolher=ap["icms_recolher"], fundo_social=ap["fundo_social"],
                      fundo_educacao=ap["fundo_educacao"], carga_efetiva=ap["carga_efetiva"]),
        excecoes_abertas=len(pend))
