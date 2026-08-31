# -*- coding: utf-8 -*-
"""Ingestao da conciliacao de ICMS: liga os parsers/reconcile ao banco do Lastro.

Fase 1 do modulo (ver claude/estado-atual.md). Roda hoje como script local
(backend/scripts/importar_conciliacao_icms.py), nao como rota da API: os quatro documentos
sao PDF e o parser depende do binario `pdftotext` (poppler-utils), que nao esta' disponivel na
funcao serverless da Vercel. As telas de conciliacao (fase 2+) leem o que este modulo grava
aqui - o upload direto do PDF pela tela web fica para quando essa dependencia for resolvida
(rodar um binario estatico junto da funcao, ou expor esta ingestao como um servico a parte).

Autoconferencia (documento_fonte.conferido): por enquanto so' registra se o parser conseguiu
ler o arquivo e encontrou pelo menos um lancamento - a comparacao com o total impresso no
rodape' de cada PDF (o que a especificacao original do pacote chama de autoconferencia forte)
ainda nao esta' implementada nos parsers portados; total_documento fica nulo ate' isso ser
feito. Nao trave a ingestao por causa disso, so' deixe o campo honesto.
"""
import datetime as dt
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ...models import (ConcApuracaoLinha, ConcDivergencia, ConcDocumentoFonte,
                       ConcLancamentoEntrada, ConcPeriodo, ConcSaldoCfop)
from .parsers import (parse_dime_apuracao, parse_dime_cfop, parse_livro_contab,
                      parse_livro_ecomet, parse_raicms, pdf_text)
from .reconcile import agrupa_faltantes_por_cfop, compara_cfop, concilia_notas

ROTULOS_APURACAO = {
    ('outros_debitos', 1): ('DIFAL — diferencial de alíquota', 'Entradas Difal / Dime 04/020 e 04/030'),
    ('outros_debitos', 2): ('Outros estornos de crédito', 'Dime 04/060'),
    ('outros_debitos', 3): ('Estorno de crédito presumido — sub-apuração TTD', 'Dime 09/036'),
    ('outros_debitos', 4): ('Estorno de ICMS s/ devolução — sub-apuração TTD', 'Dime 09/038'),
    ('outros_creditos', 1): ('CIAP', 'CIAP ICMS — crédito a ser apropriado no mês'),
    ('outros_creditos', 2): ('Crédito presumido TTD 409 (DCIP)', 'Dime 09/075 menos o CIAP'),
    ('outros_creditos', 3): ('Segregação dos débitos de saídas com crédito presumido', 'Dime 09/076'),
    ('outros_creditos', 4): ('Energia', 'Preenchimento manual'),
    ('outros_creditos', 5): ('Embalagens', 'Preenchimento manual'),
}


def _data(s):
    """dd/mm/aaaa -> date, ou None."""
    try:
        return dt.datetime.strptime(s, '%d/%m/%Y').date()
    except (TypeError, ValueError):
        return None


def _documento(db, periodo_id, tipo, origem, caminho, linhas):
    doc = ConcDocumentoFonte(
        periodo_id=periodo_id, tipo=tipo, origem=origem, nome_original=Path(caminho).name,
        total_extraido=round(sum(r.get('valor_contabil', 0.0) for r in linhas), 2),
        conferido=bool(linhas), lido_em=dt.datetime.utcnow())
    db.add(doc)
    db.flush()
    return doc


