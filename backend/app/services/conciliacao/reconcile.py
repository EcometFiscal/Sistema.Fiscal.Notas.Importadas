# -*- coding: utf-8 -*-
"""Motor de conciliacao ICMS: Contabilidade (referencia) x Ecomet.

Portado sem alteracao de logica do pacote de handoff "modulo-conciliacao-icms" (31/08/2026).
"""
from collections import defaultdict
from itertools import combinations

TOL = 0.01


def agrupa_por_nota(rows):
    d = defaultdict(list)
    for r in rows:
        d[r['numero']].append(r)
    return d


def _subset(items, alvo):
    for n in range(1, min(len(items), 6) + 1):
        for c in combinations(range(len(items)), n):
            if abs(sum(items[i]['valor_contabil'] for i in c) - alvo) < TOL:
                return c
    return None


def concilia_notas(contab, ecomet):
    """Pareia nota a nota pelo numero + valor contabil."""
    gc, ge = agrupa_por_nota(contab), agrupa_por_nota(ecomet)
    casadas, cfop_div, so_contab, so_ecomet, revisar = [], [], [], [], []
    for num in sorted(set(gc) | set(ge)):
        lc, le = gc.get(num, []), ge.get(num, [])
        if not le:
            so_contab.extend(lc); continue
        if not lc:
            so_ecomet.extend(le); continue
        sc, se = sum(x['valor_contabil'] for x in lc), sum(x['valor_contabil'] for x in le)
        if abs(sc - se) < TOL:
            pares = list(zip(sorted(lc, key=lambda x: -x['valor_contabil']),
                             sorted(le, key=lambda x: -x['valor_contabil']))) \
                    if len(lc) == len(le) else [(lc[0], le[0])]
            for a, b in pares:
                casadas.append((a, b))
                if a['cfop'] != b['cfop']:
                    cfop_div.append((a, b))
            continue
        maior, menor, alvo = (lc, le, se) if sc > se else (le, lc, sc)
        idx = _subset(maior, alvo)
        if idx is None:
            revisar.append((num, lc, le)); continue
        casados_maior = [maior[i] for i in idx]
        sobra = [maior[i] for i in range(len(maior)) if i not in idx]
        a, b = (casados_maior[0], menor[0]) if sc > se else (menor[0], casados_maior[0])
        casadas.append((a, b))
        if a['cfop'] != b['cfop']:
            cfop_div.append((a, b))
        (so_contab if sc > se else so_ecomet).extend(sobra)
    return dict(casadas=casadas, cfop_divergente=cfop_div, so_contab=so_contab,
                so_ecomet=so_ecomet, revisar=revisar)


def compara_cfop(dime, raicms, livro_ecomet=None):
    """Compara saldos por CFOP: Dime (contabilidade) x RAICMS (Ecomet)."""
    livro_agg = defaultdict(float)
    if livro_ecomet:
        for r in livro_ecomet:
            livro_agg[r['cfop']] += r['valor_contabil']
    linhas = []
    for cfop in sorted(set(dime) | set(raicms)):
        d = dime.get(cfop, {})
        e = raicms.get(cfop, {})
        linha = dict(
            cfop=cfop,
            contab_valor=d.get('valor_contabil', 0.0), ecomet_valor=e.get('valor_contabil', 0.0),
            contab_base=d.get('base_calculo', 0.0), ecomet_base=e.get('base_calculo', 0.0),
            contab_imposto=d.get('imposto', 0.0), ecomet_imposto=e.get('imposto', 0.0),
            livro_ecomet_valor=livro_agg.get(cfop, 0.0) if livro_ecomet else None)
        linha['dif_valor'] = round(linha['contab_valor'] - linha['ecomet_valor'], 2)
        linha['dif_base'] = round(linha['contab_base'] - linha['ecomet_base'], 2)
        linha['dif_imposto'] = round(linha['contab_imposto'] - linha['ecomet_imposto'], 2)
        if cfop not in raicms:
            linha['situacao'] = 'Ausente no Ecomet'
        elif cfop not in dime:
            linha['situacao'] = 'Ausente na Contabilidade'
        elif abs(linha['dif_valor']) < TOL and abs(linha['dif_imposto']) < TOL:
            linha['situacao'] = 'OK'
        else:
            linha['situacao'] = 'Divergente'
        linhas.append(linha)
    return linhas


def agrupa_faltantes_por_cfop(so_contab):
    """Notas que a contabilidade lancou e o Ecomet nao -> saldos por CFOP."""
    g = defaultdict(lambda: dict(qtd=0, valor=0.0, base=0.0, imposto=0.0, difal=0.0))
    for r in so_contab:
        a = g[r['cfop']]
        a['qtd'] += 1
        a['valor'] += r['valor_contabil']
        a['base'] += r.get('base_calculo', 0.0)
        a['imposto'] += r.get('imposto', 0.0)
        a['difal'] += r.get('difal', 0.0)
    return dict(sorted(g.items()))


def enriquece_cfop(notas_xlsx, contab_rows):
    """Preenche CFOP/ICMS de uma lista de notas a partir do Livro da contabilidade."""
    idx = defaultdict(list)
    for r in contab_rows:
        idx[r['numero']].append(r)
    saida = []
    for n in notas_xlsx:
        num = str(n.get('numero', '')).strip().lstrip('0')
        cand = idx.get(num, [])
        if not cand:
            n.update(cfop='', icms=0.0, base_calculo=0.0, origem='NAO ENCONTRADA'); saida.append(n); continue
        val = n.get('valor')
        exatos = [c for c in cand if val is not None and abs(c['valor_contabil'] - float(val)) < TOL]
        alvo = exatos or cand
        cfops = sorted({c['cfop'] for c in alvo})
        n.update(cfop='/'.join(cfops),
                 icms=sum(c.get('imposto', 0.0) for c in alvo),
                 base_calculo=sum(c.get('base_calculo', 0.0) for c in alvo),
                 valor_contab_livro=sum(c['valor_contabil'] for c in alvo),
                 origem='EXATA' if exatos else ('NUMERO' if len(cand) == 1 else 'AMBIGUA'))
        saida.append(n)
    return saida
