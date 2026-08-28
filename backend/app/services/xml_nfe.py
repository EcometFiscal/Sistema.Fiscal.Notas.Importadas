"""Leitor de NF-e 4.00.

O XML e' o documento; o DANFE e' o desenho dele. Aqui so' se le' XML: base de calculo, CST,
aliquota, NCM e origem estao em campos nomeados, nao em posicao visual.

Aceita <nfeProc> (com protocolo) e <NFe> solto, e tambem o <procEventoNFe> de cancelamento.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET


def _tag(elem) -> str:
    return elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag


def _acha(pai, *caminho):
    """Busca por nome local, ignorando namespace - o XML da NF-e vem com e sem prefixo."""
    atual = pai
    for nome in caminho:
        achou = None
        for filho in list(atual):
            if _tag(filho) == nome:
                achou = filho
                break
        if achou is None:
            return None
        atual = achou
    return atual


def _txt(pai, *caminho):
    e = _acha(pai, *caminho)
    return e.text.strip() if e is not None and e.text else None


def _num(pai, *caminho):
    v = _txt(pai, *caminho)
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _primeiro(pai, nomes: tuple[str, ...]):
    for filho in list(pai):
        if _tag(filho) in nomes:
            return filho
    return None


class XmlInvalido(Exception):
    pass


@dataclass
class ItemNFe:
    numero: int
    codigo: str | None
    descricao: str
    ncm: str | None
    cfop: str | None
    unidade: str | None
    quantidade: float
    valor: float
    origem: str | None          # 0..8 da tabela da NF-e
    cst: str | None
    base_calculo: float | None
    aliquota: float | None      # fracao (0.04, 0.12)
    valor_icms: float | None


@dataclass
class NotaFiscal:
    chave: str
    numero: int
    serie: str
    modelo: str
    natureza: str | None
    finalidade: str | None      # 1 normal, 2 complementar, 3 ajuste, 4 devolucao
    tipo_nf: str                # 0 entrada, 1 saida (do ponto de vista do emitente)
    data_emissao: dt.date
    emit_cnpj: str | None
    emit_nome: str | None
    emit_uf: str | None
    dest_cnpj: str | None
    dest_nome: str | None
    dest_uf: str | None
    dest_exterior: bool
    valor_total: float | None
    situacao: str | None        # cStat do protocolo
    refs: list[str] = field(default_factory=list)   # chaves de NFref (ide/NFref/refNFe)
    itens: list[ItemNFe] = field(default_factory=list)
    cancelada: bool = False

    @property
    def cfop_principal(self) -> str | None:
        return self.itens[0].cfop if self.itens else None


GRUPOS_ICMS = ("ICMS00", "ICMS10", "ICMS20", "ICMS30", "ICMS40", "ICMS41", "ICMS50", "ICMS51",
               "ICMS60", "ICMS70", "ICMS90", "ICMSPart", "ICMSST", "ICMSSN101", "ICMSSN102",
               "ICMSSN201", "ICMSSN202", "ICMSSN500", "ICMSSN900")


def _data(texto: str | None) -> dt.date | None:
    if not texto:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", texto)
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _refs(ide) -> list[str]:
    """Chaves das NF-e referenciadas em ide/NFref/refNFe. Pode haver mais de um grupo NFref;
    ignoramos referencia a outro tipo de documento (refNF, refNFP, refCTe, refECF) - so' importa
    quando a nota referenciada e' outra NF-e."""
    refs = []
    for filho in list(ide):
        if _tag(filho) == "NFref":
            chave_ref = _txt(filho, "refNFe")
            if chave_ref:
                refs.append(chave_ref)
    return refs


