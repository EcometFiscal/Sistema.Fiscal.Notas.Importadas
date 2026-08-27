import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Parceiro, Produto
from ..schemas import ParceiroIn, ParceiroOut, ProdutoIn, ProdutoOut
from ..services.apuracao import bloco_sugerido

router = APIRouter(tags=["cadastros"])


@router.get("/parceiros", response_model=list[ParceiroOut])
def listar_parceiros(q: str | None = None, limite: int = Query(50, le=500),
                     db: Session = Depends(get_db)):
    st = select(Parceiro).order_by(Parceiro.nome).limit(limite)
    if q:
        st = select(Parceiro).where(Parceiro.nome.ilike(f"%{q.strip()}%")).order_by(Parceiro.nome).limit(limite)
    return db.execute(st).scalars().all()


@router.post("/parceiros", response_model=ParceiroOut, status_code=201)
def criar_parceiro(dados: ParceiroIn, db: Session = Depends(get_db)):
    nome = " ".join(dados.nome.replace("\xa0", " ").split()).upper()
    if db.execute(select(Parceiro).where(Parceiro.nome == nome)).scalars().first():
        raise HTTPException(409, "Ja' existe parceiro com esse nome")
    p = Parceiro(**{**dados.model_dump(), "nome": nome})
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/produtos", response_model=list[ProdutoOut])
def listar_produtos(db: Session = Depends(get_db)):
    return db.execute(select(Produto).order_by(Produto.descricao)).scalars().all()


@router.post("/produtos", response_model=ProdutoOut, status_code=201)
def criar_produto(dados: ProdutoIn, db: Session = Depends(get_db)):
    desc = " ".join(dados.descricao.replace("\xa0", " ").split()).upper()
    if db.execute(select(Produto).where(Produto.descricao == desc)).scalars().first():
        raise HTTPException(409, "Ja' existe produto com essa descricao")
    p = Produto(**{**dados.model_dump(), "descricao": desc})
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/blocos")
def blocos(uf: str | None = None, exterior: bool = False, db: Session = Depends(get_db)):
    from ..services.apuracao import regra
    hoje = dt.date.today()
    saida = []
    for b in ("1", "2", "3"):
        r = regra(db, b, hoje)
        if r:
            saida.append(dict(bloco=b, descricao=r.descricao, aliquota=float(r.aliquota),
                              aliq_presumido=float(r.aliq_presumido),
                              carga_efetiva=float(r.carga_efetiva)))
    return dict(blocos=saida, sugerido=bloco_sugerido(uf, exterior))
