import datetime as dt

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.exportacao import exportar_apuracao, exportar_estoque

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
