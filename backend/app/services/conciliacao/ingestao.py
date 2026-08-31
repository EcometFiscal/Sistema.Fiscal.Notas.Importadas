# -*- coding: utf-8 -*-
"""Ingestao da conciliacao de ICMS: liga os parsers/reconcile ao banco do Lastro.

Roda hoje como script local (backend/scripts/importar_conciliacao_icms.py), nao como rota da
API: os documentos sao PDF e o parser depende do binario `pdftotext` (poppler-utils), que nao
esta' disponivel na funcao serverless da Vercel. As telas de conciliacao leem o que este modulo
grava aqui - o upload direto do PDF pela tela web fica para quando essa dependencia for
resolvida (rodar um binario estatico junto da funcao, ou expor esta ingestao como um servico a
parte) - decisao explicita do usuario em 31/08/2026 de nao mexer nisso por enquanto.

Seis documentos por competencia, em dois grupos (pedido do usuario em 31/08/2026):
  Contabilidade: Previa Dime, Livro de Entradas, Livro de Saidas
  Empresa (Ecomet/SAGI): Livro Fiscal (RAICMS - traz CFOP de entrada E de saida + apuracao),
                         Livro de Entradas, Livro de Saidas
Os dois de saida (contab_saida/ecomet_saida) sao opcionais nesta funcao - uma competencia pode
ser reimportada so' com os 4 documentos originais (entrada) enquanto o de saida nao estiver
disponivel; os relatorios de divergencia de saida simplesmente ficam vazios nesse caso.

Tres relatorios de divergencia (bloco de cada ConcDivergencia):
  1. CFOP da Previa Dime x Livro Fiscal - bloco='entrada' e bloco='saida' (tipo cfop_saldo /
     coerencia_interna_ecomet), ja' existia para entrada, agora tambem para saida.
  2. Livro de Entradas contabilidade x Empresa, nota a nota - bloco='entrada'.
  3. Livro de Saidas contabilidade x Empresa, nota a nota - bloco='saida'. Trata nota cancelada
     (contabilidade zera o valor, Ecomet mantem o valor original anotado "Cancelada" - achado
     real da competencia 07/2026) como divergencia tipo='nota_cancelada', nunca escondida nem
     tratada como pareamento comum.

Esses relatorios servem para ajustar os documentos e reimportar - reimportar a mesma competencia
e' seguro (apaga e regrava documentos/lancamentos/saldos/divergencias dela; fechamento e
justificativas ja' dadas nao sao tocados). Depois de aprovada a conciliacao, o fechamento
(POST /conciliacao/periodos/{competencia}/fechar) grava o resultado definitivo em ConcFechamento.

Autoconferencia (documento_fonte.conferido): por enquanto so' registra se o parser conseguiu
ler o arquivo e encontrou pelo menos um lancamento - a comparacao com o total impresso no
rodape' de cada PDF (autoconferencia forte) foi feita manualmente ao validar os parsers (ver
claude/estado-atual.md), mas nao esta' automatizada aqui; total_documento fica nulo ate' isso
ser feito. Nao trave a ingestao por causa disso, so' deixe o campo honesto.
"""
import datetime as dt
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ...models import (ConcApuracaoLinha, ConcDivergencia, ConcDocumentoFonte,
                       ConcLancamentoEntrada, ConcPeriodo, ConcSaldoCfop)
from .parsers import (parse_dime_apuracao, parse_dime_cfop, parse_livro_contab,
                      parse_livro_ecomet, parse_livro_saidas_contab, parse_livro_saidas_ecomet,
                      parse_raicms, pdf_text)
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


def _grava_lancamentos(db, periodo_id, doc, linhas, origem, tipo):
    """tipo: 'entrada' ou 'saida'. Campos que so' existem de um lado (data_entrada/cod_emitente
    no Livro de Entradas; a coluna correspondente no Livro de Saidas nao tem data de entrada,
    so' o dia do mes) ficam None quando a linha nao trouxe."""
    for r in linhas:
        db.add(ConcLancamentoEntrada(
            periodo_id=periodo_id, documento_id=doc.id, origem=origem, tipo=tipo,
            data_entrada=_data(r.get('data_entrada')), data_documento=_data(r.get('data_doc')),
            especie=r.get('especie') or r.get('especie_cod'), serie=r.get('serie'),
            numero=r['numero'], emitente_codigo=r.get('cod_emitente'), emitente_cnpj=r.get('cnpj'),
            uf=r.get('uf'), valor_contabil=r.get('valor_contabil', 0.0), cfop=r.get('cfop'),
            cod_fiscal=r.get('cod_fiscal') or None, base_calculo=r.get('base_calculo', 0.0),
            aliquota=r.get('aliquota', 0.0), imposto=r.get('imposto', 0.0),
            difal=r.get('difal', 0.0), cancelada=bool(r.get('cancelada', False))))


