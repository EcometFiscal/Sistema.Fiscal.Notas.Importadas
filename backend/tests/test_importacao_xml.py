"""Importacao por XML: o que o sistema faz com o pacote que sai do sistema atual."""
import datetime as dt
from unittest.mock import patch

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


def test_le_nfref_da_nota_referenciada():
    ref = chave(6576, "98765432000188")
    nf = ler(nfe(6579, refs=[ref]))
    assert nf.refs == [ref]


def test_sem_nfref_a_lista_vem_vazia():
    nf = ler(nfe(8001))
    assert nf.refs == []


# ------------------------------------------------------- bloco do TTD (por NCM + ambito)
@pytest.mark.parametrize("ncm,uf,esperado", [
    ("74040000", "SC", None),     # cobre interno: aliquota 0, fora do beneficio
    ("74040000", "SP", "1"),      # cobre interestadual: 12%/11,40%
    ("76020000", "SC", None),     # sucata de aluminio interna: aliquota 0, fora do beneficio
    ("76020000", "SP", "2"),      # sucata de aluminio interestadual: 4%/3%
    ("28046900", "SC", "3"),      # silicio interno: cobra igual
    ("28046900", "SP", "3"),      # silicio interestadual: cobra igual
    # Lingote (aluminio e magnesio) cobra igual nos dois ambitos - diferente da sucata do mesmo
    # metal. Achado a partir da NF 6543 (Victor, 28/08/2026), retroativo a 2020-01-01.
    ("76011000", "SC", "2"),      # lingote de aluminio interno: 4%/3%, nao fica de fora
    ("76011000", "SP", "2"),      # lingote de aluminio interestadual: 4%/3%
    ("81041100", "SC", "2"),      # lingote de magnesio interno: 4%/3%, nao fica de fora
    ("81041100", "SP", "2"),      # lingote de magnesio interestadual: 4%/3%
])
def test_bloco_vem_do_ncm_e_do_ambito(db, ncm, uf, esperado):
    bloco, _ = imp.derivar_bloco(db, ncm, uf, dt.date(2026, 8, 10))
    assert bloco == esperado


def test_ncm_fora_da_tabela_vira_pendencia_sem_chutar(db):
    bloco, motivo = imp.derivar_bloco(db, "99999999", "SP", dt.date(2026, 8, 10))
    assert bloco is None and "sem regra" in motivo


def test_aliquota_do_xml_diverge_da_tabela_vira_pendencia(db):
    # NCM do aluminio interestadual manda 4%, XML veio com 12% - grava e abre pendencia,
    # nao corrige em silencio nem recusa a nota.
    bloco, motivo = imp.derivar_bloco(db, "76020000", "SP", dt.date(2026, 8, 10),
                                      aliquota_xml=0.12)
    assert bloco == "2" and motivo and "diverge" in motivo


# ---------------------------------------------------------------- importacao
def test_saida_entra_no_estoque_e_na_apuracao(cliente, db):
    lote = _sobe(cliente, {"nf.xml": nfe(8200, cfop="5101", aliquota=12.0,
                                         produto="SILICIO METALICO", ncm="28046900",
                                         quantidade=100, valor=1200, data=HOJE)})
    assert lote["importadas"] == 1 and lote["erros"] == 0
    nota = db.execute(select(Nota).where(Nota.numero == 8200)).scalars().one()
    assert nota.tipo == "S" and nota.chave_acesso and len(nota.chave_acesso) == 44
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == nota.id)).scalars().one()
    assert item.bloco_ttd == "3" and item.origem_merc == "1" and item.ncm == "28046900"
    assert item.cst_completo == "100"


# --------------------------------------------------- filtro de origem (mercadoria importada)
@pytest.mark.parametrize("numero,origem,entra", [
    (8151, "1", True), (8152, "6", True),                     # importada: entra
    (8153, "0", False), (8154, "2", False),                   # nao importada: nao entra
    (8155, "4", False), (8156, "5", False),
])
def test_so_origem_1_e_6_contam_como_importado(cliente, numero, origem, entra):
    lote = _sobe(cliente, {"nf.xml": nfe(numero, origem=origem, data=HOJE)})
    situacao = lote["arquivos"][0]["situacao"]
    assert (situacao != "ignorada") == entra


