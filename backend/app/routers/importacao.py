import datetime as dt

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ArquivoImportado, Configuracao, LoteImportacao
from ..services import importacao as imp

router = APIRouter(tags=["importacao"])


class ConfigIn(BaseModel):
    cnpj_empresa: str


@router.get("/configuracao")
def configuracao(db: Session = Depends(get_db)):
    return {c.chave: dict(valor=c.valor, descricao=c.descricao, alterado_em=c.alterado_em)
            for c in db.execute(select(Configuracao)).scalars()}


@router.post("/configuracao")
def gravar_configuracao(dados: ConfigIn, db: Session = Depends(get_db),
                        x_usuario: str = Header(default="fiscal")):
    cnpj = imp.definir_cnpj_empresa(db, dados.cnpj_empresa, x_usuario)
    if len(cnpj) != 14:
        raise HTTPException(400, detail=dict(mensagem="CNPJ precisa ter 14 dígitos."))
    db.commit()
    return dict(cnpj_empresa=cnpj)


@router.post("/importar/zip", status_code=201)
async def importar_zip(arquivo: UploadFile = File(...), db: Session = Depends(get_db),
                       x_usuario: str = Header(default="fiscal")):
    conteudo = await arquivo.read()
    lote = imp.importar_zip(db, conteudo, arquivo.filename or "pacote.zip", x_usuario)
    return _lote_json(lote)


def _lote_json(lote: LoteImportacao) -> dict:
    return dict(id=lote.id, origem=lote.origem, nome=lote.nome, total=lote.total,
                importadas=lote.importadas, duplicadas=lote.duplicadas, pendentes=lote.pendentes,
                erros=lote.erros, criado_em=lote.criado_em, criado_por=lote.criado_por,
                arquivos=[dict(arquivo=a.arquivo, situacao=a.situacao, motivo=a.motivo,
                               chave_acesso=a.chave_acesso, numero=a.numero, tipo=a.tipo,
                               nota_id=a.nota_id)
                          for a in sorted(lote.arquivos, key=lambda x: (x.situacao, x.arquivo))])


@router.get("/importar/lotes")
def lotes(limite: int = 30, db: Session = Depends(get_db)):
    linhas = db.execute(select(LoteImportacao).order_by(LoteImportacao.id.desc())
                        .limit(limite)).scalars().all()
    return [dict(id=l.id, origem=l.origem, nome=l.nome, total=l.total, importadas=l.importadas,
                 duplicadas=l.duplicadas, pendentes=l.pendentes, erros=l.erros,
                 criado_em=l.criado_em, criado_por=l.criado_por) for l in linhas]


@router.get("/importar/lotes/{lote_id}")
def lote(lote_id: int, db: Session = Depends(get_db)):
    l = db.get(LoteImportacao, lote_id)
    if not l:
        raise HTTPException(404, "Lote não encontrado")
    return _lote_json(l)