def ler(conteudo: bytes | str) -> NotaFiscal:
    try:
        raiz = ET.fromstring(conteudo if isinstance(conteudo, bytes) else conteudo.encode())
    except ET.ParseError as e:
        raise XmlInvalido(f"XML ilegivel: {e}") from e

    if _tag(raiz) == "nfeProc":
        nfe = _acha(raiz, "NFe")
        prot = _acha(raiz, "protNFe", "infProt")
    elif _tag(raiz) == "NFe":
        nfe, prot = raiz, None
    else:
        raise XmlInvalido(f"Raiz inesperada: {_tag(raiz)}. Esperado nfeProc ou NFe.")
    if nfe is None:
        raise XmlInvalido("XML sem elemento NFe")

    inf = _acha(nfe, "infNFe")
    if inf is None:
        raise XmlInvalido("XML sem infNFe")
    chave = (inf.get("Id") or "").replace("NFe", "")
    if len(chave) != 44 or not chave.isdigit():
        chave = _txt(prot, "chNFe") if prot is not None else ""
    if len(chave) != 44:
        raise XmlInvalido("Nao foi possivel ler a chave de acesso de 44 digitos")

    ide = _acha(inf, "ide")
    emit, dest = _acha(inf, "emit"), _acha(inf, "dest")
    data = _data(_txt(ide, "dhEmi") or _txt(ide, "dEmi"))
    if data is None:
        raise XmlInvalido("XML sem data de emissao")

    itens: list[ItemNFe] = []
    for det in [d for d in list(inf) if _tag(d) == "det"]:
        prod = _acha(det, "prod")
        if prod is None:
            continue
        icms_grupo = None
        icms = _acha(det, "imposto", "ICMS")
        if icms is not None:
            icms_grupo = _primeiro(icms, GRUPOS_ICMS)
        pic = _num(icms_grupo, "pICMS") if icms_grupo is not None else None
        itens.append(ItemNFe(
            numero=int(det.get("nItem") or len(itens) + 1),
            codigo=_txt(prod, "cProd"),
            descricao=(_txt(prod, "xProd") or "").strip(),
            ncm=_txt(prod, "NCM"),
            cfop=_txt(prod, "CFOP"),
            unidade=_txt(prod, "uCom"),
            quantidade=_num(prod, "qCom") or 0.0,
            valor=_num(prod, "vProd") or 0.0,
            origem=_txt(icms_grupo, "orig") if icms_grupo is not None else None,
            cst=((_txt(icms_grupo, "CST") or _txt(icms_grupo, "CSOSN"))
                 if icms_grupo is not None else None),
            base_calculo=_num(icms_grupo, "vBC") if icms_grupo is not None else None,
            aliquota=(pic / 100) if pic is not None else None,
            valor_icms=_num(icms_grupo, "vICMS") if icms_grupo is not None else None,
        ))
    if not itens:
        raise XmlInvalido("NF-e sem itens")

    dest_ext = dest is not None and _acha(dest, "idEstrangeiro") is not None
    return NotaFiscal(
        chave=chave,
        numero=int(_txt(ide, "nNF") or 0),
        serie=_txt(ide, "serie") or "1",
        modelo=_txt(ide, "mod") or "55",
        natureza=_txt(ide, "natOp"),
        finalidade=_txt(ide, "finNFe"),
        tipo_nf=_txt(ide, "tpNF") or "1",
        data_emissao=data,
        emit_cnpj=_txt(emit, "CNPJ") if emit is not None else None,
        emit_nome=_txt(emit, "xNome") if emit is not None else None,
        emit_uf=_txt(emit, "enderEmit", "UF") if emit is not None else None,
        dest_cnpj=(_txt(dest, "CNPJ") or _txt(dest, "CPF")) if dest is not None else None,
        dest_nome=_txt(dest, "xNome") if dest is not None else None,
        dest_uf=_txt(dest, "enderDest", "UF") if dest is not None else None,
        dest_exterior=dest_ext,
        valor_total=_num(inf, "total", "ICMSTot", "vNF"),
        situacao=_txt(prot, "cStat") if prot is not None else None,
        refs=_refs(ide),
        itens=itens,
    )


EVENTO_TAGS = ("proceventonfe", "evento", "retevento")


def _raiz_de_evento(conteudo: bytes | str) -> ET.Element | None:
    """A raiz do XML de evento, se o arquivo for um (cancelamento, carta de correcao, etc).
    Comparacao de tag em minusculas: pacotes reais chegam ora com "procEventoNFe", ora com
    "ProcEventoNFe" - maiuscula errada nao pode fazer um cancelamento passar batido como erro
    de leitura."""
    try:
        raiz = ET.fromstring(conteudo if isinstance(conteudo, bytes) else conteudo.encode())
    except ET.ParseError:
        return None
    return raiz if _tag(raiz).lower() in EVENTO_TAGS else None


def evento_cancelamento(conteudo: bytes | str) -> str | None:
    """Se o arquivo for um evento de cancelamento autorizado (tpEvento 110111), devolve a
    chave cancelada."""
    raiz = _raiz_de_evento(conteudo)
    if raiz is None:
        return None
    for elem in raiz.iter():
        if _tag(elem) == "tpEvento" and (elem.text or "").strip() == "110111":
            for e2 in raiz.iter():
                if _tag(e2) == "chNFe" and e2.text:
                    return e2.text.strip()
    return None


def evento_outro(conteudo: bytes | str) -> str | None:
    """Se o arquivo for um evento de NF-e que nao e' cancelamento (Carta de Correcao, EPEC,
    etc.), devolve uma descricao curta pra virar pendencia informativa em vez de erro de
    leitura - o pacote real de julho/2026 trouxe uma Carta de Correcao (tpEvento 110110) que
    sem isto aparecia como "Raiz inesperada"."""
    raiz = _raiz_de_evento(conteudo)
    if raiz is None:
        return None
    tp = desc = None
    for elem in raiz.iter():
        if _tag(elem) == "tpEvento":
            tp = (elem.text or "").strip()
        if _tag(elem) == "descEvento":
            desc = (elem.text or "").strip()
    if tp == "110111":
        return None                                   # cancelamento - ja' tratado a parte
    return f"{desc or 'evento'} (tpEvento {tp or '?'})"