def _registra_divergencias_notas(db, periodo_id, res, bloco):
    """cfop_divergente, pareamento_manual e nota_cancelada de um concilia_notas() (entrada ou
    saida, conforme `bloco`)."""
    for a, b in res['cfop_divergente']:
        db.add(ConcDivergencia(
            periodo_id=periodo_id, tipo='cfop_nota', bloco=bloco, severidade='alto',
            cfop=a['cfop'], numero_nota=a['numero'],
            descricao=(f"NF {a['numero']} está como CFOP {a['cfop']} na contabilidade e "
                       f"{b['cfop']} no Ecomet"),
            valor_contabilidade=a['valor_contabil'], valor_ecomet=b['valor_contabil'],
            diferenca=round(a['valor_contabil'] - b['valor_contabil'], 2)))

    for num, lc, le in res['revisar']:
        cancelada = any(r.get('cancelada') for r in le)
        if cancelada:
            valor_ecomet = sum(r['valor_contabil'] for r in le)
            db.add(ConcDivergencia(
                periodo_id=periodo_id, tipo='nota_cancelada', bloco=bloco, severidade='revisar',
                numero_nota=num,
                descricao=(f"NF {num}: cancelada — a contabilidade zerou o valor e o Ecomet "
                          f"manteve o valor original ({valor_ecomet:.2f}) anotado \"Cancelada\". "
                          "Confirme que a nota está mesmo cancelada antes de aprovar."),
                valor_contabilidade=sum(r['valor_contabil'] for r in lc), valor_ecomet=valor_ecomet,
                diferenca=round(sum(r['valor_contabil'] for r in lc) - valor_ecomet, 2)))
        else:
            db.add(ConcDivergencia(
                periodo_id=periodo_id, tipo='pareamento_manual', bloco=bloco, severidade='revisar',
                numero_nota=num,
                descricao=(f"NF {num}: {len(lc)} lançamento(s) na contabilidade e {len(le)} no "
                          "Ecomet não casam automaticamente por número + valor")))


def _registra_divergencias_cfop(db, periodo_id, linhas, bloco):
    """cfop_saldo (Dime x RAICMS) e coerencia_interna_ecomet (Livro do Ecomet x RAICMS), para o
    bloco de entrada ou de saida."""
    rotulo_bloco = 'entrada' if bloco == 'entrada' else 'saída'
    for l in linhas:
        if l['situacao'] == 'Divergente':
            db.add(ConcDivergencia(
                periodo_id=periodo_id, tipo='cfop_saldo', bloco=bloco, severidade='alto',
                cfop=l['cfop'],
                descricao=f"CFOP {l['cfop']} ({rotulo_bloco}): saldo divergente entre Dime e RAICMS",
                valor_contabilidade=l['contab_valor'], valor_ecomet=l['ecomet_valor'],
                diferenca=l['dif_valor']))
        if (l.get('livro_ecomet_valor') is not None
                and abs(l['livro_ecomet_valor'] - l['ecomet_valor']) > 0.01):
            db.add(ConcDivergencia(
                periodo_id=periodo_id, tipo='coerencia_interna_ecomet', bloco=bloco,
                severidade='alto', cfop=l['cfop'],
                descricao=(f"CFOP {l['cfop']} ({rotulo_bloco}): Livro do Ecomet mostra "
                          f"{l['livro_ecomet_valor']:.2f} e o RAICMS (Livro Fiscal) mostra "
                          f"{l['ecomet_valor']:.2f} — divergência interna do próprio Ecomet"),
                valor_contabilidade=l['livro_ecomet_valor'], valor_ecomet=l['ecomet_valor'],
                diferenca=round(l['livro_ecomet_valor'] - l['ecomet_valor'], 2)))


def _registra_notas_ausentes(db, periodo_id, so_contab, bloco):
    falt = agrupa_faltantes_por_cfop(so_contab)
    obs = ('provavelmente uso/consumo ou insumo' if bloco == 'entrada'
          else 'NF lançada pela contabilidade sem lançamento correspondente no Livro de Saídas '
               'do Ecomet — verifique se foi emitida/registrada')
    for cfop, dados in falt.items():
        db.add(ConcDivergencia(
            periodo_id=periodo_id, tipo='nota_ausente_ecomet', bloco=bloco, severidade='revisar',
            cfop=cfop,
            descricao=(f"{dados['qtd']} nota(s) de CFOP {cfop} lançada(s) pela contabilidade e "
                      f"ausente(s) no Ecomet — {obs}"),
            valor_contabilidade=round(dados['valor'], 2)))
    return falt


