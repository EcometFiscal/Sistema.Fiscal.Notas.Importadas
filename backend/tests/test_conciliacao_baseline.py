# -*- coding: utf-8 -*-
"""Trava os numeros validados da competencia 07/2026 do modulo de Conciliacao de ICMS.

So' testa os parsers e o motor de conciliacao (services/conciliacao/) - nao toca no banco.
Roda contra os 4 PDFs originais, que NAO ficam neste repositorio (sao documentos fiscais reais
da empresa - ver claude/estado-atual.md). Para rodar localmente, aponte DOCS_2026_07 para uma
pasta com os 4 arquivos e tenha o poppler-utils instalado (`pdftotext` no PATH):

    DOCS_2026_07=/caminho/dos/pdfs python -m pytest backend/tests/test_conciliacao_baseline.py -v

Sem DOCS_2026_07 (ou sem a pasta existir), o modulo inteiro e' pulado - assim o resto da
suite de testes do Lastro continua rodando normalmente em qualquer maquina, sem exigir poppler.
"""
import json
import os
from pathlib import Path

import pytest

from app.services.conciliacao.parsers import (parse_dime_apuracao, parse_dime_cfop,
                                               parse_livro_contab, parse_livro_ecomet,
                                               parse_raicms, pdf_text)
from app.services.conciliacao.reconcile import agrupa_faltantes_por_cfop, compara_cfop, concilia_notas

BASE = json.loads((Path(__file__).parent / 'fixtures' / 'baseline_2026-07.json')
                  .read_text(encoding='utf-8'))
DOCS = Path(os.environ.get('DOCS_2026_07', '')) if os.environ.get('DOCS_2026_07') else None

ARQUIVOS = {
    'contab_livro': 'Livro Entradas.pdf',
    'contab_dime': 'Previa Dime.pdf',
    'ecomet_livro': 'Livro de Entradas SAGI.pdf',
    'ecomet_raicms': 'Livro Fiscal SAGI.pdf',
}

pytestmark = pytest.mark.skipif(
    not DOCS or not DOCS.exists(),
    reason='documentos de 07/2026 nao disponiveis; defina DOCS_2026_07 (ver docstring do arquivo)')


@pytest.fixture(scope='module')
def dados():
    t = {k: pdf_text(DOCS / v) for k, v in ARQUIVOS.items()}
    return dict(
        contab=parse_livro_contab(t['contab_livro']),
        ecomet=parse_livro_ecomet(t['ecomet_livro']),
        dime=parse_dime_cfop(t['contab_dime']),
        apur=parse_dime_apuracao(t['contab_dime']),
        raicms=parse_raicms(t['ecomet_raicms']))


def _quase(a, b):
    assert abs(a - b) < 0.01, f'esperado {b:,.2f}, obtido {a:,.2f}'


def test_totais_dos_documentos(dados):
    """Autoconferencia: cada parser fecha com o total impresso no rodape."""
    esp = BASE['totais_documentos']
    _quase(sum(x['valor_contabil'] for x in dados['contab']), esp['contab_livro_entradas']['valor_contabil'])
    _quase(sum(x['imposto'] for x in dados['contab']), esp['contab_livro_entradas']['imposto'])
    _quase(sum(x['valor_contabil'] for x in dados['dime']['entradas'].values()),
           esp['dime_entradas']['valor_contabil'])
    _quase(sum(x['valor_contabil'] for x in dados['dime']['saidas'].values()),
           esp['dime_saidas']['valor_contabil'])
    _quase(sum(x['valor_contabil'] for x in dados['raicms']['saidas'].values()),
           esp['raicms_saidas']['valor_contabil'])


def test_conciliacao_nota_a_nota(dados):
    r = concilia_notas(dados['contab'], dados['ecomet'])
    esp = BASE['conciliacao_notas']
    assert len(r['casadas']) == esp['casadas']
    assert len(r['cfop_divergente']) == esp['cfop_divergente']
    assert len(r['so_contab']) == esp['so_contabilidade']
    assert len(r['so_ecomet']) == esp['so_ecomet']
    assert len(r['revisar']) == esp['sem_pareamento'], 'nenhum caso deve exigir revisao'


def test_notas_com_cfop_divergente(dados):
    r = concilia_notas(dados['contab'], dados['ecomet'])
    obtido = {a['numero']: (a['cfop'], b['cfop']) for a, b in r['cfop_divergente']}
    for n in BASE['conciliacao_notas']['notas_cfop_divergente']:
        assert obtido[n['numero']] == (n['cfop_contabilidade'], n['cfop_ecomet'])


def test_saidas_sem_divergencia(dados):
    linhas = compara_cfop(dados['dime']['saidas'], dados['raicms']['saidas'])
    assert [l for l in linhas if l['situacao'] != 'OK'] == []


def test_divergencia_interna_da_ecomet(dados):
    """3102 e 3551: Livro de Entradas SAGI concorda com a contabilidade, RAICMS nao."""
    linhas = {l['cfop']: l for l in compara_cfop(
        dados['dime']['entradas'], dados['raicms']['entradas'], dados['ecomet'])}
    for cfop, dif in (('3102', 154312.25), ('3551', 49623.02)):
        l = linhas[cfop]
        _quase(l['livro_ecomet_valor'], l['contab_valor'])
        _quase(l['contab_valor'] - l['ecomet_valor'], dif)


def test_notas_ausentes_por_cfop(dados):
    r = concilia_notas(dados['contab'], dados['ecomet'])
    g = agrupa_faltantes_por_cfop(r['so_contab'])
    for cfop, esp in BASE['notas_ausentes_por_cfop'].items():
        assert g[cfop]['qtd'] == esp['qtd'], f'CFOP {cfop}'
        _quase(g[cfop]['valor'], esp['valor'])


def test_apuracao_fecha_com_a_dime(dados):
    """A apuracao montada pelo modulo tem de bater com o item 998 da Dime."""
    a = dados['apur']
    esp = BASE['apuracao']
    debitos = (a[('04', '010')] + a[('04', '020')] + a[('04', '030')] + a[('04', '060')]
               + a[('09', '036')] + a[('09', '038')])
    ciap = esp['outros_creditos']['ciap']
    creditos = (a[('05', '020')] + ciap + (a[('09', '075')] - ciap) + a[('09', '076')]
                + a[('05', '010')])
    _quase(debitos, esp['total_debitos'])
    _quase(creditos, esp['total_creditos'])
    _quase(creditos - debitos, esp['saldo_credor_mes_seguinte'])


def test_planilha_atual_erraria(dados):
    """Sem as cinco linhas novas, a planilha em uso erra em R$ 232.052,16."""
    a = dados['apur']
    ciap = BASE['apuracao']['outros_creditos']['ciap']
    debitos = a[('04', '010')] + a[('04', '020')] + a[('04', '030')]
    creditos = a[('05', '020')] + ciap + a[('05', '010')]
    _quase(BASE['apuracao']['saldo_credor_mes_seguinte'] - (creditos - debitos), 232052.16)