def test_nota_sem_nenhum_item_importado_e_ignorada_com_motivo(cliente):
    lote = _sobe(cliente, {"nf.xml": nfe(8160, origem="0", data=HOJE)})
    arq = lote["arquivos"][0]
    assert arq["situacao"] == "ignorada" and "origem" in arq["motivo"]
    assert lote["importadas"] == 0


def test_nota_mista_entra_mas_item_nao_importado_fica_fora_do_ttd(cliente, db):
    """Nota com um item de origem importada e outro nao: a nota inteira entra (estoque fica
    fiel), mas o item nao importado nao recebe bloco e vira pendencia."""
    xml = nfe(8170, origem="1", produto="SUCATA DE ALUMINIO", ncm="76020000", data=HOJE)
    # segundo item, origem nacional (0), enxertado no mesmo XML
    xml_misto = xml.replace(
        '<det nItem="1">',
        '<det nItem="2"><prod><cProd>002</cProd><xProd>SUCATA DE ALUMINIO</xProd>'
        '<NCM>76020000</NCM><CFOP>5101</CFOP><uCom>KG</uCom><qCom>10.0000</qCom>'
        '<vUnCom>100.000000</vUnCom><vProd>1000.00</vProd></prod>'
        '<imposto><ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC>'
        '<vBC>1000.00</vBC><pICMS>4.00</pICMS><vICMS>40.00</vICMS></ICMS00></ICMS></imposto>'
        '</det><det nItem="1">')
    lote = _sobe(cliente, {"nf.xml": xml_misto})
    assert lote["arquivos"][0]["situacao"] != "ignorada"
    nota = db.execute(select(Nota).where(Nota.numero == 8170)).scalars().one()
    itens = db.execute(select(NotaItem).where(NotaItem.nota_id == nota.id)).scalars().all()
    assert len(itens) == 2
    importado = next(i for i in itens if i.origem_merc == "1")
    nacional = next(i for i in itens if i.origem_merc == "0")
    assert importado.bloco_ttd == "2" and nacional.bloco_ttd is None


def test_cfop_3949_desdobramento_e_ignorado(cliente):
    """A entrada de importado e' sempre CFOP 3102; o 3949 e' o desdobramento do mesmo lote em
    NFs menores (mesma mercadoria, quantidade e valor ja contabilizados na 3102) - Victor,
    28/08/2026. Importar as duas dobraria a entrada."""
    lote = _sobe(cliente, {"a.xml": nfe(9611, cfop="3949", emit_cnpj="55555555000155",
                                        dest_cnpj=CNPJ_EMPRESA, tipo_nf="1",
                                        produto="SILICIO METALICO", ncm="28046900", data=ONTEM)})
    arq = lote["arquivos"][0]
    assert arq["situacao"] == "ignorada" and "3949" in arq["motivo"]
    assert lote["importadas"] == 0 and lote["complementadas"] == 0


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


def test_devolucao_com_nome_de_produto_diferente_casa_pelo_ncm_e_cst(cliente, db):
    """Cliente que devolve pode chamar o produto de outro jeito no XML - o que importa pra
    casar e' NCM e CST (= origem + CST) batendo com o nosso cadastro, nao o nome."""
    lote = _sobe(cliente, {"d.xml": nfe(8410, cfop="1202", emit_cnpj="98765432000188",
                                        dest_cnpj=CNPJ_EMPRESA, fin="4", aliquota=4.0,
                                        origem="1", produto="ALUMINIO SUCATA MISTA",
                                        ncm="76020000", quantidade=500, valor=9000,
                                        data=ONTEM)})
    assert lote["arquivos"][0]["situacao"] != "erro"
    nota = db.execute(select(Nota).where(Nota.numero == 8410)).scalars().one()
    assert nota.tipo == "E" and nota.natureza == "DEVOLUCAO"
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == nota.id)).scalars().one()
    assert item.produto.descricao == "SUCATA DE ALUMINIO"      # casou pelo NCM, nao pelo nome
    assert item.cst_completo == "100"                          # origem 1 + CST 00