def importar_periodo(db: Session, competencia: str, *, contab_livro: str, contab_dime: str,
                     ecomet_livro: str, ecomet_raicms: str, contab_saida: str | None = None,
                     ecomet_saida: str | None = None, ciap: float = 0.0,
                     inscricao_estadual: str = "260070009") -> ConcPeriodo:
    """Le' os documentos de uma competencia, concilia e grava tudo no banco.

    contab_saida/ecomet_saida sao opcionais: sem eles, so' o Livro de Entradas e' conciliado
    nota a nota (comportamento anterior); com eles, o Livro de Saidas tambem e' - ver o
    docstring do modulo para os tres relatorios de divergencia.

    Reimportar a mesma competencia apaga e regrava os documentos/lancamentos/saldos/divergencias
    dela (o periodo em si e' preservado, junto com fechamento e justificativas ja' dadas) -
    assim corrigir um PDF errado e' so' rodar de novo.
    """
    contab = parse_livro_contab(pdf_text(contab_livro))
    ecomet = parse_livro_ecomet(pdf_text(ecomet_livro))
    dime_txt = pdf_text(contab_dime)
    dime, apur = parse_dime_cfop(dime_txt), parse_dime_apuracao(dime_txt)
    raicms = parse_raicms(pdf_text(ecomet_raicms))

    tem_saida = bool(contab_saida and ecomet_saida)
    contab_s = parse_livro_saidas_contab(pdf_text(contab_saida)) if tem_saida else []
    ecomet_s = parse_livro_saidas_ecomet(pdf_text(ecomet_saida)) if tem_saida else []

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
    if tem_saida:
        doc_contab_s = _documento(db, periodo.id, 'livro_saidas', 'contabilidade', contab_saida, contab_s)
        doc_ecomet_s = _documento(db, periodo.id, 'livro_saidas', 'ecomet', ecomet_saida, ecomet_s)

    _grava_lancamentos(db, periodo.id, doc_contab, contab, 'contabilidade', 'entrada')
    _grava_lancamentos(db, periodo.id, doc_ecomet, ecomet, 'ecomet', 'entrada')
    if tem_saida:
        _grava_lancamentos(db, periodo.id, doc_contab_s, contab_s, 'contabilidade', 'saida')
        _grava_lancamentos(db, periodo.id, doc_ecomet_s, ecomet_s, 'ecomet', 'saida')

    for fonte, tipo, d in (('dime', 'entrada', dime['entradas']), ('dime', 'saida', dime['saidas']),
                           ('raicms', 'entrada', raicms['entradas']), ('raicms', 'saida', raicms['saidas'])):
        for cfop, v in d.items():
            db.add(ConcSaldoCfop(periodo_id=periodo.id, fonte=fonte, tipo=tipo, cfop=cfop, **v))

    def _agrega_por_cfop(linhas):
        agg = defaultdict(float)
        for r in linhas:
            agg[r['cfop']] += r['valor_contabil']
        return agg

    for cfop, valor in _agrega_por_cfop(ecomet).items():
        db.add(ConcSaldoCfop(periodo_id=periodo.id, fonte='livro_ecomet', tipo='entrada', cfop=cfop,
                             valor_contabil=round(valor, 2)))
    if tem_saida:
        # notas canceladas ficam de fora do saldo por CFOP (a contabilidade tambem nao soma) -
        # senao o saldo do Livro de Saidas do Ecomet nunca bateria com o RAICMS por causa delas.
        for cfop, valor in _agrega_por_cfop([r for r in ecomet_s if not r.get('cancelada')]).items():
            db.add(ConcSaldoCfop(periodo_id=periodo.id, fonte='livro_ecomet', tipo='saida', cfop=cfop,
                                 valor_contabil=round(valor, 2)))

    # Relatorio 2: Livro de Entradas, nota a nota.
    res_e = concilia_notas(contab, ecomet)
    _registra_divergencias_notas(db, periodo.id, res_e, 'entrada')
    _registra_notas_ausentes(db, periodo.id, res_e['so_contab'], 'entrada')

    # Relatorio 3: Livro de Saidas, nota a nota (so' se os dois documentos vieram).
    if tem_saida:
        res_s = concilia_notas(contab_s, ecomet_s)
        _registra_divergencias_notas(db, periodo.id, res_s, 'saida')
        _registra_notas_ausentes(db, periodo.id, res_s['so_contab'], 'saida')

    # Relatorio 1: CFOP da Previa Dime x Livro Fiscal (entrada e saida).
    cfop_ent = compara_cfop(dime['entradas'], raicms['entradas'], ecomet)
    _registra_divergencias_cfop(db, periodo.id, cfop_ent, 'entrada')
    ecomet_s_ok = [r for r in ecomet_s if not r.get('cancelada')] if tem_saida else None
    cfop_sai = compara_cfop(dime['saidas'], raicms['saidas'], ecomet_s_ok)
    _registra_divergencias_cfop(db, periodo.id, cfop_sai, 'saida')

    sc_ec, sc_ct = raicms['resumo'].get('009', 0.0), periodo.saldo_credor_anterior or 0.0
    if abs(sc_ec - sc_ct) > 0.01:
        db.add(ConcDivergencia(
            periodo_id=periodo.id, tipo='saldo_credor_anterior', bloco=None, severidade='alto',
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
