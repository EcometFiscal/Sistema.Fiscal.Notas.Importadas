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


# ====================================================================================
# Conciliacao e Fechamento de ICMS (normal, empresa toda) - modulo separado do TTD 409
# de importados acima. Recebido como pacote pronto em 31/08/2026 (ver
# claude/estado-atual.md) e integrado ao schema existente em vez de ganhar um banco
# proprio. Prefixo "Conc"/"conc_" so' para nao colidir por acidente com o dominio de
# importados; nao ha' nenhuma chave estrangeira entre os dois modulos.
#
# O pacote original trazia tipos ENUM nativos do Postgres para os campos de status/
# origem/etc. Convertidos aqui para String + CheckConstraint, que e' o padrao usado em
# todo o resto deste arquivo (ex.: Nota.tipo) e que o Base.metadata.create_all() sabe
# criar sozinho, sem precisar de CREATE TYPE em migracao a parte. Da mesma forma, os
# ids viraram inteiro autoincremento (nao uuid) e os campos que apontavam para um
# usuario (fechado_por, responsavel, criada_por) viraram String, ja' que este sistema
# nao tem tabela de usuarios - segue o mesmo padrao de Nota.criado_por/RegraTTD.
# alterado_por.
class ConcPeriodo(Base):
    __tablename__ = "conc_periodo"
    id: Mapped[int] = mapped_column(primary_key=True)
    competencia: Mapped[str] = mapped_column(String(7))            # AAAA-MM, como ApuracaoMes
    inscricao_estadual: Mapped[str] = mapped_column(String(14), default="260070009")
    status: Mapped[str] = mapped_column(String(15), default="aberto")   # aberto|em_analise|fechado
    saldo_credor_anterior: Mapped[float | None] = mapped_column(DIN)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    fechado_em: Mapped[dt.datetime | None] = mapped_column(DateTime)
    fechado_por: Mapped[str | None] = mapped_column(String(60))

    documentos: Mapped[list["ConcDocumentoFonte"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin")
    lancamentos: Mapped[list["ConcLancamentoEntrada"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin")
    saldos: Mapped[list["ConcSaldoCfop"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    divergencias: Mapped[list["ConcDivergencia"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin")
    linhas_apuracao: Mapped[list["ConcApuracaoLinha"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin")
    fechamento: Mapped["ConcFechamento | None"] = relationship(
        cascade="all, delete-orphan", uselist=False)

    __table_args__ = (
        CheckConstraint("status in ('aberto','em_analise','fechado')", name="ck_concperiodo_status"),
        Index("ix_concperiodo_comp", "competencia", "inscricao_estadual", unique=True),
    )


class ConcDocumentoFonte(Base):
    """Um dos 4 documentos-fonte de uma competencia (Previa Dime, Livro de Entradas da
    contabilidade, Livro de Entradas e RAICMS do Ecomet). total_documento fica nulo ate' a
    autoconferencia forte (comparar com o total impresso no rodape' do PDF) ser implementada -
    ver a nota em services/conciliacao/ingestao.py."""
    __tablename__ = "conc_documento_fonte"
    id: Mapped[int] = mapped_column(primary_key=True)
    periodo_id: Mapped[int] = mapped_column(ForeignKey("conc_periodo.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(30))          # dime | livro_entradas | raicms
    origem: Mapped[str] = mapped_column(String(15))        # contabilidade | ecomet
    nome_original: Mapped[str] = mapped_column(Text)
    total_documento: Mapped[float | None] = mapped_column(DIN)
    total_extraido: Mapped[float | None] = mapped_column(DIN)
    conferido: Mapped[bool] = mapped_column(Boolean, default=False)
    erro: Mapped[str | None] = mapped_column(Text)
    lido_em: Mapped[dt.datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("origem in ('contabilidade','ecomet')", name="ck_concdoc_origem"),
        Index("ix_concdoc_periodo_tipo", "periodo_id", "tipo", "origem", unique=True),
    )


class ConcLancamentoEntrada(Base):
    """Nota a nota do Livro de Entradas - de um lado (contabilidade) ou do outro (Ecomet).
    O pareamento entre os dois lados e' feito em memoria por numero+valor (services/
    conciliacao/reconcile.py), nunca por emitente: um lado usa codigo interno, o outro CNPJ."""
    __tablename__ = "conc_lancamento_entrada"
    id: Mapped[int] = mapped_column(primary_key=True)
    periodo_id: Mapped[int] = mapped_column(ForeignKey("conc_periodo.id", ondelete="CASCADE"))
    documento_id: Mapped[int] = mapped_column(ForeignKey("conc_documento_fonte.id", ondelete="CASCADE"))
    origem: Mapped[str] = mapped_column(String(15))
    data_entrada: Mapped[dt.date | None] = mapped_column(Date)
    data_documento: Mapped[dt.date | None] = mapped_column(Date)
    especie: Mapped[str | None] = mapped_column(String(10))
    serie: Mapped[str | None] = mapped_column(String(6))
    numero: Mapped[str] = mapped_column(String(20))
    emitente_codigo: Mapped[str | None] = mapped_column(String(30))   # codigo interno (contabilidade)
    emitente_cnpj: Mapped[str | None] = mapped_column(String(14))     # CNPJ (ecomet)
    uf: Mapped[str | None] = mapped_column(String(2))
    valor_contabil: Mapped[float] = mapped_column(DIN, default=0)
    cfop: Mapped[str | None] = mapped_column(String(4))
    cod_fiscal: Mapped[str | None] = mapped_column(String(1))    # 1 c/credito|2 isenta|3 outras|4 difal
    base_calculo: Mapped[float] = mapped_column(DIN, default=0)
    aliquota: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    imposto: Mapped[float] = mapped_column(DIN, default=0)
    difal: Mapped[float] = mapped_column(DIN, default=0)

    __table_args__ = (
        CheckConstraint("origem in ('contabilidade','ecomet')", name="ck_conclanc_origem"),
        Index("ix_conclanc_periodo_num", "periodo_id", "origem", "numero"),
        Index("ix_conclanc_periodo_cfop", "periodo_id", "cfop"),
    )


class ConcSaldoCfop(Base):
    """Saldo por CFOP de uma das quatro fontes (Dime, RAICMS, Livro de Entradas do Ecomet
    somado por CFOP, ou - se um dia precisar - o CFOP somado do lado contabil)."""
    __tablename__ = "conc_saldo_cfop"
    id: Mapped[int] = mapped_column(primary_key=True)
    periodo_id: Mapped[int] = mapped_column(ForeignKey("conc_periodo.id", ondelete="CASCADE"))
    fonte: Mapped[str] = mapped_column(String(15))     # dime|raicms|livro_ecomet|cfop_contabil
    tipo: Mapped[str] = mapped_column(String(8))       # entrada|saida
    cfop: Mapped[str] = mapped_column(String(4))
    valor_contabil: Mapped[float] = mapped_column(DIN, default=0)
    base_calculo: Mapped[float] = mapped_column(DIN, default=0)
    imposto: Mapped[float] = mapped_column(DIN, default=0)
    isentas: Mapped[float] = mapped_column(DIN, default=0)
    outras: Mapped[float] = mapped_column(DIN, default=0)
    difal: Mapped[float] = mapped_column(DIN, default=0)

    __table_args__ = (
        CheckConstraint("tipo in ('entrada','saida')", name="ck_concsaldo_tipo"),
        Index("ix_concsaldo_unico", "periodo_id", "fonte", "tipo", "cfop", unique=True),
    )


class ConcDivergencia(Base):
    """Uma linha do painel de divergencias. tipo segue o vocabulario do pacote original:
    cfop_saldo | cfop_nota | coerencia_interna_ecomet | saldo_credor_anterior |
    nota_ausente_ecomet | pareamento_manual."""
    __tablename__ = "conc_divergencia"
    id: Mapped[int] = mapped_column(primary_key=True)
    periodo_id: Mapped[int] = mapped_column(ForeignKey("conc_periodo.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(40))
    severidade: Mapped[str] = mapped_column(String(10))     # alto | revisar
    status: Mapped[str] = mapped_column(String(25), default="aberta")
    cfop: Mapped[str | None] = mapped_column(String(4))
    numero_nota: Mapped[str | None] = mapped_column(String(20))
    descricao: Mapped[str] = mapped_column(Text)
    valor_contabilidade: Mapped[float | None] = mapped_column(DIN)
    valor_ecomet: Mapped[float | None] = mapped_column(DIN)
    diferenca: Mapped[float | None] = mapped_column(DIN)
    justificativa: Mapped[str | None] = mapped_column(Text)
    regra_id: Mapped[int | None] = mapped_column(ForeignKey("conc_regra_justificativa.id"))
    responsavel: Mapped[str | None] = mapped_column(String(60))
    resolvido_em: Mapped[dt.datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("severidade in ('alto','revisar')", name="ck_concdiv_severidade"),
        CheckConstraint(
            "status in ('aberta','corrigida_ecomet','devolvida_contabilidade','justificada')",
            name="ck_concdiv_status"),
        Index("ix_concdiv_periodo", "periodo_id", "status", "severidade"),
    )


class ConcRegraJustificativa(Base):
    """Justificativa recorrente (fase 5 do pacote original): 'CFOP 1556 e' sempre uso e
    consumo, nao precisa perguntar de novo todo mes'."""
    __tablename__ = "conc_regra_justificativa"
    id: Mapped[int] = mapped_column(primary_key=True)
    inscricao_estadual: Mapped[str] = mapped_column(String(14), default="260070009")
    escopo: Mapped[str] = mapped_column(String(20))     # cfop | emitente | tipo_divergencia
    chave: Mapped[str] = mapped_column(String(40))
    motivo: Mapped[str] = mapped_column(Text)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)
    criada_em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    criada_por: Mapped[str | None] = mapped_column(String(60))

    __table_args__ = (
        Index("ix_concregra_unico", "inscricao_estadual", "escopo", "chave", unique=True),
    )


class ConcApuracaoLinha(Base):
    """Uma linha da apuracao normal de ICMS (grupo debito|outros_debitos|credito|
    outros_creditos|saldo), no mesmo espirito de ApuracaoMes mas para o ICMS da empresa
    toda, nao so' o TTD 409 de importados."""
    __tablename__ = "conc_apuracao_linha"
    id: Mapped[int] = mapped_column(primary_key=True)
    periodo_id: Mapped[int] = mapped_column(ForeignKey("conc_periodo.id", ondelete="CASCADE"))
    grupo: Mapped[str] = mapped_column(String(20))    # debito|outros_debitos|credito|outros_creditos|saldo
    ordem: Mapped[int] = mapped_column(Integer)
    rotulo: Mapped[str] = mapped_column(Text)
    valor: Mapped[float] = mapped_column(DIN, default=0)
    origem_texto: Mapped[str | None] = mapped_column(Text)
    editavel: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_concapur_unico", "periodo_id", "grupo", "ordem", unique=True),
    )


class ConcFechamento(Base):
    __tablename__ = "conc_fechamento"
    id: Mapped[int] = mapped_column(primary_key=True)
    periodo_id: Mapped[int] = mapped_column(
        ForeignKey("conc_periodo.id", ondelete="RESTRICT"), unique=True)
    total_debitos: Mapped[float] = mapped_column(DIN)
    total_creditos: Mapped[float] = mapped_column(DIN)
    imposto_a_recolher: Mapped[float] = mapped_column(DIN, default=0)
    saldo_credor_transportado: Mapped[float] = mapped_column(DIN, default=0)
    snapshot: Mapped[dict] = mapped_column(JSON)
    fechado_em: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    fechado_por: Mapped[str | None] = mapped_column(String(60))
