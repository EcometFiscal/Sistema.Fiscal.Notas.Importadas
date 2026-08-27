import datetime as dt

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Nota
from ..schemas import LancamentoOut, NotaIn, NotaOut
from ..services.fechamento import CompetenciaFechada
from ..services.notas import ErroLancamento, cancelar_nota, criar_nota, resumo_pos_lancamento

router = APIRouter(prefix="/notas", tags=["notas"])


@router.post("", response_model=LancamentoOut, status_code=201)
def lancar(dados: NotaIn, db: Session = Depends(get_db),
           x_usuario: str = Header(default="fiscal")):
    try:
        nota, avisos = criar_nota(db, dados, x_usuario)
    except CompetenciaFechada as e:
        raise HTTPException(409, detail=dict(mensagem=e.mensagem, avisos=[],
                                             competencia=e.competencia))
    except ErroLancamento as e:
        raise HTTPException(e.status, detail=dict(mensagem=e.mensagem, avisos=e.avisos))
    resumo = resumo_pos_lancamento(db, nota)
    return LancamentoOut(nota=NotaOut.model_validate(nota), avisos=avisos,
                         estoque=resumo["estoque"], apuracao=resumo["apuracao"])


@router.get("", response_model=list[NotaOut])
def listar(tipo: str | None = None, de: dt.date | None = None, ate: dt.date | None = None,
           q: str | None = None, limite: int = Query(100, le=1000),
           db: Session = Depends(get_db)):
    st = select(Nota).order_by(Nota.data_mov.desc(), Nota.id.desc()).limit(limite)
    if tipo:
        st = st.where(Nota.tipo == tipo)
    if de:
        st = st.where(Nota.data_mov >= de)
    if ate:
        st = st.where(Nota.data_mov <= ate)
    if q and q.strip().isdigit():
        st = st.where(Nota.numero == int(q.strip()))
    return db.execute(st).scalars().unique().all()


@router.get("/{nota_id}", response_model=NotaOut)
def obter(nota_id: int, db: Session = Depends(get_db)):
    nota = db.get(Nota, nota_id)
    if not nota:
        raise HTTPException(404, "Nota nao encontrada")
    return nota


@router.post("/{nota_id}/cancelar", response_model=NotaOut)
def cancelar(nota_id: int, motivo: str, db: Session = Depends(get_db),
             x_usuario: str = Header(default="fiscal")):
    try:
        return cancelar_nota(db, nota_id, motivo, x_usuario)
    except CompetenciaFechada as e:
        raise HTTPException(409, detail=dict(mensagem=e.mensagem))
    except ErroLancamento as e:
        raise HTTPException(e.status, detail=dict(mensagem=e.mensagem))
