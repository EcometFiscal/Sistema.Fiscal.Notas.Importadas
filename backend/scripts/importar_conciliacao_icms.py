"""Le' os 4 PDFs de uma competencia (Previa Dime, Livro de Entradas da contabilidade, Livro de
Entradas e RAICMS do Ecomet), concilia e grava tudo em conc_* (backend/app/models.py).

Roda LOCAL, nao na Vercel: depende do binario `pdftotext` (poppler-utils), que a funcao
serverless nao tem hoje - ver a nota em app/services/conciliacao/parsers.py. As telas de
conciliacao (fase 2+) leem so' o que este script ja' deixou gravado no banco.

    DATABASE_URL="postgresql+psycopg2://...supabase..." python -m scripts.importar_conciliacao_icms \\
        --competencia 2026-07 \\
        --contab-livro  "Livro Entradas.pdf" \\
        --contab-dime   "Previa Dime.pdf" \\
        --ecomet-livro  "Livro de Entradas SAGI.pdf" \\
        --ecomet-raicms "Livro Fiscal SAGI.pdf" \\
        [--ciap 19692.41]

Reimportar a mesma competencia e' seguro: apaga e regrava documentos/lancamentos/saldos/
divergencias dela (fechamento e justificativas ja' dadas nao sao tocados - ver ingestao.py).
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
    ap.add_argument('--contab-livro', required=True)
    ap.add_argument('--contab-dime', required=True)
    ap.add_argument('--ecomet-livro', required=True)
    ap.add_argument('--ecomet-raicms', required=True)
    ap.add_argument('--ciap', type=float, default=0.0,
                    help="credito CIAP do mes (ultima coluna do CIAP ICMS) - preenchimento manual, "
                         "nao vem de nenhum dos 4 PDFs")
    ap.add_argument('--inscricao-estadual', default='260070009')
    a = ap.parse_args()

    with SessionLocal() as db:
        periodo = importar_periodo(
            db, a.competencia, contab_livro=a.contab_livro, contab_dime=a.contab_dime,
            ecomet_livro=a.ecomet_livro, ecomet_raicms=a.ecomet_raicms, ciap=a.ciap,
            inscricao_estadual=a.inscricao_estadual)
        print(f"competência {periodo.competencia} importada (período #{periodo.id}).")
        print(f"  {len(periodo.lancamentos)} lançamento(s), {len(periodo.saldos)} saldo(s) por CFOP, "
             f"{len(periodo.divergencias)} divergência(s).")
        altas = [d for d in periodo.divergencias if d.severidade == "alto"]
        print(f"  {len(altas)} divergência(s) de severidade alta — revisar antes de fechar.")


if __name__ == "__main__":
    main()