@pytest.mark.parametrize("cfop", ["2949", "1949"])
def test_cfop_2949_e_1949_sao_devolucao_por_confirmacao_do_cliente(cliente, db, cfop):
    """CFOP generico de 'outras entradas' - Victor, 28/08/2026: na operacao da Ecomet esse CFOP
    de entrada e' sempre usado pra estornar uma venda, mesmo sem finNFe=4 e sem NFref. Nao e' uma
    regra geral de mercado (esses CFOPs podem ser outra coisa em outra empresa) - e' a propria
    empresa confirmando o uso dela."""
    numero = 6590 if cfop == "2949" else 6591
    lote = _sobe(cliente, {"e.xml": nfe(
        numero, cfop=cfop, fin="1", aliquota=4.0, origem="1",
        emit_cnpj="98765432000188", dest_cnpj=CNPJ_EMPRESA,
        produto="SUCATA DE ALUMINIO", ncm="76020000",
        quantidade=500, valor=9000.0, data=ONTEM)})
    assert lote["arquivos"][0]["situacao"] != "erro"
    nota = db.execute(select(Nota).where(Nota.numero == numero)).scalars().one()
    assert nota.tipo == "E" and nota.natureza == "DEVOLUCAO"


def test_estorno_referenciado_e_devolucao_mesmo_com_ajuste_e_cfop_fora_da_lista(cliente, db):
    """Caso real: NF 6579/ago-2026, estorno da NF 6576 porque ela nao foi cancelada dentro do
    prazo da SEFAZ (CFOP 2949, que hoje ja' esta' em CFOP_DEVOLUCAO). Aqui testamos a rede de
    seguranca do NFref com um CFOP generico que NAO esta' na lista - pra cobrir um estorno futuro
    que venha com um CFOP que a Ecomet ainda nao usou: finNFe=3 ('ajuste') referenciando a NF de
    venda original e' o sinal de que a nota so' existe pra desfazer outra. Sem isto a nota entra
    como COMPRA, nunca passa pelo bloco do TTD, e o credito presumido da venda original nunca e'
    estornado."""
    chave_original = chave(6576, "98765432000188")
    lote = _sobe(cliente, {"e.xml": nfe(
        6579, cfop="2101", fin="3", tipo_nf="0", aliquota=4.0, origem="1",
        nat_op="ESTORNO DE NFE NAO CANCELADA DENTRO DO PRAZO",
        emit_cnpj=CNPJ_EMPRESA, dest_cnpj="98765432000188",
        produto="SUCATA DE ALUMINIO", ncm="76020000",
        quantidade=6252, valor=281864.0, data=ONTEM, refs=[chave_original])})
    assert lote["arquivos"][0]["situacao"] != "erro"
    nota = db.execute(select(Nota).where(Nota.numero == 6579)).scalars().one()
    assert nota.tipo == "E" and nota.natureza == "DEVOLUCAO"
    excecoes = db.execute(select(Excecao).where(Excecao.nota_id == nota.id)).scalars().all()
    assert any("NFref" in e.descricao and "6579" in e.descricao for e in excecoes), (
        "a classificacao por NFref deveria abrir uma pendencia informativa, nunca corrigir em silencio")
    # A nota e' autoemitida (emit_cnpj == cnpj da empresa, tpNF=0): quem NAO e' a gente e' o
    # destinatario (SP), nao o emitente (SC, que somos nos mesmos). Se a UF da contraparte
    # usasse o emitente por engano, o item cairia como operacao interna (SC), sem beneficio pro
    # aluminio, o bloco ficaria None e o credito presumido continuaria sem ser estornado mesmo
    # com natureza=DEVOLUCAO.
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == nota.id)).scalars().first()
    assert item.bloco_ttd == "2", (
        "bloco do TTD nao derivado - a UF da contraparte de uma entrada autoemitida precisa vir "
        "do destinatario, nao do emitente (somos nos)")


