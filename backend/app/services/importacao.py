"""Importacao de NF-e a partir do XML.

Caminhos de entrada, na ordem em que foram decididos com o Victor em 27/08/2026:
  1. Pacote ZIP exportado do sistema atual  - principal, e' o que ele controla hoje
  2. Pasta vigiada no servidor              - quando houver acesso a' maquina
  3. NFeDistribuicaoDFe com certificado A1  - ver sefaz.py

Nenhum valor fiscal e' lido de PDF. Nunca.
"""
from __future__ import annotations

import datetime as dt
import io
import zipfile
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (ArquivoImportado, Configuracao, Excecao, LoteImportacao, Nota, NotaItem,
                      Parceiro, Produto)
from . import estoque as est
from . import fechamento as fec
from .xml_nfe import NotaFiscal, XmlInvalido, evento_cancelamento, ler

# CFOPs de devolucao de venda que voltam como entrada
CFOP_DEVOLUCAO = {"1201", "1202", "1410", "1411", "2201", "2202", "2410", "2411"}
ORIGEM_IMPORTADA = {"1", "2", "3", "6", "7", "8"}


def cnpj_empresa(db: Session) -> str | None:
    v = db.get(Configuracao, "cnpj_empresa")
    return (v.valor or "").strip() if v and v.valor else None


def definir_cnpj_empresa(db: Session, cnpj: str, usuario: str = "fiscal"):
    limpo = "".join(c for c in cnpj if c.isdigit())
    reg = db.get(Configuracao, "cnpj_empresa")
    if reg is None:
        reg = Configuracao(chave="cnpj_empresa",
                           descricao="CNPJ do estabelecimento. Decide se a NF-e e' entrada ou saida.")
        db.add(reg)
    reg.valor = limpo
    reg.alterado_por = usuario
    db.flush()
    return limpo


def detectar_cnpj(notas: list[NotaFiscal]) -> tuple[str | None, int, int]:
    """Sem A1 e sem cadastro previo, o proprio pacote diz qual e' o CNPJ do estabelecimento:
    e' o unico que aparece dos DOIS lados - emitindo as saidas e recebendo as entradas.
    Devolve (cnpj, quantas vezes apareceu, quantos candidatos empataram)."""
    contagem: dict[str, int] = {}
    for nf in notas:
        for cnpj in (nf.emit_cnpj, nf.dest_cnpj):
            if cnpj and len(cnpj) == 14:
                contagem[cnpj] = contagem.get(cnpj, 0) + 1
    if not contagem:
        return None, 0, 0
    ordenado = sorted(contagem.items(), key=lambda kv: -kv[1])
    melhor, vezes = ordenado[0]
    empate = sum(1 for _, v in ordenado if v == vezes)
    return melhor, vezes, empate


@dataclass
class Resultado:
    arquivo: str
    situacao: str
    motivo: str | None = None
    chave: str | None = None
    numero: int | None = None
    tipo: str | None = None
    nota_id: int | None = None


def derivar_bloco(nf: NotaFiscal, item) -> tuple[str | None, str | None]:
    """Deriva o bloco do TTD a partir do que ja' esta' no XML: CFOP, UF e aliquota.
    Devolve (bloco, motivo_da_pendencia). Bloco None = fora do beneficio."""
    cfop = (item.cfop or "").strip()
    if not cfop:
        return None, "Item sem CFOP"
    if cfop.startswith("7"):
        return None, None            # exportacao: fora do beneficio, entra so' no estoque
    aliq = item.aliquota
    if cfop.startswith("5"):
        if aliq is not None and abs(aliq - 0.12) > 0.0001:
            return "3", (f"CFOP {cfop} (interna) com aliquota de {aliq*100:.2f}% - a tabela do TTD "
                         "usa 12% na operacao interna. Confira antes de apurar.")
        return "3", None
    if cfop.startswith("6"):
        if aliq is not None and abs(aliq - 0.04) < 0.0001:
            return "2", None
        if aliq is not None and abs(aliq - 0.12) < 0.0001:
            if item.origem in ORIGEM_IMPORTADA:
                return "2", (f"Item com origem {item.origem} (importada) e aliquota de 12%. "
                             "Mercadoria importada em operacao interestadual costuma ser 4%.")
            return "1", None
        if item.origem in ORIGEM_IMPORTADA:
            return "2", (f"CFOP {cfop} com aliquota de "
                         f"{'nao informada' if aliq is None else f'{aliq*100:.2f}%'} - "
                         "classificado no bloco 2 pela origem do item. Confira.")
        return "1", (f"CFOP {cfop} com aliquota de "
                     f"{'nao informada' if aliq is None else f'{aliq*100:.2f}%'}, fora da tabela "
                     "do TTD (4% ou 12%). Classificado no bloco 1 - confira.")
    return None, None


