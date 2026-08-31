"""Le' os documentos de uma competencia (Contabilidade: Previa Dime, Livro de Entradas, Livro de
Saidas; Empresa/Ecomet: Livro Fiscal, Livro de Entradas, Livro de Saidas), concilia e grava tudo
em conc_* (backend/app/models.py).

Roda LOCAL, nao na Vercel: depende do binario `pdftotext` (poppler-utils), que a funcao
serverless nao tem hoje - ver a nota em app/services/conciliacao/parsers.py. As telas de
conciliacao leem so' o que este script ja' deixou gravado no banco.

Os dois documentos de saida sao opcionais: sem eles, so' o Livro de Entradas e' conciliado nota
a nota (comportamento anterior a 31/08/2026) e o relatorio de divergencia do Livro de Saidas
fica vazio.

    DATABASE_URL="postgresql+psycopg2://...supabase..." python -m scripts.importar_conciliacao_icms \\
        --competencia 2026-07 \\
        --contab-livro  "Livro Entradas Contabilidade.pdf" \\
        --contab-dime   "Previa Dime Contabilidade.pdf" \\
        --contab-saida  "Livro Saidas Contabilidade.pdf" \\
        --ecomet-livro  "Livro de Entradas Empresa.pdf" \\
        --ecomet-raicms "Livro Fiscal Empresa.pdf" \\
        --ecomet-saida  "Livro Saida Empresa.pdf" \\
        [--ciap 19692.41]

Reimportar a mesma competencia e' seguro: apaga e regrava documentos/lancamentos/saldos/
divergencias dela (fechamento e justificativas ja' dadas nao sao tocados - ver ingestao.py). E'
assim que se ajusta um documento errado a partir de um relatorio de divergencia: corrige o PDF
(ou a origem dele) e roda este script de novo para a mesma competencia.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal  # noqa: E402
from app.services.conciliacao.ingestao import importar_periodo  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--competencia', required=True, help='AAAA-MM, ex.: 2026-07')
    ap.add_argument('--contab-livro', required=True, help='Livro de Entradas da contabilidade')
    ap.add_argument('--contab-dime', required=True, help='Prévia Dime da contabilidade')
    ap.add_argument('--contab-saida', default=None, help='Livro de Saídas da contabilidade (opcional)')
    ap.add_argument('--ecomet-livro', required=True, help='Livro de Entradas da Empresa (Ecomet/SAGI)')
    ap.add_argument('--ecomet-raicms', required=True, help='Livro Fiscal da Empresa (RAICMS)')
    ap.add_argument('--ecomet-saida', default=None, help='Livro de Saídas da Empresa (Ecomet/SAGI, opcional)')
    ap.add_argument('--ciap', type=float, default=0.0,
                    help="credito CIAP do mes (ultima coluna do CIAP ICMS) - preenchimento manual, "
                         "nao vem de nenhum documento")
    ap.add_argument('--inscricao-estadual', default='260070009')
    a = ap.parse_args()

    if bool(a.contab_saida) != bool(a.ecomet_saida):
        ap.error('--contab-saida e --ecomet-saida têm que vir os dois juntos, ou nenhum.')

    with SessionLocal() as db:
        periodo = importar_periodo(
            db, a.competencia, contab_livro=a.contab_livro, contab_dime=a.contab_dime,
            ecomet_livro=a.ecomet_livro, ecomet_raicms=a.ecomet_raicms,
            contab_saida=a.contab_saida, ecomet_saida=a.ecomet_saida, ciap=a.ciap,
            inscricao_estadual=a.inscricao_estadual)
        print(f"competência {periodo.competencia} importada (período #{periodo.id}).")
        if not a.contab_saida:
            print("  Livro de Saídas não informado — relatório de divergência de saída ficou vazio.")
        print(f"  {len(periodo.lancamentos)} lançamento(s), {len(periodo.saldos)} saldo(s) por CFOP, "
             f"{len(periodo.divergencias)} divergência(s).")
        altas = [d for d in periodo.divergencias if d.severidade == "alto"]
        print(f"  {len(altas)} divergência(s) de severidade alta — revisar antes de fechar.")


if __name__ == "__main__":
    main()
