from __future__ import annotations

import datetime as dt
from pydantic import BaseModel, ConfigDict, Field


class ParceiroOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nome: str
    cnpj: str | None = None
    uf: str | None = None
    exterior: bool = False
    papel: str | None = None


class ParceiroIn(BaseModel):
    nome: str = Field(min_length=2, max_length=160)
    cnpj: str | None = None
    uf: str | None = None
    pais: str | None = None
    exterior: bool = False
    papel: str | None = None


class ProdutoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    descricao: str
    unidade: str
    categoria: str | None = None
    ncm: str | None = None


class ProdutoIn(BaseModel):
    descricao: str = Field(min_length=2, max_length=120)
    unidade: str = "KG"
    categoria: str | None = None
    ncm: str | None = None


class ItemIn(BaseModel):
    produto_id: int | None = None
    produto: str | None = None          # aceita a descricao e cria/localiza
    quantidade: float = Field(gt=0)
    valor: float | None = None
    base_calculo: float | None = None
    bloco_ttd: str | None = None        # obrigatorio nas saidas beneficiadas
    cst: str | None = None
    ncm: str | None = None


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    produto_id: int
    quantidade: float
    valor: float | None = None
    base_calculo: float | None = None
    bloco_ttd: str | None = None
    custo_unit: float | None = None
    custo_total: float | None = None
    ncm: str | None = None
    origem_merc: str | None = None
    cst: str | None = None
    cst_completo: str | None = None     # origem + CST, ex. "100" - como o fiscal enxerga


class NotaIn(BaseModel):
    tipo: str = Field(pattern="^[ES]$")
    numero: int = Field(gt=0)
    serie: str | None = "1"
    modelo: str | None = "55"
    chave_acesso: str | None = Field(default=None, max_length=44)
    cfop: str | None = None
    natureza: str = "VENDA"             # VENDA | DEVOLUCAO | IMPORTACAO
    data_emissao: dt.date | None = None
    data_mov: dt.date
    parceiro_id: int | None = None
    parceiro: str | None = None
    observacao: str | None = None
    itens: list[ItemIn] = Field(min_length=1)
    # confirmacoes exigidas pelas regras
    justificativa: str | None = None
    confirmar_duplicata: bool = False


class Aviso(BaseModel):
    codigo: str
    mensagem: str
    exige: str | None = None            # justificativa | confirmar_duplicata
    dados: dict | None = None


class NotaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tipo: str
    numero: int
    serie: str | None = None
    chave_acesso: str | None = None
    natureza: str
    data_mov: dt.date
    valor_total: float | None = None
    status: str
    observacao: str | None = None
    criado_por: str
    parceiro: ParceiroOut | None = None
    itens: list[ItemOut] = []


class LancamentoOut(BaseModel):
    nota: NotaOut
    avisos: list[Aviso] = []
    estoque: list[dict] = []
    apuracao: dict | None = None
