"""Importacao por XML: o que o sistema faz com o pacote que sai do sistema atual."""
import datetime as dt

import pytest
from sqlalchemy import select

from app.models import Excecao, Nota, NotaItem, Parceiro, Produto
from app.services import importacao as imp
from app.services.xml_nfe import XmlInvalido, ler
from tests.fixtures_nfe import CNPJ_EMPRESA, chave, evento_cancelamento, nfe, pacote

HOJE = dt.date.today()
ONTEM = HOJE - dt.timedelta(days=1)


@pytest.fixture(autouse=True)
def cnpj(db):
    imp.definir_cnpj_empresa(db, CNPJ_EMPRESA, "teste")
    db.commit()


def _sobe(cliente, arquivos, nome="pacote.zip"):
    r = cliente.post("/api/importar/zip",
                     files={"arquivo": (nome, pacote(arquivos), "application/zip")})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- leitura do XML
def test_le_os_campos_que_importam():
    nf = ler(nfe(8001, cfop="6101", aliquota=4.0, origem="1", quantidade=32621, valor=610012.70))
    assert nf.numero == 8001 and nf.serie == "1" and nf.modelo == "55"
    assert len(nf.chave) == 44
    item = nf.itens[0]
    assert item.cfop == "6101" and item.ncm == "76020000" and item.origem == "1"
    assert item.aliquota == 0.04 and abs(item.valor - 610012.70) < 0.01
    assert abs(item.base_calculo - 610012.70) < 0.01


def test_xml_ilegivel_e_recusado():
    with pytest.raises(XmlInvalido):
        ler(b"<html>isto nao e uma nota</html>")


# ---------------------------------------------------------------- bloco do TTD
@pytest.mark.parametrize("cfop,aliq,origem,esperado", [
    ("5101", 12.0, "1", "3"),     # interna
    ("6101", 4.0, "1", "2"),      # interestadual com mercadoria importada
    ("6101", 12.0, "0", "1"),     # interestadual nacional
    ("7101", 0.0, "1", None),     # exportacao: fora do beneficio
])
def test_bloco_vem_do_proprio_xml(cfop, aliq, origem, esperado):
    nf = ler(nfe(8100, cfop=cfop, aliquota=aliq, origem=origem))
    bloco, _ = imp.derivar_bloco(nf, nf.itens[0])
    assert bloco == esperado


def test_aliquota_fora_da_tabela_vira_pendencia():
    nf = ler(nfe(8101, cfop="6101", aliquota=7.0, origem="0"))
    bloco, motivo = imp.derivar_bloco(nf, nf.itens[0])
    assert bloco == "1" and "fora da tabela" in motivo


# ---------------------------------------------------------------- importacao
def test_saida_entra_no_estoque_e_na_apuracao(cliente, db):
    lote = _sobe(cliente, {"nf.xml": nfe(8200, cfop="5101", aliquota=12.0,
                                         produto="SILICIO METALICO", ncm="72023000",
                                         quantidade=100, valor=1200, data=HOJE)})
    assert lote["importadas"] == 1 and lote["erros"] == 0
    nota = db.execute(select(Nota).where(Nota.numero == 8200)).scalars().one()
    assert nota.tipo == "S" and nota.chave_acesso and len(nota.chave_acesso) == 44
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == nota.id)).scalars().one()
    assert item.bloco_ttd == "3" and item.origem_merc == "1" and item.ncm == "72023000"


def test_entrada_de_importacao(cliente, db):
    lote = _sobe(cliente, {"e.xml": nfe(8300, cfop="3102", emit_cnpj="55555555000155",
                                        dest_cnpj=CNPJ_EMPRESA, tipo_nf="1",
                                        produto="SUCATA DE COBRE", ncm="74040000",
                                        quantidade=20000, valor=1000000, data=ONTEM)})
    assert lote["importadas"] == 1
    nota = db.execute(select(Nota).where(Nota.numero == 8300)).scalars().one()
    assert nota.tipo == "E" and nota.natureza == "IMPORTACAO"


def test_devolucao_de_venda_volta_ao_estoque(cliente, db):
    _sobe(cliente, {"d.xml": nfe(8400, cfop="1202", emit_cnpj="98765432000188",
                                 dest_cnpj=CNPJ_EMPRESA, fin="4", aliquota=4.0,
                                 produto="SUCATA DE ALUMINIO", quantidade=500, valor=9000,
                                 data=ONTEM)})
    nota = db.execute(select(Nota).where(Nota.numero == 8400)).scalars().one()
    assert nota.tipo == "E" and nota.natureza == "DEVOLUCAO"


def test_chave_repetida_nao_duplica(cliente):
    xml = nfe(8500, data=HOJE)
    primeiro = _sobe(cliente, {"a.xml": xml})
    segundo = _sobe(cliente, {"a.xml": xml})
    assert primeiro["importadas"] == 1
    assert segundo["duplicadas"] == 1 and segundo["importadas"] == 0


def test_nota_de_terceiros_e_ignorada(cliente):
    lote = _sobe(cliente, {"x.xml": nfe(8600, emit_cnpj="11111111000111",
                                        dest_cnpj="22222222000122")})
    assert lote["arquivos"][0]["situacao"] == "ignorada"