def _parceiro(db: Session, cnpj: str | None, nome: str | None, uf: str | None,
              exterior: bool, papel: str) -> Parceiro | None:
    """Casa por CNPJ; se nao houver, casa pelo nome e APROVEITA para gravar o CNPJ que faltava
    nos 60 parceiros vindos da planilha."""
    nome_limpo = " ".join((nome or "").replace("\xa0", " ").split()).upper() or None
    p = None
    if cnpj:
        p = db.execute(select(Parceiro).where(Parceiro.cnpj == cnpj)).scalars().first()
    if p is None and nome_limpo:
        p = db.execute(select(Parceiro).where(Parceiro.nome == nome_limpo)).scalars().first()
    if p is None and nome_limpo:
        for cand in db.execute(select(Parceiro)).scalars():
            if nome_limpo in (cand.variantes or "").upper() or nome_limpo == cand.nome:
                p = cand
                break
    if p is None:
        if not nome_limpo:
            return None
        p = Parceiro(nome=nome_limpo, cnpj=cnpj, uf=uf, exterior=exterior, papel=papel,
                     status="do_xml")
        db.add(p)
        db.flush()
        return p
    if cnpj and not p.cnpj:
        p.cnpj = cnpj                # o XML preenche o que a planilha nunca teve
    if uf and not p.uf:
        p.uf = uf
    if p.papel and papel and p.papel != papel:
        p.papel = "ambos"
    return p


def _produto(db: Session, descricao: str, ncm: str | None) -> tuple[Produto, str | None]:
    desc = " ".join((descricao or "").replace("\xa0", " ").split()).upper()
    p = db.execute(select(Produto).where(Produto.descricao == desc)).scalars().first()
    if p:
        if ncm and not p.ncm:
            p.ncm = ncm
        return p, None
    if ncm:
        iguais = db.execute(select(Produto).where(Produto.ncm == ncm)).scalars().all()
        if len(iguais) == 1:
            return iguais[0], (f"Produto '{desc}' casado com '{iguais[0].descricao}' pelo NCM {ncm}. "
                               "Confirme se e' o mesmo produto.")
    p = Produto(descricao=desc, ncm=ncm, status="do_xml")
    db.add(p)
    db.flush()
    return p, (f"Produto '{desc}' nao existia no cadastro e foi criado a partir do XML "
               f"(NCM {ncm or 'nao informado'}). Confirme antes de apurar.")


