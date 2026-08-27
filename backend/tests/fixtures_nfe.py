"""Gerador de NF-e 4.00 para teste. Segue o layout real: mesmos nomes de campo e mesma
hierarquia que a SEFAZ devolve, para o parser ser exercitado como sera' em producao."""
from __future__ import annotations

import datetime as dt

CNPJ_EMPRESA = "12345678000199"


def chave(numero: int, cnpj: str = CNPJ_EMPRESA, serie: int = 1, ano_mes: str = "2608") -> str:
    base = f"42{ano_mes}{cnpj}55{serie:03d}{numero:09d}1{numero:08d}"
    return (base + "0" * 44)[:43] + "0"


def nfe(numero: int, *, tipo_nf="1", cfop="5101", aliquota=4.0, origem="1",
        emit_cnpj=CNPJ_EMPRESA, emit_uf="SC", dest_cnpj="98765432000188",
        dest_nome="ALUNOVA REFUSAO LTDA", dest_uf="SP", produto="SUCATA DE ALUMINIO",
        ncm="76020000", quantidade=1000.0, valor=20000.0, data=None, fin="1",
        cstat="100", com_protocolo=True, chave_custom=None, cst="00") -> str:
    data = data or dt.date(2026, 8, 10)
    ch = chave_custom or chave(numero, emit_cnpj)
    vicms = round(valor * aliquota / 100, 2)
    prot = (f'<protNFe versao="4.00"><infProt><chNFe>{ch}</chNFe><cStat>{cstat}</cStat>'
            f'<xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe>'
            if com_protocolo else "")
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
 <NFe><infNFe Id="NFe{ch}" versao="4.00">
  <ide><cUF>42</cUF><natOp>VENDA DE MERCADORIA</natOp><mod>55</mod><serie>1</serie>
   <nNF>{numero}</nNF><dhEmi>{data.isoformat()}T10:15:00-03:00</dhEmi>
   <tpNF>{tipo_nf}</tpNF><idDest>2</idDest><finNFe>{fin}</finNFe></ide>
  <emit><CNPJ>{emit_cnpj}</CNPJ><xNome>MINHA EMPRESA LTDA</xNome>
   <enderEmit><UF>{emit_uf}</UF></enderEmit></emit>
  <dest><CNPJ>{dest_cnpj}</CNPJ><xNome>{dest_nome}</xNome>
   <enderDest><UF>{dest_uf}</UF></enderDest></dest>
  <det nItem="1">
   <prod><cProd>001</cProd><xProd>{produto}</xProd><NCM>{ncm}</NCM><CFOP>{cfop}</CFOP>
    <uCom>KG</uCom><qCom>{quantidade:.4f}</qCom><vUnCom>{valor/quantidade:.6f}</vUnCom>
    <vProd>{valor:.2f}</vProd></prod>
   <imposto><ICMS><ICMS00><orig>{origem}</orig><CST>{cst}</CST><modBC>3</modBC>
    <vBC>{valor:.2f}</vBC><pICMS>{aliquota:.2f}</pICMS><vICMS>{vicms:.2f}</vICMS>
   </ICMS00></ICMS></imposto></det>
  <total><ICMSTot><vNF>{valor:.2f}</vNF></ICMSTot></total>
 </infNFe></NFe>
 {prot}
</nfeProc>'''


def evento_cancelamento(ch: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
 <evento versao="1.00"><infEvento Id="ID110111{ch}01">
  <cOrgao>42</cOrgao><tpAmb>1</tpAmb><CNPJ>{CNPJ_EMPRESA}</CNPJ><chNFe>{ch}</chNFe>
  <tpEvento>110111</tpEvento><detEvento versao="1.00"><descEvento>Cancelamento</descEvento>
   <xJust>Erro de digitacao</xJust></detEvento></infEvento></evento>
 <retEvento versao="1.00"><infEvento><cStat>135</cStat><chNFe>{ch}</chNFe></infEvento></retEvento>
</procEventoNFe>'''


def pacote(arquivos: dict[str, str]) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    return buf.getvalue()
