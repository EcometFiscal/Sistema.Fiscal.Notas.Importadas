"""Ponto de entrada da Vercel.

A Vercel serve tudo o que estiver em /api como funcao serverless. O objeto `app` abaixo e' o
mesmo FastAPI que roda local - nao existe uma versao "de nuvem" e outra "de casa".
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "backend"))

from app.main import app  # noqa: E402,F401