def importar_nota(db: Session, nf: NotaFiscal, usuario: str, origem: str) -> Resultado:
    cnpj_nosso = cnpj_empresa(db)
    if not cnpj_nosso:
        return Resultado("", "erro", "CNPJ da empresa nao configurado - defina em /api/configuracao")

    ja = db.execute(select(Nota).where(Nota.chave_acesso == nf.chave)).scalars().first()
    if ja:
        return Resultado("", "duplicada", f"Chave ja' importada no lancamento #{ja.id}",
                         nf.chave, nf.numero, ja.tipo, ja.id)

    if nf.situacao and nf.situacao not in ("100", "150"):
        return Resultado("", "ignorada", f"Protocolo com cStat {nf.situacao} (nao autorizada)",
                         nf.chave, nf.numero)

    if nf.emit_cnpj == cnpj_nosso:
        tipo = "S" if nf.tipo_nf == "1" else "E"
        parceiro = _parceiro(db, nf.dest_cnpj, nf.dest_nome, nf.dest_uf, nf.dest_exterior,
                             "cliente" if tipo == "S" else "fornecedor")
    elif nf.dest_cnpj == cnpj_nosso:
        tipo = "E"
        parceiro = _parceiro(db, nf.emit_cnpj, nf.emit_nome, nf.emit_uf, False, "fornecedor")
    else:
        return Resultado("", "ignorada",
                         "NF-e nao e' do estabelecimento (nem emitente nem destinatario)",
                         nf.chave, nf.numero)

    cfop = nf.cfop_principal or ""
    if tipo == "E":
        natureza = ("DEVOLUCAO" if (cfop in CFOP_DEVOLUCAO or nf.finalidade == "4")
                    else "IMPORTACAO" if cfop.startswith("3") else "COMPRA")
    else:
        natureza = "DEVOLUCAO" if nf.finalidade == "4" else "VENDA"

    try:
        fec.exigir_aberta(db, nf.data_emissao)
    except fec.CompetenciaFechada as e:
        return Resultado("", "pendente", e.mensagem, nf.chave, nf.numero, tipo)

    if nf.data_emissao > dt.date.today():
        return Resultado("", "pendente", f"Data de emissao {nf.data_emissao:%d/%m/%Y} e' futura",
                         nf.chave, nf.numero, tipo)

    nota = Nota(chave_acesso=nf.chave, numero=nf.numero, serie=nf.serie, modelo=nf.modelo,
                tipo=tipo, cfop=cfop, natureza=natureza, data_emissao=nf.data_emissao,
                data_mov=nf.data_emissao, parceiro_id=parceiro.id if parceiro else None,
                valor_total=nf.valor_total, status="lancada", criado_por=usuario,
                origem_registro=f"XML ({origem})", observacao=nf.natureza)
    db.add(nota)
    db.flush()

    pendencias: list[str] = []
    produtos = []
    for item in nf.itens:
        produto, aviso = _produto(db, item.descricao, item.ncm)
        if aviso:
            pendencias.append(aviso)
        bloco = None
        if tipo == "S" or natureza == "DEVOLUCAO":
            bloco, motivo = derivar_bloco(nf, item)
            if motivo:
                pendencias.append(f"Item {item.numero}: {motivo}")
        db.add(NotaItem(nota_id=nota.id, produto_id=produto.id, ncm=item.ncm,
                        origem_merc=item.origem, quantidade=item.quantidade, valor=item.valor,
                        base_calculo=item.base_calculo if item.base_calculo is not None else item.valor,
                        aliquota=item.aliquota, cst=item.cst, bloco_ttd=bloco,
                        custo_unit=(item.valor / item.quantidade)
                        if tipo == "E" and item.quantidade else None))
        produtos.append(produto.id)
        if tipo == "S" and natureza != "DEVOLUCAO":
            disponivel = float(est.saldo(db, produto.id, nf.data_emissao))
            falta = item.quantidade - disponivel
            if falta > 0.0005:
                pendencias.append(
                    f"{produto.descricao}: saída de {item.quantidade:,.1f} kg com saldo de "
                    f"{disponivel:,.1f} kg na data. Acerto lançado automaticamente.")
    db.flush()
    est.recalcular_varios(db, produtos, usuario)

    for p in pendencias:
        db.add(Excecao(tipo="importacao_xml", nota_id=nota.id, descricao=p, criado_por=usuario))

    return Resultado("", "pendente" if pendencias else "importada",
                     "; ".join(pendencias) if pendencias else None,
                     nf.chave, nf.numero, tipo, nota.id)


