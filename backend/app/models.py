"""Modelo de dados do Lastro.

Fase 2. Decisoes que mudam o significado das tabelas:
  - decisao 5 (27/08/2026): a saida NAO e' vinculada a uma entrada especifica. ConsumoEstoque
    e' o razao de CUSTEIO (PEPS), nao prova de vinculacao fiscal. origem_merc segue nulo ate'
    o XML.
  - decisao 1 (27/08/2026, REVERTIDA em 30/08/2026): saida sem saldo NAO gera mais lancamento
    de acerto - o saldo do produto fica negativo ate' uma entrada real cobrir a diferenca.
"""
import datetime as dt

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
                        Integer, Numeric, String, Text, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

NUM = Numeric(15, 3)
DIN = Numeric(15, 2)


class Parceiro(Base):
    __tablename__ = "parceiro"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), unique=True)
    cnpj: Mapped[str | None] = mapped_column(String(14))
    id_estrangeiro: Mapped[str | None] = mapped_column(String(60))
    uf: Mapped[str | None] = mapped_column(String(2))
    pais: Mapped[str | None] = mapped_column(String(60))
    exterior: Mapped[bool] = mapped_column(Boolean, default=False)
    papel: Mapped[str | None] = mapped_column(String(12))
    variantes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ativo")
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Produto(Base):
    __tablename__ = "produto"
    id: Mapped[int] = mapped_column(primary_key=True)
    descricao: Mapped[str] = mapped_column(String(120), unique=True)
    ncm: Mapped[str | None] = mapped_column(String(8))          # decisao 2: dispensado
    unidade: Mapped[str] = mapped_column(String(6), default="KG")
    categoria: Mapped[str | None] = mapped_column(String(12))
    metal: Mapped[str | None] = mapped_column(String(20))
    variantes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ativo")


class Nota(Base):
    __tablename__ = "nota"
    id: Mapped[int] = mapped_column(primary_key=True)
    chave_acesso: Mapped[str | None] = mapped_column(String(44), unique=True)
    numero: Mapped[int] = mapped_column(Integer)
    serie: Mapped[str | None] = mapped_column(String(3))
    modelo: Mapped[str | None] = mapped_column(String(2), default="55")
    tipo: Mapped[str] = mapped_column(String(1))                # E | S
    cfop: Mapped[str | None] = mapped_column(String(4))
    natureza: Mapped[str] = mapped_column(String(12), default="VENDA")
    data_emissao: Mapped[dt.date | None] = mapped_column(Date)
    data_mov: Mapped[dt.date] = mapped_column(Date)
    parceiro_id: Mapped[int | None] = mapped_column(ForeignKey("parceiro.id"))
    valor_total: Mapped[float | None] = mapped_column(DIN)
    observacao: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="lancada")
    origem_registro: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    criado_por: Mapped[str] = mapped_column(String(60), default="sistema")

    parceiro: Mapped["Parceiro"] = relationship(lazy="joined")
    itens: Mapped[list["NotaItem"]] = relationship(back_populates="nota", cascade="all, delete-orphan",
                                                  lazy="selectin")
    __table_args__ = (
        CheckConstraint("tipo in ('E','S')", name="ck_nota_tipo"),
        Index("ix_nota_num", "tipo", "numero"),
        Index("ix_nota_data", "data_mov"),
    )


class NotaItem(Base):
    __tablename__ = "nota_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    nota_id: Mapped[int] = mapped_column(ForeignKey("nota.id", ondelete="CASCADE"))
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id"))
    ncm: Mapped[str | None] = mapped_column(String(8))
    origem_merc: Mapped[str | None] = mapped_column(String(1))  # decisao 5: nao exigido
    quantidade: Mapped[float] = mapped_column(NUM)
    valor: Mapped[float | None] = mapped_column(DIN)
    base_calculo: Mapped[float | None] = mapped_column(DIN)
    aliquota: Mapped[float | None] = mapped_column(Numeric(6, 4))
    cst: Mapped[str | None] = mapped_column(String(3))
    bloco_ttd: Mapped[str | None] = mapped_column(String(2))    # 1 | 2 | 3 (saidas)
    custo_unit: Mapped[float | None] = mapped_column(Numeric(15, 6))   # entradas
    custo_total: Mapped[float | None] = mapped_column(DIN)             # saidas (PEPS)

    nota: Mapped["Nota"] = relationship(back_populates="itens")
    produto: Mapped["Produto"] = relationship(lazy="joined")
    __table_args__ = (Index("ix_item_prod", "produto_id"),)

    @property
    def cst_completo(self) -> str | None:
        """Codigo de 3 digitos que o pessoal do fiscal reconhece: origem (1 digito) + CST do
        ICMS (2 digitos). Ex.: origem=1 + cst=00 -> "100"."""
        if self.origem_merc and self.cst:
            return f"{self.origem_merc}{self.cst}"
        return None


class ConsumoEstoque(Base):
    """Razao de custeio PEPS (decisao 5: custeio, nao vinculacao fiscal)."""
    __tablename__ = "consumo_estoque"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_saida_id: Mapped[int] = mapped_column(ForeignKey("nota_item.id", ondelete="CASCADE"))
    item_entrada_id: Mapped[int] = mapped_column(ForeignKey("nota_item.id", ondelete="CASCADE"))
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id"))
    quantidade: Mapped[float] = mapped_column(NUM)
    custo_unitario: Mapped[float | None] = mapped_column(Numeric(15, 6))
    metodo: Mapped[str] = mapped_column(String(10), default="PEPS")
    __table_args__ = (Index("ix_consumo_saida", "item_saida_id"),
                      Index("ix_consumo_produto", "produto_id"))


