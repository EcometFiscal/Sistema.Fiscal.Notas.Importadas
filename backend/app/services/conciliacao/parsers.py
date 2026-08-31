# -*- coding: utf-8 -*-
"""Parsers dos documentos fiscais - Contabilidade x Ecomet.

Portado do pacote de handoff "modulo-conciliacao-icms" (recebido em 31/08/2026) sem alterar a
logica de extracao - ela ja' foi validada nota a nota contra a competencia real de 07/2026
(ver backend/tests/test_conciliacao_baseline.py). So' o empacotamento mudou.

Dependencia externa: o binario `pdftotext` (poppler-utils). Local/desenvolvimento: instale o
poppler-utils (`apt install poppler-utils` / `brew install poppler`). Producao (Vercel): esse
binario NAO esta' disponivel na funcao serverless hoje - a ingestao desta competencia roda por
scripts/importar_conciliacao_icms.py, executado localmente (ou por uma sessao com shell real),
gravando o resultado ja' processado no Postgres. Ver docs/CONTRATO-DE-DADOS.md do pacote
original para o racional completo.
"""
import re
import subprocess

NUM = r'-?\(?-?[\d.]{1,20},\d{2}\)?'


def to_float(s):
    if s is None:
        return 0.0
    s = str(s).strip().replace('(', '-').replace(')', '')
    if s in ('', '-'):
        return 0.0
    neg = s.startswith('-')
    s = s.lstrip('-').replace('.', '').replace(',', '.')
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def pdf_text(path):
    return subprocess.run(['pdftotext', '-layout', str(path), '-'],
                          capture_output=True, text=True, check=True).stdout


def pdf_text_table(path):
    """Como pdf_text, mas com '-table' em vez de '-layout': mantem coluna vazia como espaco em
    branco genuino (nao comprime), essencial para as notas nota-a-nota de parse_livro_contab e
    parse_livro_ecomet - com '-layout' colunas vizinhas vazias fazem valores de outra coluna
    (do bloco de IPI, por ex.) vazarem para dentro da posicao de aliquota/imposto do ICMS."""
    return subprocess.run(['pdftotext', '-table', str(path), '-'],
                          capture_output=True, text=True, check=True).stdout


# ---------------------------------------------------------------- DIME
def parse_dime_cfop(text):
    """Quadros 01 (entradas) e 02 (saidas) da Previa Dime -> {cfop: {...}}"""
    out = {'entradas': {}, 'saidas': {}}
    bloco = None
    for line in text.splitlines():
        s = line.strip()
        if re.match(r'^0?1\s+VALORES FISCAIS ENTRADAS', s):
            bloco = 'entradas'; continue
        if re.match(r'^0?2\s+VALORES FISCAIS SAÍDAS', s):
            bloco = 'saidas'; continue
        if re.match(r'^0?3\s+RESUMO DOS VALORES', s):
            bloco = None; continue
        if not bloco:
            continue
        m = re.match(r'^([1-7]\d{3})\s+(.*)$', s)
        if not m:
            continue
        nums = re.findall(NUM, m.group(2))
        if len(nums) < 5:
            continue
        v = [to_float(n) for n in nums]
        cfop = m.group(1)
        if bloco == 'entradas':
            d = dict(valor_contabil=v[0], base_calculo=v[1], imposto=v[2],
                     isentas=v[3], outras=v[4], difal=v[7] if len(v) > 7 else 0.0)
        else:
            d = dict(valor_contabil=v[0], base_calculo=v[1], imposto=v[2],
                     isentas=v[3], outras=v[4], difal=0.0)
        out[bloco][cfop] = d
    return out


def parse_dime_apuracao(text):
    """Quadros 04/05/09 da Dime -> {(quadro,item): valor}"""
    out, quadro = {}, None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r'^(0?4|0?5|09|14)\s+(Resumo da Apuração|CÁLCULO DO IMPOSTO|Demonstrativo)', s)
        if m:
            quadro = m.group(1).zfill(2); continue
        if not quadro:
            continue
        m = re.match(r'^(\d{3})\s+(.*?)\s+(' + NUM + r')$', s)
        if m:
            out[(quadro, m.group(1))] = to_float(m.group(3))
    return out


# ---------------------------------------------------------------- RAICMS (Ecomet)
def parse_raicms(text):
    """Livro Fiscal SAGI (RAICMS P9) -> cfops + resumo da apuracao."""
    out = {'entradas': {}, 'saidas': {}, 'resumo': {}}
    bloco = None
    for line in text.splitlines():
        s = line.strip()
        if s == 'ENTRADAS':
            bloco = 'entradas'; continue
        if s == 'SAÍDAS':
            bloco = 'saidas'; continue
        if 'SUBTOTAIS' in s:
            bloco = None; continue
        if 'RESUMO DA APURAÇÃO' in s:
            bloco = 'resumo'; continue
        if bloco in ('entradas', 'saidas'):
            m = re.match(r'^([1-7]\d{3})\s+(.*)$', s)
            if not m:
                continue
            nums = re.findall(NUM, m.group(2))
            if len(nums) < 5:
                continue
            v = [to_float(n) for n in nums]
            out[bloco][m.group(1)] = dict(valor_contabil=v[0], base_calculo=v[1],
                                          imposto=v[2], isentas=v[3], outras=v[4], difal=0.0)
        elif bloco == 'resumo':
            m = re.match(r'^(\d{3})\s+(.*?)\s+(' + NUM + r')\s+(' + NUM + r')$', s)
            if m:
                out['resumo'][m.group(1)] = to_float(m.group(4))
    return out


