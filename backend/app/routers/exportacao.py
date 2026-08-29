import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import LoteImportacao
from ..services.exportacao import (exportar_apuracao, exportar_auditoria_lote, exportar_estoque,
                                   exportar_pendencias)

router = APIRouter(prefix="/exportar", tags=["exportacao"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _arquivo(conteudo, nome: str):
    return StreamingResponse(conteudo, media_type=XLSX,
                             headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@router.get("/apuracao/{competencia}")
def apuracao(competencia: str, db: Session = Depends(get_db)):
    return _arquivo(exportar_apuracao(db, competencia),
                    f"Apuracao ICMS Importado {competencia.replace('-', '')}.xlsx")


@router.get("/estoque")
def estoque(de: dt.date | None = None, ate: dt.date | None = None, db: Session = Depends(get_db)):
    ref = (ate or dt.date.today()).strftime("%Y%m%d")
    return _arquivo(exportar_estoque(db, de, ate), f"Estoque Fiscal Importado {ref}.xlsx")


@router.get("/pendencias")
def pendencias(db: Session = Depends(get_db)):
    ref = dt.date.today().strftime("%Y%m%d")
    return _arquivo(exportar_pendencias(db), f"Relatorio de Erros e Pendencias {ref}.xlsx")


@router.get("/auditoria/{lote_id}")
def auditoria(lote_id: int, db: Session = Depends(get_db)):
    lote = db.get(LoteImportacao, lote_id)
    if not lote:
        raise HTTPException(404, "Lote não encontrado")
    ref = dt.date.today().strftime("%Y%m%d")
    return _arquivo(exportar_auditoria_lote(db, lote), f"Auditoria Importacao Lote {lote_id} {ref}.xlsx")