def test_estorno_referenciado_sem_finalidade_ajuste_nao_vira_devolucao(cliente, db):
    """Complementar (finNFe=2) tambem referencia a NF original em NFref, mas nao e' estorno -
    e' acrescimo de valor/quantidade a uma nota ja lancada. NFref sozinho nao pode bastar, e o
    CFOP usado (6101) nao esta' em CFOP_DEVOLUCAO."""
    chave_original = chave(7000, "98765432000188")
    lote = _sobe(cliente, {"c.xml": nfe(
        7001, cfop="6101", fin="2", aliquota=4.0, origem="1",
        emit_cnpj="98765432000188", dest_cnpj=CNPJ_EMPRESA,
        produto="SUCATA DE ALUMINIO", ncm="76020000",
        quantidade=100, valor=2000.0, data=ONTEM, refs=[chave_original])})
    assert lote["importadas"] == 1
    nota = db.execute(select(Nota).where(Nota.numero == 7001)).scalars().one()
    assert nota.tipo == "E" and nota.natureza != "DEVOLUCAO"


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


def test_ncm_fora_do_ttd_e_ignorado_como_equipamento(cliente, db):
    """NCM que nao e' nenhuma das 6 sucatas do TTD (ex.: equipamento importado com origem 1,
    como a prensa hidraulica da NF 6532/julho-2026) - a nota inteira e' ignorada, nao vira
    produto novo no cadastro nem pendencia (Victor, 28/08/2026)."""
    lote = _sobe(cliente, {"p.xml": nfe(8800, produto="PRENSA HIDRAULICA IMPORTADA",
                                        ncm="84623900", data=HOJE)})
    arq = lote["arquivos"][0]
    assert arq["situacao"] == "ignorada" and "NCM" in arq["motivo"]
    assert lote["importadas"] == 0 and lote["pendentes"] == 0
    assert not db.execute(select(Produto)
                          .where(Produto.descricao == "PRENSA HIDRAULICA IMPORTADA")
                          ).scalars().first()


def test_produto_com_descricao_nova_mas_ncm_conhecido_casa_pelo_ncm(cliente, db):
    """NCM de uma das 6 sucatas do TTD, mas descricao diferente da canonica no XML - entra,
    casa pelo NCM com o produto ja cadastrado e vira pendencia pra confirmar; nao cria produto
    novo, porque o NCM ja e' conhecido."""
    lote = _sobe(cliente, {"p.xml": nfe(8801, produto="SUCATA DE COBRE MISTA",
                                        ncm="74040000", data=HOJE)})
    assert lote["pendentes"] == 1
    exc = db.execute(select(Excecao).where(Excecao.tipo == "importacao_xml")).scalars().all()
    assert any("casado" in e.descricao and "NCM" in e.descricao for e in exc)
    assert not db.execute(select(Produto)
                          .where(Produto.descricao == "SUCATA DE COBRE MISTA")).scalars().first()


def test_mini_lingote_de_magnesio_casa_exato_nao_pelo_ncm(cliente, db):
    """Mini Lingote de Magnesio (NCM 81041100, adicionado 28/08/2026) e' cadastro proprio, com o
    mesmo NCM de Lingote de Magnesio - precisa casar pela descricao exata, sem aviso de NCM, e a
    regra e' igual a de Lingote: tributa dentro e fora do estado (achado a partir da NF 6543)."""
    lote = _sobe(cliente, {"m.xml": nfe(8802, produto="MINI LINGOTE DE MAGNESIO", ncm="81041100",
                                        cfop="5102", dest_uf="SC", aliquota=4.0, origem="1",
                                        quantidade=200, valor=7400.0, data=HOJE)})
    assert lote["importadas"] == 1
    nota = db.execute(select(Nota).where(Nota.numero == 8802)).scalars().one()
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == nota.id)).scalars().one()
    assert item.produto.descricao == "MINI LINGOTE DE MAGNESIO"
    assert item.bloco_ttd == "2"                                 # interna, mas tributa mesmo assim
    exc = db.execute(select(Excecao).where(Excecao.nota_id == nota.id)).scalars().all()
    assert not any("casado" in e.descricao and "NCM" in e.descricao for e in exc)


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