class Excecao(Base):
    __tablename__ = "excecao"
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(40))
    nota_id: Mapped[int | None] = mapped_column(ForeignKey("nota.id", ondelete="CASCADE"))
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produto.id"))
    descricao: Mapped[str] = mapped_column(Text)
    justificativa: Mapped[str | None] = mapped_column(Text)
    quantidade: Mapped[float | None] = mapped_column(NUM)
    valor: Mapped[float | None] = mapped_column(DIN)
    resolvida: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    criado_por: Mapped[str] = mapped_column(String(60), default="sistema")


class RegraTTD(Base):
    """Aliquotas com vigencia, por produto (NCM) e ambito da operacao. A virada de fase do
    TTD nao pode virar chamado de emergencia. bloco segue existindo so' para o Excel da
    contabilidade continuar saindo no formato de sempre - a chave real e' (ncm, ambito)."""
    __tablename__ = "regra_ttd"
    id: Mapped[int] = mapped_column(primary_key=True)
    ncm: Mapped[str] = mapped_column(String(8))
    ambito: Mapped[str] = mapped_column(String(15))   # interna | interestadual
    bloco: Mapped[str] = mapped_column(String(2))
    descricao: Mapped[str] = mapped_column(String(80))
    aliquota: Mapped[float] = mapped_column(Numeric(6, 4))
    aliq_presumido: Mapped[float] = mapped_column(Numeric(6, 4))
    carga_efetiva: Mapped[float] = mapped_column(Numeric(6, 4))
    vigencia_inicio: Mapped[dt.date] = mapped_column(Date)
    vigencia_fim: Mapped[dt.date | None] = mapped_column(Date)
    alterado_por: Mapped[str | None] = mapped_column(String(60))
    alterado_em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class ApuracaoMes(Base):
    __tablename__ = "apuracao_mes"
    id: Mapped[int] = mapped_column(primary_key=True)
    competencia: Mapped[str] = mapped_column(String(7), unique=True)
    base_beneficiada: Mapped[float | None] = mapped_column(DIN)
    debito: Mapped[float | None] = mapped_column(DIN)
    credito_presumido: Mapped[float | None] = mapped_column(DIN)
    estorno: Mapped[float | None] = mapped_column(DIN)
    devolucao_icms: Mapped[float | None] = mapped_column(DIN)
    icms_recolher: Mapped[float | None] = mapped_column(DIN)
    fundo_social: Mapped[float | None] = mapped_column(DIN)
    fundo_educacao: Mapped[float | None] = mapped_column(DIN)
    carga_efetiva: Mapped[float | None] = mapped_column(Numeric(8, 5))
    status: Mapped[str] = mapped_column(String(10), default="aberta")
    fechada_em: Mapped[dt.datetime | None] = mapped_column(DateTime)
    fechada_por: Mapped[str | None] = mapped_column(String(60))


class Auditoria(Base):
    __tablename__ = "auditoria"
    id: Mapped[int] = mapped_column(primary_key=True)
    tabela: Mapped[str] = mapped_column(String(40))
    registro_id: Mapped[int] = mapped_column(Integer)
    operacao: Mapped[str] = mapped_column(String(10))
    antes: Mapped[dict | None] = mapped_column(JSON)
    depois: Mapped[dict | None] = mapped_column(JSON)
    usuario: Mapped[str] = mapped_column(String(60))
    em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Configuracao(Base):
    """Poucas chaves, mas que nao podem viver em variavel de ambiente esquecida:
    o CNPJ do estabelecimento e' o que decide se uma NF-e e' entrada ou saida."""
    __tablename__ = "configuracao"
    chave: Mapped[str] = mapped_column(String(40), primary_key=True)
    valor: Mapped[str | None] = mapped_column(Text)
    descricao: Mapped[str | None] = mapped_column(Text)
    alterado_em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    alterado_por: Mapped[str | None] = mapped_column(String(60))


class LoteImportacao(Base):
    __tablename__ = "lote_importacao"
    id: Mapped[int] = mapped_column(primary_key=True)
    origem: Mapped[str] = mapped_column(String(20))        # zip | pasta | sefaz
    nome: Mapped[str | None] = mapped_column(Text)
    total: Mapped[int] = mapped_column(Integer, default=0)
    importadas: Mapped[int] = mapped_column(Integer, default=0)
    complementadas: Mapped[int] = mapped_column(Integer, default=0)
    duplicadas: Mapped[int] = mapped_column(Integer, default=0)
    pendentes: Mapped[int] = mapped_column(Integer, default=0)
    erros: Mapped[int] = mapped_column(Integer, default=0)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    criado_por: Mapped[str] = mapped_column(String(60), default="fiscal")

    arquivos: Mapped[list["ArquivoImportado"]] = relationship(
        back_populates="lote", cascade="all, delete-orphan", lazy="selectin")


class ArquivoImportado(Base):
    __tablename__ = "arquivo_importado"
    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lote_importacao.id", ondelete="CASCADE"))
    arquivo: Mapped[str] = mapped_column(Text)
    chave_acesso: Mapped[str | None] = mapped_column(String(44))
    numero: Mapped[int | None] = mapped_column(Integer)
    tipo: Mapped[str | None] = mapped_column(String(1))
    situacao: Mapped[str] = mapped_column(String(20))      # importada|complementada|duplicada|pendente|erro|ignorada
    motivo: Mapped[str | None] = mapped_column(Text)
    nota_id: Mapped[int | None] = mapped_column(ForeignKey("nota.id", ondelete="SET NULL"))

    lote: Mapped["LoteImportacao"] = relationship(back_populates="arquivos")
