"""Conciliação e Fechamento de ICMS (normal, empresa toda) - fase 1.

A partir de 01/09/2026 a ingestão também pode rodar por upload direto na tela (POST
/periodos/{competencia}/importar) - a API passou a rodar em container Docker na Vercel
especificamente para ter o `pdftotext` disponível (ver Dockerfile.vercel e vercel.json na raiz
do repositório). scripts/importar_conciliacao_icms.py continua funcionando do mesmo jeito para
quem preferir rodar localmente.
"""
import datetime as dt
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ConcDivergencia, ConcFechamento, ConcPeriodo
from ..services.conciliacao.ingestao import importar_periodo
from ..services.conciliacao.notas_credores import gerar_planilha_conciliada

router = APIRouter(prefix="/conciliacao", tags=["conciliacao"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _periodo_ou_404(db: Session, competencia: str) -> ConcPeriodo:
    p = db.execute(select(ConcPeriodo).where(ConcPeriodo.competencia == competencia)
                   ).scalars().first()
    if not p:
        raise HTTPException(404, detail=dict(
            mensagem=f"Nenhuma competência de conciliação de ICMS importada para {competencia}."))
    return p


@router.post("/periodos/{competencia}/importar", status_code=201)
async def importar(
    competencia: str,
    contab_livro: UploadFile = File(..., description="Livro de Entradas da contabilidade"),
    contab_dime: UploadFile = File(..., description="Prévia Dime da contabilidade"),
    ecomet_livro: UploadFile = File(..., description="Livro de Entradas da Empresa (Ecomet/SAGI)"),
    ecomet_raicms: UploadFile = File(..., description="Livro Fiscal da Empresa (RAICMS)"),
    contab_saida: UploadFile | None = File(None, description="Livro de Saídas da contabilidade (opcional)"),
    ecomet_saida: UploadFile | None = File(None, description="Livro de Saídas da Empresa (opcional)"),
    ciap: float = Form(0.0),
    inscricao_estadual: str = Form("260070009"),
    db: Session = Depends(get_db),
):
    """Recebe os documentos direto da tela (multipart) e roda a mesma ingestão do script local
    (services/conciliacao/ingestao.py). Os dois documentos de saída são opcionais, mas têm que
    vir os dois juntos, ou nenhum - mesma regra do CLI."""
    if bool(contab_saida) != bool(ecomet_saida):
        raise HTTPException(400, detail=dict(
            mensagem="Envie o Livro de Saídas dos dois lados (contabilidade e Empresa), ou de nenhum."))

    with tempfile.TemporaryDirectory() as tmp:
        async def salvar(upload: UploadFile | None, nome: str) -> str | None:
            if upload is None:
                return None
            destino = Path(tmp) / nome
            destino.write_bytes(await upload.read())
            return str(destino)

        caminhos = dict(
            contab_livro=await salvar(contab_livro, "contab_livro.pdf"),
            contab_dime=await salvar(contab_dime, "contab_dime.pdf"),
            ecomet_livro=await salvar(ecomet_livro, "ecomet_livro.pdf"),
            ecomet_raicms=await salvar(ecomet_raicms, "ecomet_raicms.pdf"),
            contab_saida=await salvar(contab_saida, "contab_saida.pdf"),
            ecomet_saida=await salvar(ecomet_saida, "ecomet_saida.pdf"))

        try:
            periodo = importar_periodo(db, competencia, ciap=ciap,
                                       inscricao_estadual=inscricao_estadual, **caminhos)
        except subprocess.CalledProcessError:
            raise HTTPException(400, detail=dict(
                mensagem="Não consegui ler um dos PDFs — confira se o arquivo não está corrompido, "
                         "protegido por senha, ou se não é mesmo um PDF."))

    altas = len([d for d in periodo.divergencias if d.severidade == "alto"])
    return dict(competencia=periodo.competencia, periodo_id=periodo.id,
               lancamentos=len(periodo.lancamentos), saldos=len(periodo.saldos),
               divergencias=len(periodo.divergencias), divergencias_altas=altas,
               tem_saida=bool(contab_saida))


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
    divergencias = [dict(id=d.id, tipo=d.tipo, bloco=d.bloco, severidade=d.severidade, status=d.status,
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


@router.post("/periodos/{competencia}/notas-credores")
async def notas_credores(
    competencia: str,
    planilha: UploadFile = File(..., description="Planilha de Notas de Credores (Contas a Pagar)"),
    db: Session = Depends(get_db),
):
    """Recebe a planilha de Notas de Credores, preenche o CFOP de entrada de cada nota a partir
    do Livro de Entradas da Contabilidade desta competência (casando por número da NF-e + valor)
    e devolve a mesma planilha com o CFOP preenchido, mais uma aba de conciliação por CFOP entre
    a planilha e o Livro. Pedido pelo Victor em 04/09/2026."""
    p = _periodo_ou_404(db, competencia)
    conteudo = await planilha.read()
    try:
        saida = gerar_planilha_conciliada(p, conteudo)
    except ValueError as e:
        raise HTTPException(400, detail=dict(mensagem=str(e)))
    nome = f"Notas Credores Conciliado {competencia.replace('-', '')}.xlsx"
    return StreamingResponse(saida, media_type=XLSX,
                             headers={"Content-Disposition": f'attachment; filename="{nome}"'})


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
        d.resolvido_em = dt.datetime.utcnow()
    else:
        d.resolvido_em = None
    db.commit()
    return dict(id=d.id, status=d.status, justificativa=d.justificativa)


@router.post("/periodos/{competencia}/fechar")
def fechar(competencia: str, db: Session = Depends(get_db), x_usuario: str = Header(default="fiscal")):
    """Aprova a conciliação da competência e salva o resultado (ConcFechamento) - passo final
    pedido pelo usuário: 'Após aprovação da conciliação salva o resultado referente ao mês
    conciliado'. Exige que não haja divergência aberta de severidade alta (as de severidade
    'revisar' - ex.: nota cancelada, uso/consumo - podem ficar abertas e não bloqueiam)."""
    p = _periodo_ou_404(db, competencia)
    if p.status == "fechado":
        raise HTTPException(400, detail=dict(mensagem="Esta competência já está fechada."))
    abertas_altas = [d for d in p.divergencias if d.status == "aberta" and d.severidade == "alto"]
    if abertas_altas:
        raise HTTPException(400, detail=dict(
            mensagem=(f"Há {len(abertas_altas)} divergência(s) de severidade alta ainda aberta(s) "
                     "— corrija os documentos e reimporte, ou justifique cada uma antes de fechar."),
            divergencias=[d.id for d in abertas_altas]))

    total_debitos = sum(l.valor for l in p.linhas_apuracao if l.grupo in ("debito", "outros_debitos"))
    total_creditos = sum(l.valor for l in p.linhas_apuracao if l.grupo in ("credito", "outros_creditos"))
    saldo = round(total_creditos - total_debitos, 2)
    snapshot = dict(
        saldos=[dict(fonte=s.fonte, tipo=s.tipo, cfop=s.cfop, valor_contabil=float(s.valor_contabil))
               for s in p.saldos],
        divergencias=[dict(tipo=d.tipo, bloco=d.bloco, severidade=d.severidade, status=d.status,
                           cfop=d.cfop, numero_nota=d.numero_nota, descricao=d.descricao,
                           justificativa=d.justificativa) for d in p.divergencias],
        apuracao=[dict(grupo=l.grupo, rotulo=l.rotulo, valor=float(l.valor)) for l in p.linhas_apuracao])

    db.add(ConcFechamento(
        periodo_id=p.id, total_debitos=round(total_debitos, 2), total_creditos=round(total_creditos, 2),
        imposto_a_recolher=max(round(total_debitos - total_creditos, 2), 0.0),
        saldo_credor_transportado=max(saldo, 0.0), snapshot=snapshot, fechado_por=x_usuario))
    p.status = "fechado"
    p.fechado_em = dt.datetime.utcnow()
    p.fechado_por = x_usuario
    db.commit()
    return dict(competencia=p.competencia, status=p.status, total_debitos=round(total_debitos, 2),
               total_creditos=round(total_creditos, 2), saldo_credor_transportado=max(saldo, 0.0))
