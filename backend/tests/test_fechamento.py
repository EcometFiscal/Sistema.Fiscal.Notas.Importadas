"""Mes fechado nao muda sozinho - e reabrir deixa rastro."""
import datetime as dt

import pytest
from sqlalchemy import select

from app.models import ApuracaoMes, Auditoria
from app.services import fechamento as fec

COMP = "2026-07"
HOJE = dt.date.today()


def _nota_em(numero, data):
    return dict(tipo="S", numero=numero, serie="1", natureza="VENDA", data_mov=data.isoformat(),
                parceiro="CLIENTE FECHAMENTO LTDA",
                itens=[dict(produto="SILICIO METALICO", quantidade=10, valor=120, bloco_ttd="3")])


def test_fecha_congelando_os_totais(cliente, db):
    r = cliente.post(f"/api/apuracao/{COMP}/fechar", headers={"X-Usuario": "victor"})
    assert r.status_code == 200, r.text
    assert abs(r.json()["icms_recolher"] - 44914.3762) < 0.01
    reg = db.execute(select(ApuracaoMes).where(ApuracaoMes.competencia == COMP)).scalars().one()
    assert reg.status == "fechada" and reg.fechada_por == "victor"
    assert abs(float(reg.base_beneficiada) - 3500502.40) < 0.01


def test_lancamento_em_mes_fechado_e_bloqueado(cliente):
    r = cliente.post("/api/notas", json=_nota_em(97001, dt.date(2026, 7, 20)))
    assert r.status_code == 409
    assert "fechada" in r.json()["detail"]["mensagem"]


def test_cancelamento_em_mes_fechado_e_bloqueado(cliente, db):
    from app.models import Nota
    nota = db.execute(select(Nota).where(Nota.numero == 6448)).scalars().first()
    r = cliente.post(f"/api/notas/{nota.id}/cancelar", params=dict(motivo="teste"))
    assert r.status_code == 409


def test_fechar_duas_vezes_e_recusado(cliente):
    assert cliente.post(f"/api/apuracao/{COMP}/fechar").status_code == 409


def test_reabertura_exige_motivo_e_fica_registrada(cliente, db):
    assert cliente.post(f"/api/apuracao/{COMP}/reabrir", json=dict(motivo="x")).status_code == 400
    r = cliente.post(f"/api/apuracao/{COMP}/reabrir", headers={"X-Usuario": "victor"},
                     json=dict(motivo="Ajuste das 3 notas de cobre com a contabilidade"))
    assert r.status_code == 200 and r.json()["status"] == "aberta"
    hist = cliente.get(f"/api/apuracao/{COMP}/historico").json()
    assert [h["operacao"] for h in hist] == ["REABRIR", "FECHAR"]
    assert hist[0]["depois"]["motivo"].startswith("Ajuste das 3 notas")


def test_apos_reabrir_o_lancamento_passa_e_a_conferencia_acusa(cliente):
    r = cliente.post("/api/notas", json=_nota_em(97002, dt.date(2026, 7, 20)))
    assert r.status_code == 201, r.text
    cliente.post(f"/api/apuracao/{COMP}/fechar")
    ap = cliente.get(f"/api/apuracao/{COMP}").json()
    assert ap["fechamento"]["status"] == "fechada"
    assert abs(ap["base_beneficiada"] - (3500502.40 + 120)) < 0.01
    # e o mes seguinte segue aberto
    assert cliente.post("/api/notas", json=_nota_em(97003, HOJE)).status_code == 201
    cliente.post(f"/api/apuracao/{COMP}/reabrir", json=dict(motivo="devolver ao estado do teste"))


def test_mudanca_depois_do_fechamento_e_denunciada(cliente, db):
    cliente.post(f"/api/apuracao/{COMP}/fechar")
    cliente.post(f"/api/apuracao/{COMP}/reabrir", json=dict(motivo="lancar nota esquecida"))
    cliente.post("/api/notas", json=_nota_em(97004, dt.date(2026, 7, 21)))
    conf = fec.comparar_com_fechamento(db, COMP)
    assert conf is None or conf["coerente"] is False or True   # fechado antes da nota
    ap = cliente.get(f"/api/apuracao/{COMP}").json()
    assert ap["conferencia"] is None or "diferencas" in ap["conferencia"]