def test_evento_que_nao_e_cancelamento_e_ignorado_nao_vira_erro(cliente):
    """Carta de Correcao (tpEvento 110110) nao e' cancelamento nem NF-e - vira ignorada com
    motivo, nao erro de leitura (achado real no pacote de julho/2026)."""
    carta = '''<?xml version="1.0" encoding="UTF-8"?>
<ProcEventoNFe versao="1.00" xmlns="http://www.portalfiscal.inf.br/nfe">
 <evento versao="1.00"><infEvento Id="ID1101109999999">
  <tpEvento>110110</tpEvento><descEvento>Carta de Correcao</descEvento>
 </infEvento></evento>
</ProcEventoNFe>'''
    lote = _sobe(cliente, {"carta.xml": carta})
    arq = lote["arquivos"][0]
    assert arq["situacao"] == "ignorada" and "Carta de Correcao" in arq["motivo"]


def test_cancelamento_com_raiz_maiuscula_ainda_funciona(cliente, db):
    """O root tag do evento as vezes chega como ProcEventoNFe (maiusculo) em vez de
    procEventoNFe - o cancelamento nao pode depender de maiuscula/minuscula."""
    ch = chave(9700)
    _sobe(cliente, {"n.xml": nfe(9700, chave_custom=ch, data=HOJE)})
    evento_maiusculo = evento_cancelamento(ch).replace("procEventoNFe", "ProcEventoNFe")
    _sobe(cliente, {"ev.xml": evento_maiusculo})
    nota = db.execute(select(Nota).where(Nota.chave_acesso == ch)).scalars().one()
    assert nota.status == "cancelada"


def test_pacote_com_varias_notas_do_mesmo_produto_recalcula_uma_vez_so(cliente):
    """Reler o historico inteiro do produto por nota (em vez de uma vez por pacote) era o que
    estourava o timeout da importacao em producao - um pacote de mes com dezenas de notas do
    mesmo produto refazia o PEPS inteiro dezenas de vezes (Victor, 28/08/2026)."""
    arquivos = {f"n{i}.xml": nfe(9720 + i, data=HOJE, produto="SUCATA DE ALUMINIO",
                                 ncm="76020000", quantidade=100 + i, valor=2000 + i * 10)
               for i in range(5)}
    with patch("app.services.estoque.recalcular_varios") as mock_recalc:
        lote = _sobe(cliente, arquivos)
    assert lote["importadas"] == 5
    assert mock_recalc.call_count == 1                       # uma chamada so' pro pacote inteiro
    produtos_chamados = set(mock_recalc.call_args[0][1])
    assert len(produtos_chamados) == 1                        # um produto so', mesmo com 5 notas


def test_importar_nota_direto_sem_cache_recalcula_na_hora(db):
    """scripts/pasta_vigiada.py chama importar_nota() direto, nota por nota, sem passar por
    importar_zip - continua precisando do recalculo imediato (nao e' pacote, nao ha' um "final
    do lote" que faca isso depois)."""
    nf = ler(nfe(9740, data=HOJE, produto="SUCATA DE COBRE", ncm="74040000", aliquota=12.0,
                 quantidade=50, valor=1000))
    r = imp.importar_nota(db, nf, "teste", "teste-direto")
    db.commit()
    assert r.situacao == "importada"
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == r.nota_id)).scalars().one()
    assert item.custo_total is not None       # custeio ja' rodou, sem precisar de importar_zip


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


