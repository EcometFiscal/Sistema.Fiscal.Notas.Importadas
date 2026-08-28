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
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (ArquivoImportado, Configuracao, Excecao, LoteImportacao, Nota, NotaItem,
                      Parceiro, Produto)
from . import apuracao as ap
from . import estoque as est
from . import fechamento as fec
from .xml_nfe import NotaFiscal, XmlInvalido, evento_cancelamento, evento_outro, ler

# CFOPs de devolucao de venda que voltam como entrada
CFOP_DEVOLUCAO = {"1201", "1202", "1410", "1411", "2201", "2202", "2410", "2411"}
# Mercadoria importada, para efeito do TTD: so' orig 1 (importacao direta) e 6 (importacao com
# industrializacao interna, sem similar nacional). Nao usar a lista mais larga de origens da
# tabela de ICMS (2,3,7,8) - essa e' outra coisa, nao decide TTD.
ORIGEM_IMPORTADA_TTD = {"1", "6"}
# A entrada de mercadoria importada e' sempre CFOP 3102 (Victor, 28/08/2026). O sistema do
# Victor emite, alem dela, uma NF por lote com CFOP 3949 para cada desdobramento fisico do
# mesmo lote (referenciando a 3102 original em NFref) - mesma mercadoria, mesma quantidade
# somada, mesmo valor somado. Importar as duas dobraria a entrada.
CFOP_DESDOBRAMENTO_IGNORAR = "3949"
# NCM da sucata metalica que o TTD cobre - fora dessa lista e' equipamento ou mercadoria fora
# do escopo do Lastro (ex.: prensa hidraulica importada com origem 1, NF 6532/julho-2026), mesmo
# que o item tenha origem de mercadoria importada. Victor, 28/08/2026: ignorar a nota inteira,
# nao criar produto novo pra isso no cadastro.
NCM_METAL_CONHECIDO = set(ap.PRODUTO_NCM.values())


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
    # Produtos cujo custeio PEPS precisa recalcular. Devolvido em vez de recalculado aqui dentro
    # pra importar_zip juntar tudo do pacote e recalcular cada produto uma vez so' no final -
    # nao uma vez por nota (um pacote com 40 notas do mesmo produto nao pode reler o historico
    # inteiro do produto 40 vezes seguidas).
    produtos_afetados: list[int] = field(default_factory=list)


def derivar_bloco(db: Session, ncm: str | None, uf_contraparte: str | None, data: dt.date,
                  aliquota_xml: float | None = None) -> tuple[str | None, str | None]:
    """Deriva o bloco do TTD por produto (NCM) e ambito da operacao (interna em SC ou
    interestadual) - nao mais por CFOP. CFOP continua decidindo so' a natureza (compra, venda,
    devolucao, importacao), nao a aliquota.
    Devolve (bloco, motivo_da_pendencia). Bloco None = fora do beneficio ou NCM sem regra."""
    ncm = (ncm or "").strip()
    if not ncm:
        return None, "Item sem NCM"
    if not ap.ncm_tem_regra(db, ncm, data):
        return None, f"NCM {ncm} sem regra cadastrada de TTD"
    ambito = "interna" if (uf_contraparte or "").upper() == "SC" else "interestadual"
    r = ap.regra_produto(db, ncm, ambito, data)
    if r is None:
        return None, None      # NCM conhecido, mas sem beneficio neste ambito (ex.: cobre interno)
    motivo = None
    if aliquota_xml is not None and abs(float(aliquota_xml) - float(r.aliquota)) > 0.0001:
        motivo = (f"Aliquota do XML ({float(aliquota_xml)*100:.2f}%) diverge da tabela do TTD "
                 f"para NCM {ncm} {ambito} ({float(r.aliquota)*100:.2f}%). Apurado pela tabela.")
    return r.bloco, motivo


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


TOLERANCIA_CENTAVOS = 0.01