def importar_zip(db: Session, conteudo: bytes, nome: str, usuario: str = "fiscal") -> LoteImportacao:
    """Le todos os .xml de dentro do pacote, inclusive em subpastas e em zips aninhados."""
    lote = LoteImportacao(origem="zip", nome=nome, criado_por=usuario)
    db.add(lote)
    db.flush()

    arquivos: list[tuple[str, bytes]] = []

    def _abrir(dados: bytes, prefixo: str = ""):
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                nome_i = f"{prefixo}{info.filename}"
                if nome_i.lower().endswith(".xml"):
                    arquivos.append((nome_i, z.read(info)))
                elif nome_i.lower().endswith(".zip"):
                    _abrir(z.read(info), f"{nome_i}/")

    try:
        _abrir(conteudo)
    except zipfile.BadZipFile:
        lote.erros = 1
        db.add(ArquivoImportado(lote_id=lote.id, arquivo=nome, situacao="erro",
                                motivo="Arquivo nao e' um ZIP valido"))
        db.commit()
        return lote

    # Se o CNPJ ainda nao foi configurado, o proprio pacote responde qual e'.
    if not cnpj_empresa(db):
        lidas = []
        for _, dados in arquivos:
            try:
                lidas.append(ler(dados))
            except XmlInvalido:
                continue
        cnpj, vezes, empate = detectar_cnpj(lidas)
        if cnpj and empate == 1:
            definir_cnpj_empresa(db, cnpj, usuario)
            db.add(Excecao(tipo="cnpj_detectado", descricao=(
                f"O CNPJ {cnpj} foi identificado automaticamente como o do estabelecimento: "
                f"aparece em {vezes} dos {len(lidas)} documentos do pacote, dos dois lados da "
                "operacao. Confirme na aba Importar XML se estiver errado."), criado_por=usuario))
            db.flush()

    cancelamentos: list[tuple[str, str]] = []
    for nome_arq, dados in arquivos:
        chave_cancelada = evento_cancelamento(dados)
        if chave_cancelada:
            cancelamentos.append((nome_arq, chave_cancelada))
            continue
        try:
            nf = ler(dados)
        except XmlInvalido as e:
            db.add(ArquivoImportado(lote_id=lote.id, arquivo=nome_arq, situacao="erro",
                                    motivo=str(e)))
            continue
        r = importar_nota(db, nf, usuario, f"zip:{nome}")
        db.add(ArquivoImportado(lote_id=lote.id, arquivo=nome_arq, situacao=r.situacao,
                                motivo=r.motivo, chave_acesso=r.chave, numero=r.numero,
                                tipo=r.tipo, nota_id=r.nota_id))

    for nome_arq, chave in cancelamentos:
        nota = db.execute(select(Nota).where(Nota.chave_acesso == chave)).scalars().first()
        if nota is None:
            db.add(ArquivoImportado(lote_id=lote.id, arquivo=nome_arq, situacao="ignorada",
                                    chave_acesso=chave,
                                    motivo="Evento de cancelamento de uma NF-e que nao esta' na base"))
            continue
        if nota.status != "cancelada":
            nota.status = "cancelada"
            nota.observacao = ((nota.observacao or "") + " | CANCELADA pelo evento no XML").strip(" |")
            est.recalcular_varios(db, [i.produto_id for i in nota.itens], usuario)
        db.add(ArquivoImportado(lote_id=lote.id, arquivo=nome_arq, situacao="importada",
                                chave_acesso=chave, nota_id=nota.id,
                                motivo="Cancelamento aplicado"))

    db.flush()
    contagem = {}
    for a in db.execute(select(ArquivoImportado)
                        .where(ArquivoImportado.lote_id == lote.id)).scalars():
        contagem[a.situacao] = contagem.get(a.situacao, 0) + 1
    lote.total = sum(contagem.values())
    lote.importadas = contagem.get("importada", 0)
    lote.duplicadas = contagem.get("duplicada", 0)
    lote.pendentes = contagem.get("pendente", 0)
    lote.erros = contagem.get("erro", 0) + contagem.get("ignorada", 0)
    db.commit()
    db.refresh(lote)
    return lote