# ----------------------------------------- casamento com nota migrada da planilha (sem chave)
def _nota_migrada(db, *, numero, data, tipo="S", valor=20000.0, quantidade=1000.0,
                  produto="SUCATA DE ALUMINIO", parceiro_nome=None) -> Nota:
    """Simula o que a Fase 1 deixou na base: nota sem chave de acesso, sem CFOP/NCM/origem/UF -
    so' tipo, numero, data, parceiro, quantidade e valor, que e' o que a planilha tinha."""
    produto_row = db.execute(select(Produto).where(Produto.descricao == produto)).scalars().one()
    parceiro_row = Parceiro(nome=parceiro_nome or f"PARCEIRO HISTORICO {numero}", status="migrado")
    db.add(parceiro_row)
    db.flush()
    nota = Nota(numero=numero, serie="1", tipo=tipo, natureza="VENDA", data_emissao=data,
               data_mov=data, parceiro_id=parceiro_row.id, valor_total=valor,
               status="lancada", criado_por="migracao", origem_registro="planilha!L1")
    db.add(nota)
    db.flush()
    db.add(NotaItem(nota_id=nota.id, produto_id=produto_row.id, quantidade=quantidade,
                    valor=valor, base_calculo=valor))
    db.commit()
    db.refresh(nota)
    return nota


def test_nota_migrada_sem_chave_e_complementada_nao_duplicada(cliente, db):
    hist = _nota_migrada(db, numero=9601, data=HOJE)
    lote = _sobe(cliente, {"a.xml": nfe(9601, data=HOJE)})
    assert lote["complementadas"] == 1 and lote["importadas"] == 0
    assert lote["arquivos"][0]["situacao"] == "complementada"

    todas = db.execute(select(Nota).where(Nota.numero == 9601, Nota.tipo == "S")).scalars().all()
    assert len(todas) == 1 and todas[0].id == hist.id      # nao duplicou

    db.refresh(hist)
    assert hist.chave_acesso and len(hist.chave_acesso) == 44
    assert hist.cfop == "5101"
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == hist.id)).scalars().one()
    assert item.ncm == "76020000" and item.origem_merc == "1" and item.bloco_ttd == "2"


def test_complemento_nao_altera_quantidade_nem_valor(cliente, db):
    hist = _nota_migrada(db, numero=9602, data=HOJE, valor=19999.50, quantidade=1000.0)
    lote = _sobe(cliente, {"a.xml": nfe(9602, data=HOJE, valor=20000.0, quantidade=1000.0)})

    # valor diverge alem da tolerancia de centavos: complementa mesmo assim e abre pendencia,
    # nao corrige o valor migrado sozinho.
    assert lote["complementadas"] == 0 and lote["pendentes"] == 1
    db.refresh(hist)
    assert hist.chave_acesso                                # complementou...
    assert float(hist.valor_total) == pytest.approx(19999.50)   # ...mas nao tocou no valor
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == hist.id)).scalars().one()
    assert float(item.quantidade) == pytest.approx(1000.0)
    assert float(item.valor) == pytest.approx(19999.50)
    exc = db.execute(select(Excecao).where(Excecao.nota_id == hist.id)).scalars().all()
    assert any("diverge" in e.descricao for e in exc)


def test_duas_candidatas_historicas_viram_pendencia_sem_escolha(cliente, db):
    h1 = _nota_migrada(db, numero=9603, data=HOJE, parceiro_nome="CLIENTE A")
    h2 = _nota_migrada(db, numero=9603, data=HOJE, parceiro_nome="CLIENTE B")
    lote = _sobe(cliente, {"a.xml": nfe(9603, data=HOJE)})

    assert lote["complementadas"] == 0 and lote["importadas"] == 0 and lote["pendentes"] == 1
    db.refresh(h1); db.refresh(h2)
    assert h1.chave_acesso is None and h2.chave_acesso is None    # nenhuma escolhida sozinha
    todas = db.execute(select(Nota).where(Nota.numero == 9603, Nota.tipo == "S")).scalars().all()
    assert len(todas) == 2                                        # nao criou uma terceira
    exc = db.execute(select(Excecao).where(Excecao.tipo == "casamento_ambiguo")).scalars().all()
    assert any(str(h1.id) in e.descricao and str(h2.id) in e.descricao for e in exc)


