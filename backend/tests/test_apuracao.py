"""Julho/2026 e' o gabarito: a apuracao derivada do banco tem que reproduzir a planilha."""
import pytest

from app.services.apuracao import previa

GABARITO = {
    "base_beneficiada": 3500502.40,
    "debito": 256452.672,
    "credito_presumido": 205438.1688,
    "estorno": 18300.381,
    "devolucao_icms": 24400.508,
    "icms_deduzir": 232052.164,
    "icms_recolher": 44914.37620,
    "fundo_social": 7819.203044,
    "fundo_educacao": 3742.755756,
}


@pytest.mark.parametrize("linha,esperado", GABARITO.items())
def test_julho_bate_centavo_a_centavo(db, linha, esperado):
    assert abs(previa(db, "2026-07")[linha] - esperado) < 0.01, linha


def test_carga_efetiva_do_mes(db):
    assert abs(previa(db, "2026-07")["carga_efetiva"] - 1.283) < 0.001


def test_blocos_do_mes(db):
    blocos = {(b["bloco"], b["devolucao"]): b["base"] for b in previa(db, "2026-07")["blocos"]}
    assert abs(blocos[("2", False)] - 2045095.20) < 0.01
    assert abs(blocos[("3", False)] - 1455407.20) < 0.01
    assert abs(blocos[("2", True)] - 610012.70) < 0.01
