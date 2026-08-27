"""Pasta vigiada: o XML cai na pasta, o sistema le' e move para 'processados'.

Roda no host que enxerga a pasta de rede. Enquanto nao houver acesso ao servidor da empresa,
o caminho e' o upload do ZIP pela tela - este script fica pronto para quando houver.

    python -m scripts.pasta_vigiada --pasta /mnt/xml/entrada --intervalo 60
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal                     # noqa: E402
from app.services.importacao import importar_nota   # noqa: E402
from app.services.xml_nfe import XmlInvalido, evento_cancelamento, ler  # noqa: E402


def processar(pasta: str, usuario: str) -> int:
    feitos = 0
    destino = os.path.join(pasta, "processados")
    erros = os.path.join(pasta, "com_erro")
    os.makedirs(destino, exist_ok=True)
    os.makedirs(erros, exist_ok=True)
    for nome in sorted(os.listdir(pasta)):
        caminho = os.path.join(pasta, nome)
        if not os.path.isfile(caminho) or not nome.lower().endswith(".xml"):
            continue
        with open(caminho, "rb") as f:
            dados = f.read()
        with SessionLocal() as db:
            try:
                if evento_cancelamento(dados):
                    print(f"{nome}: evento de cancelamento - use a importacao por ZIP")
                    shutil.move(caminho, os.path.join(destino, nome))
                    continue
                nf = ler(dados)
                r = importar_nota(db, nf, usuario, f"pasta:{pasta}")
                db.commit()
                print(f"{nome}: {r.situacao}" + (f" - {r.motivo}" if r.motivo else ""))
                shutil.move(caminho, os.path.join(destino, nome))
                feitos += 1
            except XmlInvalido as e:
                db.rollback()
                print(f"{nome}: XML invalido - {e}")
                shutil.move(caminho, os.path.join(erros, nome))
    return feitos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pasta", required=True)
    ap.add_argument("--intervalo", type=int, default=60, help="segundos entre varreduras; 0 = uma vez")
    ap.add_argument("--usuario", default="pasta-vigiada")
    args = ap.parse_args()
    while True:
        processar(args.pasta, args.usuario)
        if not args.intervalo:
            break
        time.sleep(args.intervalo)


if __name__ == "__main__":
    main()