def importar_periodo(db: Session, competencia: str, *, contab_livro: str, contab_dime: str,
                     ecomet_livro: str, ecomet_raicms: str, ciap: float = 0.0,
                     inscricao_estadual: str = "260070009") -> ConcPeriodo:
    """Le' os quatro PDFs de uma competencia, concilia e grava tudo no banco.

    Reimportar a mesma competencia apaga e regrava os documentos/lancamentos/saldos/divergencias
    dela (o periodo em si e' preservado, junto com fechamento e justificativas ja' dadas) -
    assim corrigir um PDF errado e' so' rodar de novo.
    """
    contab = parse_livro_contab(pdf_text(contab_livro))
    ecomet = parse_livro_ecomet(pdf_text(ecomet_livro))
    dime_txt = pdf_text(contab_dime)
    dime, apur = parse_dime_cfop(dime_txt), parse_dime_apuracao(dime_txt)
    raicms = parse_raicms(pdf_text(ecomet_raicms))

    periodo = db.query(ConcPeriodo).filter_by(
        competencia=competencia, inscricao_estadual=inscricao_estadual).one_or_none()
    if periodo is None:
        periodo = ConcPeriodo(competencia=competencia, inscricao_estadual=inscricao_estadual)
        db.add(periodo)
        db.flush()
    else:
        for modelo in (ConcDivergencia, ConcSaldoCfop, ConcLancamentoEntrada, ConcDocumentoFonte,
                       ConcApuracaoLinha):
            db.execute(delete(modelo).where(modelo.periodo_id == periodo.id))
        db.flush()

    g = lambda q, i: apur.get((q, i), 0.0)
    periodo.saldo_credor_anterior = g('05', '010')

    doc_contab = _documento(db, periodo.id, 'livro_entradas', 'contabilidade', contab_livro, contab)
    doc_ecomet = _documento(db, periodo.id, 'livro_entradas', 'ecomet', ecomet_livro, ecomet)
    doc_dime = _documento(db, periodo.id, 'dime', 'contabilidade', contab_dime,
                          list(dime['entradas'].values()) + list(dime['saidas'].values()))
    doc_raicms = _documento(db, periodo.id, 'raicms', 'ecomet', ecomet_raicms,
                            list(raicms['entradas'].values()) + list(raicms['saidas'].values()))

    for origem, doc, linhas in (('contabilidade', doc_contab, contab), ('ecomet', doc_ecomet, ecomet)):
        for r in linhas:
            db.add(ConcLancamentoEntrada(
                periodo_id=periodo.id, documento_id=doc.id, origem=origem,
                data_entrada=_data(r.get('data_entrada')), data_documento=_data(r.get('data_doc')),
                especie=r.get('especie'), serie=r.get('serie'), numero=r['numero'],
                emitente_codigo=r.get('cod_emitente'), emitente_cnpj=r.get('cnpj'), uf=r.get('uf'),
                valor_contabil=r.get('valor_contabil', 0.0), cfop=r.get('cfop'),
                cod_fiscal=r.get('cod_fiscal') or None, base_calculo=r.get('base_calculo', 0.0),
                aliquota=r.get('aliquota', 0.0), imposto=r.get('imposto', 0.0),
                difal=r.get('difal', 0.0)))

    for fonte, tipo, d in (('dime', 'entrada', dime['entradas']), ('dime', 'saida', dime['saidas']),
                           ('raicms', 'entrada', raicms['entradas']), ('raicms', 'saida', raicms['saidas'])):
        for cfop, v in d.items():
            db.add(ConcSaldoCfop(periodo_id=periodo.id, fonte=fonte, tipo=tipo, cfop=cfop, **v))

    livro_agg = defaultdict(float)
    for r in ecomet:
        livro_agg[r['cfop']] += r['valor_contabil']
    for cfop, valor in livro_agg.items():
        db.add(ConcSaldoCfop(periodo_id=periodo.id, fonte='livro_ecomet', tipo='entrada', cfop=cfop,
                             valor_contabil=round(valor, 2)))

    res = concilia_notas(contab, ecomet)
    cfop_ent = compara_cfop(dime['entradas'], raicms['entradas'], ecomet)
    cfop_sai = compara_cfop(dime['saidas'], raicms['saidas'])
    falt = agrupa_faltantes_por_cfop(res['so_contab'])

    for a, b in res['cfop_divergente']:
        db.add(ConcDivergencia(
            periodo_id=periodo.id, tipo='cfop_nota', severidade='alto',
            cfop=a['cfop'], numero_nota=a['numero'],
            descricao=(f"NF {a['numero']} está como CFOP {a['cfop']} na contabilidade e "
                       f"{b['cfop']} no Ecomet"),
            valor_contabilidade=a['valor_contabil'], valor_ecomet=b['valor_contabil'],
            diferenca=round(a['valor_contabil'] - b['valor_contabil'], 2)))

    for linhas, rotulo_situacao in ((cfop_ent, 'entrada'), (cfop_sai, 'saida')):
        for l in linhas:
            if l['situacao'] == 'Divergente':
                db.add(ConcDivergencia(
                    periodo_id=periodo.id, tipo='cfop_saldo', severidade='alto', cfop=l['cfop'],
                    descricao=f"CFOP {l['cfop']} ({rotulo_situacao}): saldo divergente entre Dime e RAICMS",
                    valor_contabilidade=l['contab_valor'], valor_ecomet=l['ecomet_valor'],
                    diferenca=l['dif_valor']))
            if (l.get('livro_ecomet_valor') is not None
                    and abs(l['livro_ecomet_valor'] - l['ecomet_valor']) > 0.01):
                db.add(ConcDivergencia(
                    periodo_id=periodo.id, tipo='coerencia_interna_ecomet', severidade='alto',
                    cfop=l['cfop'],
                    descricao=(f"CFOP {l['cfop']}: Livro de Entradas do Ecomet mostra "
                              f"{l['livro_ecomet_valor']:.2f} e o RAICMS mostra {l['ecomet_valor']:.2f} "
                              "— divergência interna do próprio Ecomet"),
                    valor_contabilidade=l['livro_ecomet_valor'], valor_ecomet=l['ecomet_valor'],
                    diferenca=round(l['livro_ecomet_valor'] - l['ecomet_valor'], 2)))

    for cfop, dados in falt.items():
        db.add(ConcDivergencia(
            periodo_id=periodo.id, tipo='nota_ausente_ecomet', severidade='revisar', cfop=cfop,
            descricao=(f"{dados['qtd']} nota(s) de CFOP {cfop} lançadas pela contabilidade e "
                      "ausentes no Ecomet — provavelmente uso/consumo ou insumo"),
            valor_contabilidade=round(dados['valor'], 2)))

    for num, lc, le in res['revisar']:
        db.add(ConcDivergencia(
            periodo_id=periodo.id, tipo='pareamento_manual', severidade='revisar', numero_nota=num,
            descricao=(f"NF {num}: {len(lc)} lançamento(s) na contabilidade e {len(le)} no Ecomet "
                      "não casam automaticamente por número + valor")))

    sc_ec, sc_ct = raicms['resumo'].get('009', 0.0), periodo.saldo_credor_anterior or 0.0
    if abs(sc_ec - sc_ct) > 0.01:
        db.add(ConcDivergencia(
            periodo_id=periodo.id, tipo='saldo_credor_anterior', severidade='alto',
            descricao='Saldo credor do período anterior diverge entre RAICMS 009 e Dime 05/010',
            valor_contabilidade=sc_ct, valor_ecomet=sc_ec, diferenca=round(sc_ct - sc_ec, 2)))

    debito_saidas = g('04', '010')
    credito_entradas = g('05', '020')
    outros_debitos = [
        ('DIFAL — diferencial de alíquota', g('04', '020') + g('04', '030')),
        ('Outros estornos de crédito', g('04', '060')),
        ('Estorno de crédito presumido — sub-apuração TTD', g('09', '036')),
        ('Estorno de ICMS s/ devolução — sub-apuração TTD', g('09', '038')),
    ]
    outros_creditos = [
        ('CIAP', ciap),
        ('Crédito presumido TTD 409 (DCIP)', g('09', '075') - ciap),
        ('Segregação dos débitos de saídas com crédito presumido', g('09', '076')),
        ('Energia', 0.0),
        ('Embalagens', 0.0),
    ]
    db.add(ConcApuracaoLinha(periodo_id=periodo.id, grupo='debito', ordem=1,
                             rotulo='Débito do ICMS nas saídas', valor=debito_saidas,
                             origem_texto='Dime 04/010'))
    for i, (rotulo, valor) in enumerate(outros_debitos, start=1):
        db.add(ConcApuracaoLinha(periodo_id=periodo.id, grupo='outros_debitos', ordem=i,
                                 rotulo=rotulo, valor=valor,
                                 origem_texto=ROTULOS_APURACAO[('outros_debitos', i)][1]))
    db.add(ConcApuracaoLinha(periodo_id=periodo.id, grupo='credito', ordem=1,
                             rotulo='Crédito do ICMS nas entradas', valor=credito_entradas,
                             origem_texto='Dime 05/020'))
    for i, (rotulo, valor) in enumerate(outros_creditos, start=1):
        db.add(ConcApuracaoLinha(periodo_id=periodo.id, grupo='outros_creditos', ordem=i,
                                 rotulo=rotulo, valor=valor,
                                 origem_texto=ROTULOS_APURACAO[('outros_creditos', i)][1],
                                 editavel=(rotulo in ('Energia', 'Embalagens'))))
    db.add(ConcApuracaoLinha(periodo_id=periodo.id, grupo='credito', ordem=2,
                             rotulo='Saldo credor do período anterior', valor=periodo.saldo_credor_anterior or 0.0,
                             origem_texto='Dime 05/010'))

    total_debitos = debito_saidas + sum(v for _, v in outros_debitos)
    total_creditos = credito_entradas + sum(v for _, v in outros_creditos) + (periodo.saldo_credor_anterior or 0.0)
    db.add(ConcApuracaoLinha(periodo_id=periodo.id, grupo='saldo', ordem=1,
                             rotulo='Saldo credor para o mês seguinte',
                             valor=round(total_creditos - total_debitos, 2),
                             origem_texto='Dime 09/998 (referência oficial)'))

    db.commit()
    db.refresh(periodo)
    return periodo