def _valor_compativel(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= TOLERANCIA_CENTAVOS


def buscar_candidatas_historico(db: Session, nf: NotaFiscal, tipo: str) -> list[Nota]:
    """Casa o XML com uma nota migrada da planilha (sem chave de acesso, porque a planilha
    nunca teve esse campo) pelo tipo, numero, serie e data_mov. Sem isto, importar hoje o XML
    de um mes ja' migrado duplicaria tudo: a deduplicacao normal (por chave_acesso) nao teria
    nada pra comparar, porque a nota migrada nao tem chave."""
    return db.execute(
        select(Nota).where(Nota.chave_acesso.is_(None), Nota.tipo == tipo,
                           Nota.numero == nf.numero, Nota.serie == (nf.serie or "1"),
                           Nota.data_mov == nf.data_emissao)
    ).scalars().all()


def _dados_fiscais_item(db: Session, item, tipo: str, natureza: str, uf_contraparte: str | None,
                        data: dt.date) -> tuple[Produto, str | None, list[str]]:
    """Produto, bloco do TTD e pendencias de um item do XML. Usada tanto para nota nova quanto
    para complementar uma nota migrada - as duas trilhas nunca podem divergir na regra que
    decide o bloco, ou a apuracao do historico complementado deixa de bater com a planilha."""
    produto, aviso = _produto(db, item.descricao, item.ncm)
    pendencias = [aviso] if aviso else []
    bloco = None
    origem_importada = (item.origem or "") in ORIGEM_IMPORTADA_TTD
    if not origem_importada:
        pendencias.append(
            f"Item {item.numero}: origem {item.origem or 'nao informada'} nao e' mercadoria "
            "importada (TTD exige orig 1 ou 6) - fora da apuracao do TTD.")
    elif tipo == "S" or natureza == "DEVOLUCAO":
        bloco, motivo = derivar_bloco(db, item.ncm, uf_contraparte, data, item.aliquota)
        if motivo:
            pendencias.append(f"Item {item.numero}: {motivo}")
    return produto, bloco, pendencias


def _agrupar_itens_por_produto(db: Session, nf: NotaFiscal, tipo: str, natureza: str,
                               uf_contraparte: str | None) -> tuple[dict[int, dict], list[str]]:
    """Agrupa os itens do XML pelo produto que _dados_fiscais_item resolve. A granularidade do
    lote no XML nao importa pra casar com a nota migrada (a planilha so' tem um item por
    produto) - Victor, 28/08/2026. Produto/NCM/origem/aliquota/CST/bloco inconsistentes entre
    lotes do mesmo produto viram pendencia, nunca escolha no escuro."""
    grupos: dict[int, dict] = {}
    pendencias: list[str] = []
    for item in nf.itens:
        produto, bloco, avisos = _dados_fiscais_item(db, item, tipo, natureza, uf_contraparte,
                                                      nf.data_emissao)
        pendencias.extend(avisos)
        fiscal = (item.ncm, item.origem, item.aliquota, item.cst, bloco)
        g = grupos.get(produto.id)
        if g is None:
            grupos[produto.id] = dict(produto=produto, quantidade=item.quantidade,
                                      fiscal=fiscal, consistente=True, numeros=[item.numero])
        else:
            g["quantidade"] += item.quantidade
            g["numeros"].append(item.numero)
            if g["fiscal"] != fiscal:
                g["consistente"] = False
    for g in grupos.values():
        if not g["consistente"]:
            pendencias.append(
                f"Itens {g['numeros']} do XML sao do mesmo produto ({g['produto'].descricao}) "
                "mas com NCM/origem/aliquota/CST/bloco diferentes entre os lotes - confira "
                "manualmente, nao gravado.")
    return grupos, pendencias


def complementar_historico(db: Session, nota: Nota, nf: NotaFiscal, cfop: str, natureza: str,
                           uf_contraparte: str | None, usuario: str) -> Resultado:
    """Preenche numa nota migrada da planilha os campos fiscais que so' o XML tem: chave de
    acesso, CFOP, natureza e, por item, NCM/origem/aliquota/CST/bloco. Quantidade e valor sao
    intocaveis - o que a planilha trouxe sobre peso e dinheiro e' o que vale pro estoque e pra
    apuracao ja' fechados; o XML so' acrescenta o que faltava."""
    pendencias: list[str] = []
    if not _valor_compativel(nota.valor_total, nf.valor_total):
        pendencias.append(
            f"Valor do XML (R$ {nf.valor_total or 0:,.2f}) diverge do valor migrado da planilha "
            f"(R$ {float(nota.valor_total or 0):,.2f}) para a NF {nota.numero}. Complementada "
            "mesmo assim - nao corrigido automaticamente, confira qual esta certo.")

    nota.chave_acesso = nf.chave
    nota.cfop = cfop
    nota.natureza = natureza
    nota.observacao = ((nota.observacao or "") + " | complementada por XML").strip(" |")
    if nota.parceiro:
        contraparte_cnpj = nf.dest_cnpj if nota.tipo == "S" else nf.emit_cnpj
        if contraparte_cnpj and not nota.parceiro.cnpj:
            nota.parceiro.cnpj = contraparte_cnpj
        if uf_contraparte and not nota.parceiro.uf:
            nota.parceiro.uf = uf_contraparte

    grupos, avisos = _agrupar_itens_por_produto(db, nf, nota.tipo, natureza, uf_contraparte)
    pendencias.extend(avisos)

    usados: set[int] = set()
    for produto_id, g in grupos.items():
        if not g["consistente"]:
            continue                                    # ja' virou pendencia, nao grava no escuro
        candidatos = [i for i in nota.itens if i.id not in usados
                     and abs(float(i.quantidade) - g["quantidade"]) <= 0.001]
        if len(candidatos) != 1:
            pendencias.append(
                (f"{g['produto'].descricao} do XML ({g['quantidade']:,.1f} kg) nao foi casado "
                 f"com nenhum item da NF {nota.numero} migrada - confira manualmente."
                 if not candidatos else
                 f"{g['produto'].descricao} do XML ({g['quantidade']:,.1f} kg) bate com "
                 f"{len(candidatos)} itens da NF {nota.numero} migrada - nao escolhido "
                 "automaticamente."))
            continue
        alvo = candidatos[0]
        usados.add(alvo.id)
        if alvo.produto_id != produto_id:
            # A quantidade bate mas o produto da planilha diverge do XML: o XML manda (Victor,
            # 28/08/2026) - a planilha e' quem estava errada, nao o XML.
            pendencias.append(
                f"Produto do item da NF {nota.numero} corrigido conforme o XML: estava "
                f"'{alvo.produto.descricao}', o XML diz '{g['produto'].descricao}' (mesma "
                f"quantidade, {g['quantidade']:,.1f} kg).")
            alvo.produto_id = produto_id
        ncm, origem, aliquota, cst, bloco = g["fiscal"]
        alvo.ncm, alvo.origem_merc, alvo.aliquota = ncm, origem, aliquota
        alvo.cst, alvo.bloco_ttd = cst, bloco

    db.flush()
    for p in pendencias:
        db.add(Excecao(tipo="importacao_xml", nota_id=nota.id, descricao=p, criado_por=usuario))

    return Resultado("", "pendente" if pendencias else "complementada",
                     "; ".join(pendencias) if pendencias else None,
                     nf.chave, nf.numero, nota.tipo, nota.id)


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

    if nf.cfop_principal == CFOP_DESDOBRAMENTO_IGNORAR:
        return Resultado("", "ignorada", (
            "CFOP 3949: desdobramento de uma NF-e de importacao (CFOP 3102) ja contabilizada "
            "por ela mesma - ignorada para nao duplicar a entrada."), nf.chave, nf.numero)

    if not any((item.origem or "") in ORIGEM_IMPORTADA_TTD for item in nf.itens):
        return Resultado("", "ignorada",
                         "Nenhum item com origem de mercadoria importada (orig 1 ou 6)",
                         nf.chave, nf.numero)

    if not any((item.ncm or "") in NCM_METAL_CONHECIDO for item in nf.itens):
        return Resultado("", "ignorada", (
            "Nenhum item com NCM de sucata metalica do TTD - nota de equipamento ou mercadoria "
            "fora do escopo do sistema, ignorada."), nf.chave, nf.numero)

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

    # Contraparte da operacao (quem nao e' a gente nesta NF-e) decide o ambito interna/
    # interestadual - vem do XML e, so' se faltar, do cadastro do parceiro.
    uf_contraparte = (nf.dest_uf if tipo == "S" else nf.emit_uf) or (parceiro.uf if parceiro else None)

    try:
        fec.exigir_aberta(db, nf.data_emissao)
    except fec.CompetenciaFechada as e:
        return Resultado("", "pendente", e.mensagem, nf.chave, nf.numero, tipo)

    if nf.data_emissao > dt.date.today():
        return Resultado("", "pendente", f"Data de emissao {nf.data_emissao:%d/%m/%Y} e' futura",
                         nf.chave, nf.numero, tipo)

    candidatas = buscar_candidatas_historico(db, nf, tipo)
    if len(candidatas) == 1:
        return complementar_historico(db, candidatas[0], nf, cfop, natureza, uf_contraparte,
                                      usuario)
    if len(candidatas) > 1:
        nums = ", ".join(f"#{n.id} (NF {n.numero})" for n in candidatas)
        db.add(Excecao(tipo="casamento_ambiguo", descricao=(
            f"NF {nf.numero} do XML bate com {len(candidatas)} notas migradas sem chave de "
            f"acesso ({nums}) - mesmo tipo/numero/serie/data. Nao escolhida automaticamente; "
            "complemente manualmente ou grave a chave na nota certa."), criado_por=usuario))
        db.flush()
        return Resultado("", "pendente",
                         f"NF {nf.numero}: {len(candidatas)} notas migradas candidatas, nao "
                         f"escolhida automaticamente ({nums})", nf.chave, nf.numero, tipo)

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
        produto, bloco, avisos = _dados_fiscais_item(db, item, tipo, natureza, uf_contraparte,
                                                      nf.data_emissao)
        pendencias.extend(avisos)
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

    for p in pendencias:
        db.add(Excecao(tipo="importacao_xml", nota_id=nota.id, descricao=p, criado_por=usuario))

    return Resultado("", "pendente" if pendencias else "importada",
                     "; ".join(pendencias) if pendencias else None,
                     nf.chave, nf.numero, tipo, nota.id, produtos)


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

    # Produtos afetados no pacote inteiro, recalculados uma vez so' no final - nao uma vez por
    # nota. Reler o historico inteiro de um produto a cada nota nova dele (um pacote de mes pode
    # trazer dezenas de notas do mesmo produto) e' o que estava estourando os 300s da funcao.
    produtos_afetados: set[int] = set()

    cancelamentos: list[tuple[str, str]] = []
    for nome_arq, dados in arquivos:
        chave_cancelada = evento_cancelamento(dados)
        if chave_cancelada:
            cancelamentos.append((nome_arq, chave_cancelada))
            continue
        outro_evento = evento_outro(dados)
        if outro_evento:
            db.add(ArquivoImportado(lote_id=lote.id, arquivo=nome_arq, situacao="ignorada",
                                    motivo=f"Evento de NF-e que nao e' cancelamento: "
                                          f"{outro_evento} - ignorado"))
            continue
        try:
            nf = ler(dados)
        except XmlInvalido as e:
            db.add(ArquivoImportado(lote_id=lote.id, arquivo=nome_arq, situacao="erro",
                                    motivo=str(e)))
            continue
        r = importar_nota(db, nf, usuario, f"zip:{nome}")
        produtos_afetados.update(r.produtos_afetados)
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
            produtos_afetados.update(i.produto_id for i in nota.itens)
        db.add(ArquivoImportado(lote_id=lote.id, arquivo=nome_arq, situacao="importada",
                                chave_acesso=chave, nota_id=nota.id,
                                motivo="Cancelamento aplicado"))

    db.flush()
    est.recalcular_varios(db, produtos_afetados, usuario)
    db.flush()
    contagem = {}
    for a in db.execute(select(ArquivoImportado)
                        .where(ArquivoImportado.lote_id == lote.id)).scalars():
        contagem[a.situacao] = contagem.get(a.situacao, 0) + 1
    lote.total = sum(contagem.values())
    lote.importadas = contagem.get("importada", 0)
    lote.complementadas = contagem.get("complementada", 0)
    lote.duplicadas = contagem.get("duplicada", 0)
    lote.pendentes = contagem.get("pendente", 0)
    lote.erros = contagem.get("erro", 0) + contagem.get("ignorada", 0)
    db.commit()
    db.refresh(lote)
    return lote
