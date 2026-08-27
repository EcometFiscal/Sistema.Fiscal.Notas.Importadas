from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import APP_NAME, CORS_ORIGINS, CRIAR_TABELAS, SENHA_ACESSO, VERSION
from .db import Base, SessionLocal, engine
from .routers import apuracao, cadastros, estoque, exportacao, importacao, notas
from .services.apuracao import semear_regras


@asynccontextmanager
async def lifespan(_: FastAPI):
    if CRIAR_TABELAS:
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            semear_regras(db)
            db.commit()
    yield


app = FastAPI(title=APP_NAME, version=VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"],
                   allow_headers=["*"])


@app.middleware("http")
async def trava_opcional(request: Request, call_next):
    """Desligada por padrao. Definindo SENHA_ACESSO no ambiente, a aplicacao passa a exigir
    o cabecalho X-Senha - e o link deixa de dar acesso sozinho."""
    protegida = (SENHA_ACESSO and request.url.path.startswith("/api")
                 and request.url.path != "/api/saude")
    if protegida and request.headers.get("X-Senha") != SENHA_ACESSO:
        return JSONResponse(status_code=401,
                            content={"detail": {"mensagem": "Senha de acesso incorreta."}})
    return await call_next(request)


app.include_router(cadastros.router, prefix="/api")
app.include_router(notas.router, prefix="/api")
app.include_router(estoque.router, prefix="/api")
app.include_router(apuracao.router, prefix="/api")
app.include_router(exportacao.router, prefix="/api")
app.include_router(importacao.router, prefix="/api")


@app.get("/api/saude")
def saude():
    return dict(app=APP_NAME, versao=VERSION,
                fase="5 - importacao por XML, estoque por saldo e apuracao TTD",
                protegido_por_senha=bool(SENHA_ACESSO))
