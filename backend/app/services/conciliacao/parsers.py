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
RE_CONTAB = re.compile(
    r'^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(\d{1,4})\s+(\d{1,9})\s+(\d{2}/\d{2}/\d{4})\s+'
    r'(\S+)\s+([A-Z]{2})\s+(' + NUM + r')\s+(\d)-(\d{3})\s+(\d)\s+(' + NUM + r')(.*)$')


def parse_livro_contab(text):
    """Livro Registro de Entradas da contabilidade -> lista de lancamentos."""
    rows, ultimo = [], None
    for line in text.splitlines():
        m = RE_CONTAB.match(line.strip())
        if m:
            resto = re.findall(NUM, m.group(13))
            aliq = to_float(resto[0]) if len(resto) >= 2 else 0.0
            imposto = to_float(resto[1]) if len(resto) >= 2 else 0.0
            ultimo = dict(data_entrada=m.group(1), especie=m.group(2).strip(),
                          serie=m.group(3), numero=m.group(4).lstrip('0') or '0',
                          data_doc=m.group(5), cod_emitente=m.group(6), uf=m.group(7),
                          valor_contabil=to_float(m.group(8)),
                          cfop=m.group(9) + m.group(10), cod_fiscal=m.group(11),
                          base_calculo=to_float(m.group(12)), aliquota=aliq,
                          imposto=imposto, difal_base=0.0, difal=0.0)
            rows.append(ultimo)
            continue
        s = line.strip()
        m4 = re.match(r'^4\s+(' + NUM + r')\s+(' + NUM + r')\s*$', s)
        if m4 and ultimo is not None:
            ultimo['difal_base'] = to_float(m4.group(1))
            ultimo['difal'] = to_float(m4.group(2))
    return rows


RE_ECOMET_MAIN = re.compile(
    r'^(\d{2}/\d{2}/\d{4})\s+(\d{2,3})\s+(\d{1,4})\s+(\d{1,9})\s+(\d{2}/\d{2}/\d{4})\s+'
    r'(\d{11,14})\s+([A-Z]{2})\s+(' + NUM + r')\s+([1-7]\d{3})\s*$')
RE_ECOMET_ICMS = re.compile(
    r'^ICMS\s+(\d)\s+(' + NUM + r')\s+(\d+(?:,\d+)?)\s+(' + NUM + r')\s*$')


def parse_livro_ecomet(text):
    """Livro Registro de Entradas do SAGI/Ecomet -> lista de lancamentos."""
    rows, pend = [], None
    for line in text.splitlines():
        s = line.strip()
        mi = RE_ECOMET_ICMS.match(s)
        if mi:
            pend = dict(cod_fiscal=mi.group(1), base_calculo=to_float(mi.group(2)),
                        aliquota=to_float(mi.group(3).replace(',', ',')),
                        imposto=to_float(mi.group(4)))
            continue
        mm = RE_ECOMET_MAIN.match(s)
        if mm:
            r = dict(data_entrada=mm.group(1), especie=mm.group(2), serie=mm.group(3),
                     numero=mm.group(4).lstrip('0') or '0', data_doc=mm.group(5),
                     cnpj=mm.group(6), uf=mm.group(7),
                     valor_contabil=to_float(mm.group(8)), cfop=mm.group(9),
                     cod_fiscal='', base_calculo=0.0, aliquota=0.0, imposto=0.0)
            if pend:
                r.update(pend); pend = None
            rows.append(r)
    return rows