# ---------------------------------------------------------------- Livro de Entradas (nota a nota)
# Le' a saida de pdf_text_table (nao pdf_text/-layout): so' ela preserva coluna vazia como
# espaco em branco, sem a qual nao da' pra saber se um numero pertence ao bloco ICMS (cod/base/
# aliq/imposto) ou ao bloco IPI logo depois - ver nota em pdf_text_table.
#
# cod/base/aliq/imposto do bloco ICMS: aliq+imposto so' aparecem quando cod_fiscal='1' (operacao
# com credito - unico caso que apura imposto); cod_fiscal 2/3 (isenta/outras) nunca tem, entao o
# grupo 13 (aliq+imposto) e' opcional e so' e' interpretado quando cod_fiscal='1'. O que vem depois
# (bloco IPI - cod/base/imposto de IPI) e' ignorado, nao faz parte do modelo.
RE_CONTAB = re.compile(
    r'^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(\d{1,4})\s+(\d{1,9})\s+(\d{2}/\d{2}/\d{4})\s+'
    r'(\S+)\s+([A-Z]{2})\s+(' + NUM + r')\s+(\d)-(\d{3})'
    r'(?:\s+(\d)\s+(' + NUM + r')(?:\s+(' + NUM + r')\s+(' + NUM + r'))?.*)?$')


def parse_livro_contab(text):
    """Livro Registro de Entradas da contabilidade -> lista de lancamentos.
    `text` deve vir de pdf_text_table (nao pdf_text/-layout)."""
    rows, ultimo = [], None
    for line in text.splitlines():
        m = RE_CONTAB.match(line.strip())
        if m:
            cod_fiscal = m.group(11) or '0'
            aliq = to_float(m.group(13)) if cod_fiscal == '1' and m.group(13) else 0.0
            imposto = to_float(m.group(14)) if cod_fiscal == '1' and m.group(14) else 0.0
            ultimo = dict(data_entrada=m.group(1), especie=m.group(2).strip(),
                          serie=m.group(3), numero=m.group(4).lstrip('0') or '0',
                          data_doc=m.group(5), cod_emitente=m.group(6), uf=m.group(7),
                          valor_contabil=to_float(m.group(8)),
                          cfop=m.group(9) + m.group(10), cod_fiscal=cod_fiscal,
                          base_calculo=to_float(m.group(12)) if m.group(12) else 0.0,
                          aliquota=aliq, imposto=imposto, difal_base=0.0, difal=0.0)
            rows.append(ultimo)
            continue
        s = line.strip()
        m4 = re.match(r'^4\s+(' + NUM + r')\s+(' + NUM + r')\s*$', s)
        if m4 and ultimo is not None:
            ultimo['difal_base'] = to_float(m4.group(1))
            ultimo['difal'] = to_float(m4.group(2))
    return rows


# Le' a saida de pdf_text_table (nao pdf_text/-layout). No layout real cada nota ocupa a linha
# principal (data...CFOP) seguida de "ICMS" e cod/base/aliq/imposto do proprio bloco ICMS, tudo
# na MESMA linha - a linha de continuacao logo abaixo e' o bloco IPI (irrelevante aqui, ignorado).
RE_ECOMET_MAIN = re.compile(
    r'^(\d{2}/\d{2}/\d{4})\s+(\d{2,3})\s+(\d{1,4})\s+(\d{1,9})\s+(\d{2}/\d{2}/\d{4})\s+'
    r'(\d{11,14})\s+([A-Z]{2})\s+(' + NUM + r')\s+([1-7]\d{3})\s+ICMS\s+(\d)\s+'
    r'(' + NUM + r')\s+(\d+(?:,\d+)?)\s+(' + NUM + r')\s*$')


def parse_livro_ecomet(text):
    """Livro Registro de Entradas do SAGI/Ecomet -> lista de lancamentos.
    `text` deve vir de pdf_text_table (nao pdf_text/-layout)."""
    rows = []
    for line in text.splitlines():
        m = RE_ECOMET_MAIN.match(line.strip())
        if not m:
            continue
        rows.append(dict(
            data_entrada=m.group(1), especie=m.group(2), serie=m.group(3),
            numero=m.group(4).lstrip('0') or '0', data_doc=m.group(5),
            cnpj=m.group(6), uf=m.group(7), valor_contabil=to_float(m.group(8)),
            cfop=m.group(9), cod_fiscal=m.group(10), base_calculo=to_float(m.group(11)),
            aliquota=to_float(m.group(12)), imposto=to_float(m.group(13))))
    return rows