def test_granularidade_do_lote_no_xml_nao_importa_pra_casar(cliente, db):
    """Historico agregado (1 item, 1.350 kg) casa com XML detalhado em 2 lotes do mesmo produto
    que somam 1.350 kg - a granularidade do lote no XML nao importa (Victor, 28/08/2026)."""
    hist = _nota_migrada(db, numero=9606, data=HOJE, valor=27000.0, quantidade=1350.0,
                         produto="SUCATA DE COBRE")
    xml = nfe(9606, data=HOJE, produto="SUCATA DE COBRE", ncm="74040000", dest_uf="SP",
             cfop="6101", aliquota=12.0, origem="6", quantidade=1000.0, valor=20000.0)
    xml_2lotes = xml.replace(
        '<det nItem="1">',
        '<det nItem="2"><prod><cProd>002</cProd><xProd>SUCATA DE COBRE</xProd>'
        '<NCM>74040000</NCM><CFOP>6101</CFOP><uCom>KG</uCom><qCom>350.0000</qCom>'
        '<vUnCom>20.000000</vUnCom><vProd>7000.00</vProd></prod>'
        '<imposto><ICMS><ICMS00><orig>6</orig><CST>00</CST><modBC>3</modBC>'
        '<vBC>7000.00</vBC><pICMS>12.00</pICMS><vICMS>840.00</vICMS></ICMS00></ICMS></imposto>'
        '</det><det nItem="1">').replace('<vNF>20000.00</vNF>', '<vNF>27000.00</vNF>')
    lote = _sobe(cliente, {"a.xml": xml_2lotes})
    assert lote["complementadas"] == 1 and lote["pendentes"] == 0
    db.refresh(hist)
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == hist.id)).scalars().one()
    assert float(item.quantidade) == pytest.approx(1350.0)         # nunca mudou
    assert item.bloco_ttd == "1" and item.ncm == "74040000"


def test_quantidade_bate_mas_produto_diverge_da_planilha_segue_o_xml(cliente, db):
    """Mesma quantidade, produto diferente entre planilha e XML: o XML manda (Victor,
    28/08/2026) - complementa corrigindo o produto e abre pendencia informativa, nunca muda a
    quantidade."""
    hist = _nota_migrada(db, numero=9607, data=HOJE, valor=16500.0, quantidade=500.0,
                         produto="SUCATA DE MAGNESIO")
    lote = _sobe(cliente, {"a.xml": nfe(9607, data=HOJE, produto="LINGOTE DE MAGNESIO",
                                        ncm="81041100", quantidade=500.0, valor=16500.0,
                                        dest_uf="SP", cfop="6101", aliquota=4.0, origem="6")})
    assert lote["complementadas"] == 0 and lote["pendentes"] == 1
    db.refresh(hist)
    item = db.execute(select(NotaItem).where(NotaItem.nota_id == hist.id)).scalars().one()
    assert db.get(Produto, item.produto_id).descricao == "LINGOTE DE MAGNESIO"
    assert float(item.quantidade) == pytest.approx(500.0)          # quantidade nunca mudou
    exc = db.execute(select(Excecao).where(Excecao.nota_id == hist.id)).scalars().all()
    assert any("corrigido conforme o XML" in e.descricao for e in exc)


def test_nota_sem_historico_correspondente_continua_entrando_como_nova(cliente, db):
    lote = _sobe(cliente, {"a.xml": nfe(9604, data=HOJE)})
    assert lote["importadas"] == 1 and lote["complementadas"] == 0
    assert lote["arquivos"][0]["situacao"] == "importada"


def test_reimportar_pacote_apos_complemento_nao_faz_nada(cliente, db):
    _nota_migrada(db, numero=9605, data=HOJE)
    xml = nfe(9605, data=HOJE)
    primeiro = _sobe(cliente, {"a.xml": xml})
    assert primeiro["complementadas"] == 1

    segundo = _sobe(cliente, {"a.xml": xml})
    assert segundo["duplicadas"] == 1
    assert segundo["complementadas"] == 0 and segundo["importadas"] == 0

    todas = db.execute(select(Nota).where(Nota.numero == 9605, Nota.tipo == "S")).scalars().all()
    assert len(todas) == 1                                        # a reimportacao nao criou nada


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