def test_nota_nao_autorizada_e_ignorada(cliente):
    lote = _sobe(cliente, {"x.xml": nfe(8650, cstat="101", data=HOJE)})
    assert lote["arquivos"][0]["situacao"] == "ignorada"


def test_xml_quebrado_nao_derruba_o_lote(cliente):
    lote = _sobe(cliente, {"ok.xml": nfe(8700, data=HOJE), "ruim.xml": "<nao> e xml valido"})
    assert lote["importadas"] == 1 and lote["erros"] == 1


def test_produto_novo_vira_pendencia(cliente, db):
    lote = _sobe(cliente, {"p.xml": nfe(8800, produto="LIGA DE ZINCO ESPECIAL", ncm="79011100",
                                        data=HOJE)})
    assert lote["pendentes"] == 1
    assert db.execute(select(Produto)
                      .where(Produto.descricao == "LIGA DE ZINCO ESPECIAL")).scalars().first()
    exc = db.execute(select(Excecao).where(Excecao.tipo == "importacao_xml")).scalars().all()
    assert any("não existia no cadastro" in e.descricao or "nao existia" in e.descricao
               for e in exc)


def test_xml_preenche_o_cnpj_que_a_planilha_nao_tinha(cliente, db):
    """Os 60 parceiros vieram da planilha sem CNPJ. O XML e' quem preenche, sem ninguem digitar."""
    alvo = db.execute(select(Parceiro)
                      .where(Parceiro.nome == "METALEX LTDA")).scalars().first()
    assert alvo and alvo.cnpj is None
    _sobe(cliente, {"c.xml": nfe(8900, dest_nome="METALEX LTDA",
                                 dest_cnpj="33444555000166", data=HOJE)})
    db.refresh(alvo)
    assert alvo.cnpj == "33444555000166"


def test_evento_de_cancelamento_cancela_a_nota(cliente, db):
    ch = chave(9000)
    _sobe(cliente, {"n.xml": nfe(9000, chave_custom=ch, data=HOJE)})
    nota = db.execute(select(Nota).where(Nota.chave_acesso == ch)).scalars().one()
    assert nota.status == "lancada"
    _sobe(cliente, {"ev.xml": evento_cancelamento(ch)})
    db.refresh(nota)
    assert nota.status == "cancelada"


def test_zip_com_subpasta_e_zip_aninhado(cliente):
    import io
    import zipfile
    interno = pacote({"dentro/nf.xml": nfe(9100, data=HOJE)})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("julho/nf2.xml", nfe(9101, data=HOJE))
        z.writestr("agosto.zip", interno)
    r = cliente.post("/api/importar/zip",
                     files={"arquivo": ("tudo.zip", buf.getvalue(), "application/zip")})
    assert r.json()["importadas"] == 2


def test_nota_de_mes_fechado_fica_pendente(cliente):
    cliente.post("/api/apuracao/2026-07/fechar")
    lote = _sobe(cliente, {"f.xml": nfe(9200, data=dt.date(2026, 7, 15))})
    arq = lote["arquivos"][0]
    assert arq["situacao"] == "pendente" and "fechada" in arq["motivo"]
    cliente.post("/api/apuracao/2026-07/reabrir", json=dict(motivo="voltar ao estado do teste"))


def test_lote_fica_registrado(cliente):
    lote = _sobe(cliente, {"n.xml": nfe(9300, data=HOJE)}, nome="exportacao_agosto.zip")
    lista = cliente.get("/api/importar/lotes").json()
    assert lista[0]["nome"] == "exportacao_agosto.zip"
    detalhe = cliente.get(f"/api/importar/lotes/{lote['id']}").json()
    assert detalhe["arquivos"][0]["chave_acesso"]


def test_o_pacote_diz_qual_e_o_cnpj_do_estabelecimento(db, cliente):
    """Sem A1 e sem cadastro previo: o CNPJ que aparece dos dois lados e' o da empresa."""
    from app.models import Configuracao
    from app.services.importacao import detectar_cnpj
    from app.services.xml_nfe import ler

    notas = [
        ler(nfe(9500, emit_cnpj=CNPJ_EMPRESA, dest_cnpj="11111111000111", data=HOJE)),
        ler(nfe(9501, emit_cnpj=CNPJ_EMPRESA, dest_cnpj="22222222000122", data=HOJE)),
        ler(nfe(9502, emit_cnpj="33333333000133", dest_cnpj=CNPJ_EMPRESA, data=HOJE)),
    ]
    cnpj, vezes, empate = detectar_cnpj(notas)
    assert cnpj == CNPJ_EMPRESA and vezes == 3 and empate == 1

    # e o importador aplica sozinho quando ainda nao ha' configuracao
    reg = db.get(Configuracao, "cnpj_empresa")
    if reg:
        db.delete(reg)
        db.commit()
    lote = _sobe(cliente, {"a.xml": nfe(9503, emit_cnpj=CNPJ_EMPRESA, dest_cnpj="11111111000111",
                                        data=HOJE),
                           "b.xml": nfe(9504, emit_cnpj="33333333000133", dest_cnpj=CNPJ_EMPRESA,
                                        cfop="3102", data=HOJE)})
    assert lote["importadas"] == 2
    assert cliente.get("/api/configuracao").json()["cnpj_empresa"]["valor"] == CNPJ_EMPRESA
