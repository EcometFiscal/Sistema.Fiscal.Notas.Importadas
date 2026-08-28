"""Lancamento unico: a nota entra uma vez e alimenta estoque e apuracao ao mesmo tempo."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Auditoria, Excecao, Nota, NotaItem, Parceiro, Produto
from ..schemas import ItemIn, NotaIn
from . import apuracao as ap
from . import estoque as est
from . import fechamento as fec


def br(v: float, casas: int = 1) -> str:
    """Numero no formato brasileiro - a mensagem e' lida por quem fala portugues."""
    return f"{v:,.{casas}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


class ErroLancamento(Exception):
    def __init__(self, mensagem: str, avisos: list[dict] | None = None, status: int = 400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.avisos = avisos or []
        self.status = status


def _parceiro(db: Session, dados: NotaIn) -> Parceiro | None:
    if dados.parceiro_id:
        p = db.get(Parceiro, dados.parceiro_id)
        if not p:
            raise ErroLancamento(f"Parceiro {dados.parceiro_id} não existe")
        return p
    if dados.parceiro:
        nome = " ".join(dados.parceiro.replace("\xa0", " ").split()).upper()
        p = db.execute(select(Parceiro).where(Parceiro.nome == nome)).scalars().first()
        if not p:
            p = Parceiro(nome=nome, papel="cliente" if dados.tipo == "S" else "fornecedor")
            db.add(p)
            db.flush()
        return p
    return None


def _produto(db: Session, item: ItemIn) -> Produto:
    if item.produto_id:
        p = db.get(Produto, item.produto_id)
        if not p:
            raise ErroLancamento(f"Produto {item.produto_id} não existe")
        return p
    if not item.produto:
        raise ErroLancamento("Item sem produto informado")
    desc = " ".join(item.produto.replace("\xa0", " ").split()).upper()
    p = db.execute(select(Produto).where(Produto.descricao == desc)).scalars().first()
    if not p:
        p = Produto(descricao=desc, ncm=item.ncm)
        db.add(p)
        db.flush()
    return p


def criar_nota(db: Session, dados: NotaIn, usuario: str = "sistema") -> tuple[Nota, list[dict]]:
    fec.exigir_aberta(db, dados.data_mov)      # mes fechado nao muda sozinho
    if dados.data_mov > dt.date.today():
        raise ErroLancamento(
            f"Data {dados.data_mov:%d/%m/%Y} é futura. O histórico tem um caso desses "
            "(NF 22190) e foi assim que o painel passou dois meses mostrando data errada.")

    avisos: list[dict] = []
    parceiro = _parceiro(db, dados)

    dup = db.execute(select(Nota).where(
        Nota.tipo == dados.tipo, Nota.numero == dados.numero,
        Nota.serie == dados.serie, Nota.data_mov == dados.data_mov,
        Nota.parceiro_id == (parceiro.id if parceiro else None),
        Nota.status != "cancelada")).scalars().first()
    if dup:
        avisos.append(dict(
            codigo="possivel_duplicata",
            exige=None if dados.confirmar_duplicata else "confirmar_duplicata",
            mensagem=(f"Já existe a NF {dados.numero} série {dados.serie} do mesmo parceiro em "
                      f"{dados.data_mov:%d/%m/%Y} (lançamento #{dup.id}). Notas diferentes podem ter "
                      "dados idênticos — confirme se é outro documento."),
            dados=dict(nota_id=dup.id)))

    itens_prep = []
    for item in dados.itens:
        produto = _produto(db, item)
        itens_prep.append((item, produto))
        if dados.tipo == "S" and dados.natureza != "DEVOLUCAO":
            disponivel = est.saldo(db, produto.id, dados.data_mov)
            falta = float(item.quantidade) - float(disponivel)
            if falta > 0.0005:
                avisos.append(dict(
                    codigo="saldo_insuficiente",
                    exige=None if dados.justificativa else "justificativa",
                    mensagem=(f"{produto.descricao}: saldo de {br(float(disponivel))} kg em "
                              f"{dados.data_mov:%d/%m/%Y} e a saída é de {br(item.quantidade)} kg. "
                              f"Faltam {br(falta)} kg. Grave com justificativa; o saldo do "
                              "produto ficará negativo até uma entrada real cobrir a diferença."),
                    dados=dict(produto_id=produto.id, produto=produto.descricao,
                               saldo=float(disponivel), falta=falta)))

    if any(a.get("exige") for a in avisos):
        raise ErroLancamento("O lançamento precisa de confirmação", avisos, status=422)

    nota = Nota(chave_acesso=dados.chave_acesso or None, numero=dados.numero, serie=dados.serie,
                modelo=dados.modelo, tipo=dados.tipo, cfop=dados.cfop, natureza=dados.natureza,
                data_emissao=dados.data_emissao or dados.data_mov, data_mov=dados.data_mov,
                parceiro_id=parceiro.id if parceiro else None, observacao=dados.observacao,
                criado_por=usuario, origem_registro="lancamento manual",
                valor_total=sum(i.valor or 0 for i in dados.itens))
    db.add(nota)
    db.flush()

    produtos_afetados = []
    for item, produto in itens_prep:
        qtd = float(item.quantidade)
        custo = (item.valor / qtd) if (item.valor and qtd) else None
        db.add(NotaItem(nota_id=nota.id, produto_id=produto.id, quantidade=qtd, valor=item.valor,
                        base_calculo=item.base_calculo if item.base_calculo is not None else item.valor,
                        bloco_ttd=item.bloco_ttd, cst=item.cst, ncm=item.ncm or produto.ncm,
                        custo_unit=custo if dados.tipo == "E" else None))
        produtos_afetados.append(produto.id)
    db.flush()

    if dup and dados.confirmar_duplicata:
        db.add(Excecao(tipo="duplicata_confirmada", nota_id=nota.id,
                       descricao=(f"NF {nota.numero} lançada mesmo existindo a nota #{dup.id} com "
                                  "número, série, parceiro e data iguais."),
                       justificativa=dados.justificativa, criado_por=usuario))
    if dados.justificativa:
        for a in [x for x in avisos if x["codigo"] == "saldo_insuficiente"]:
            db.add(Excecao(tipo="saida_sem_saldo", nota_id=nota.id,
                           produto_id=a["dados"]["produto_id"], quantidade=a["dados"]["falta"],
                           descricao=a["mensagem"], justificativa=dados.justificativa,
                           criado_por=usuario))

    est.recalcular_varios(db, produtos_afetados, usuario)
    db.add(Auditoria(tabela="nota", registro_id=nota.id, operacao="INSERT", antes=None,
                     usuario=usuario,
                     depois=dict(numero=nota.numero, tipo=nota.tipo, data=str(nota.data_mov),
                                 valor=float(nota.valor_total or 0),
                                 itens=[dict(produto_id=p, quantidade=float(i.quantidade))
                                        for i, p in [(x[0], x[1].id) for x in itens_prep]])))
    db.commit()
    db.refresh(nota)
    return nota, avisos


def cancelar_nota(db: Session, nota_id: int, motivo: str, usuario: str) -> Nota:
    nota = db.get(Nota, nota_id)
    if not nota:
        raise ErroLancamento("Nota não encontrada", status=404)
    if nota.status == "cancelada":
        raise ErroLancamento("Nota já cancelada")
    fec.exigir_aberta(db, nota.data_mov)
    produtos = [i.produto_id for i in nota.itens]
    nota.status = "cancelada"
    nota.observacao = ((nota.observacao or "") + f" | CANCELADA: {motivo}").strip(" |")
    db.add(Auditoria(tabela="nota", registro_id=nota.id, operacao="CANCELAR", usuario=usuario,
                     antes=dict(status="lancada"), depois=dict(status="cancelada", motivo=motivo)))
    est.recalcular_varios(db, produtos, usuario)
    db.commit()
    db.refresh(nota)
    return nota


def resumo_pos_lancamento(db: Session, nota: Nota) -> dict:
    produtos = {i.produto_id for i in nota.itens}
    pos = [p for p in est.posicao(db) if p["produto_id"] in produtos]
    comp = f"{nota.data_mov.year}-{nota.data_mov.month:02d}"
    return dict(estoque=pos, apuracao=ap.previa(db, comp))
