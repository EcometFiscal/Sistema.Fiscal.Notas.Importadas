import React, { useEffect, useState } from 'react'
import { api, kg, rs, pct, hoje } from '../api'

const ITEM_VAZIO = { produto_id: '', quantidade: '', valor: '', bloco_ttd: '' }

export default function Lancamento({ aoLancar }) {
  const [produtos, setProdutos] = useState([])
  const [blocos, setBlocos] = useState([])
  const [parceiros, setParceiros] = useState([])
  const [form, setForm] = useState({
    tipo: 'S', numero: '', serie: '1', natureza: 'VENDA', data_mov: hoje(),
    parceiro: '', chave_acesso: '', cfop: '', observacao: '',
  })
  const [itens, setItens] = useState([{ ...ITEM_VAZIO }])
  const [saldos, setSaldos] = useState({})
  const [avisos, setAvisos] = useState([])
  const [justificativa, setJustificativa] = useState('')
  const [confirmarDup, setConfirmarDup] = useState(false)
  const [erro, setErro] = useState(null)
  const [sucesso, setSucesso] = useState(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    api.produtos().then(setProdutos)
    api.blocos().then((b) => setBlocos(b.blocos))
    api.parceiros().then(setParceiros)
  }, [])

  // saldo do produto na data escolhida, para o usuario ver antes de gravar
  useEffect(() => {
    const ids = itens.map((i) => i.produto_id).filter(Boolean)
    ids.forEach((id) => {
      api.saldo(id, form.data_mov).then((s) => setSaldos((v) => ({ ...v, [`${id}|${form.data_mov}`]: s.saldo })))
    })
  }, [itens.map((i) => i.produto_id).join(','), form.data_mov])

  const saldoDe = (id) => saldos[`${id}|${form.data_mov}`]
  const mudaItem = (idx, campo, valor) =>
    setItens((v) => v.map((it, i) => (i === idx ? { ...it, [campo]: valor } : it)))

  const exigeJustificativa = avisos.some((a) => a.exige === 'justificativa')
  const exigeConfirmacao = avisos.some((a) => a.exige === 'confirmar_duplicata')

  async function enviar(e) {
    e.preventDefault()
    setEnviando(true); setErro(null); setSucesso(null)
    const corpo = {
      ...form,
      numero: Number(form.numero),
      chave_acesso: form.chave_acesso || null,
      cfop: form.cfop || null,
      parceiro: form.parceiro || null,
      justificativa: justificativa || null,
      confirmar_duplicata: confirmarDup,
      itens: itens.filter((i) => i.produto_id && i.quantidade).map((i) => ({
        produto_id: Number(i.produto_id),
        quantidade: Number(i.quantidade),
        valor: i.valor === '' ? null : Number(i.valor),
        bloco_ttd: form.tipo === 'S' && i.bloco_ttd ? i.bloco_ttd : null,
      })),
    }
    try {
      const r = await api.lancar(corpo)
      setSucesso(r); setAvisos(r.avisos || []); setJustificativa(''); setConfirmarDup(false)
      setForm((f) => ({ ...f, numero: '', chave_acesso: '', observacao: '' }))
      setItens([{ ...ITEM_VAZIO }])
      aoLancar?.()
    } catch (ex) {
      if (ex.status === 422) setAvisos(ex.corpo.detail.avisos || [])
      else setErro(ex.corpo?.detail?.mensagem || 'Não foi possível gravar o lançamento.')
    } finally {
      setEnviando(false)
    }
  }

  return (
    <form onSubmit={enviar}>
      <div className="cartao">
        <h2>Lançamento único</h2>
        <p className="ajuda">
          A nota é digitada uma vez. O estoque e a apuração saem os dois deste mesmo lançamento —
          eles não podem discordar entre si.
        </p>

        <div className="grade g4">
          <div>
            <label>Operação</label>
            <select value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value,
              natureza: e.target.value === 'E' ? 'IMPORTACAO' : 'VENDA' })}>
              <option value="S">Saída</option>
              <option value="E">Entrada</option>
            </select>
          </div>
          <div>
            <label>Natureza</label>
            <select value={form.natureza} onChange={(e) => setForm({ ...form, natureza: e.target.value })}>
              {form.tipo === 'S'
                ? <><option value="VENDA">Venda</option><option value="REMESSA">Remessa</option></>
                : <><option value="IMPORTACAO">Importação</option>
                    <option value="DEVOLUCAO">Devolução de venda</option>
                    <option value="COMPRA">Compra</option></>}
            </select>
          </div>
          <div><label>Número da NF</label>
            <input required inputMode="numeric" value={form.numero}
                   onChange={(e) => setForm({ ...form, numero: e.target.value })} /></div>
          <div><label>Série</label>
            <input value={form.serie} onChange={(e) => setForm({ ...form, serie: e.target.value })} /></div>
        </div>

        <div className="grade g3" style={{ marginTop: 14 }}>
          <div><label>Data do movimento</label>
            <input type="date" required max={hoje()} value={form.data_mov}
                   onChange={(e) => setForm({ ...form, data_mov: e.target.value })} /></div>
          <div>
            <label>{form.tipo === 'S' ? 'Cliente' : 'Fornecedor'}</label>
            <input list="parceiros" value={form.parceiro} placeholder="digite ou escolha"
                   onChange={(e) => setForm({ ...form, parceiro: e.target.value })} />
            <datalist id="parceiros">
              {parceiros.map((p) => <option key={p.id} value={p.nome} />)}
            </datalist>
          </div>
          <div><label>Chave de acesso (44 dígitos, opcional)</label>
            <input maxLength={44} value={form.chave_acesso} placeholder="entra automática na Fase 5"
                   onChange={(e) => setForm({ ...form, chave_acesso: e.target.value })} /></div>
        </div>
      </div>

      <div className="cartao">
        <h2>Itens</h2>
        <p className="ajuda">
          O saldo do produto na data escolhida aparece embaixo de cada linha, antes de gravar.
        </p>
        {itens.map((item, idx) => {
          const saldo = saldoDe(item.produto_id)
          const falta = form.tipo === 'S' && saldo != null && item.quantidade
            ? Number(item.quantidade) - saldo : 0
          return (
            <div className="linha-item" key={idx}>
              <div>
                <label>Produto</label>
                <select value={item.produto_id} onChange={(e) => mudaItem(idx, 'produto_id', e.target.value)}>
                  <option value="">selecione…</option>
                  {produtos.map((p) => <option key={p.id} value={p.id}>{p.descricao}</option>)}
                </select>
                {item.produto_id && saldo != null && (
                  <div className={`saldo-dica ${falta > 0 ? 'falta' : ''}`}>
                    saldo em {form.data_mov.split('-').reverse().join('/')}: {kg(saldo)} kg
                    {falta > 0 && ` · faltam ${kg(falta)} kg`}
                  </div>
                )}
              </div>
              <div><label>Quantidade (kg)</label>
                <input inputMode="decimal" value={item.quantidade}
                       onChange={(e) => mudaItem(idx, 'quantidade', e.target.value)} /></div>
              <div><label>Valor (R$)</label>
                <input inputMode="decimal" value={item.valor}
                       onChange={(e) => mudaItem(idx, 'valor', e.target.value)} /></div>
              <div>
                <label>Bloco TTD</label>
                <select disabled={form.tipo === 'E' && form.natureza !== 'DEVOLUCAO'}
                        value={item.bloco_ttd} onChange={(e) => mudaItem(idx, 'bloco_ttd', e.target.value)}>
                  <option value="">—</option>
                  {blocos.map((b) => (
                    <option key={b.bloco} value={b.bloco}>
                      {b.bloco} · {b.descricao} · carga {pct(b.carga_efetiva * 100)}
                    </option>
                  ))}
                </select>
              </div>
              <button type="button" className="icone" title="remover item"
                      onClick={() => setItens((v) => v.filter((_, i) => i !== idx))}>×</button>
            </div>
          )
        })}
        <button type="button" className="leve" style={{ marginTop: 14 }}
                onClick={() => setItens((v) => [...v, { ...ITEM_VAZIO }])}>+ adicionar item</button>
      </div>

      {avisos.length > 0 && (
        <div className="cartao">
          <h2>Confirmações</h2>
          {avisos.map((a, i) => (
            <div className={`aviso ${a.exige ? 'alerta' : 'ok'}`} key={i}>
              <b>{a.codigo === 'saldo_insuficiente' ? 'Saldo insuficiente' : 'Possível duplicata'}</b>
              {a.mensagem}
            </div>
          ))}
          {exigeJustificativa && (
            <div style={{ marginTop: 10 }}>
              <label>Justificativa (fica registrada com seu usuário)</label>
              <textarea rows={2} value={justificativa} onChange={(e) => setJustificativa(e.target.value)}
                        placeholder="ex.: entrada de importação ainda sem XML, será lançada nesta semana" />
            </div>
          )}
          {exigeConfirmacao && (
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12,
                            textTransform: 'none', fontSize: 14, color: 'inherit' }}>
              <input type="checkbox" style={{ width: 16 }} checked={confirmarDup}
                     onChange={(e) => setConfirmarDup(e.target.checked)} />
              Confirmo que é outro documento, não uma digitação repetida
            </label>
          )}
        </div>
      )}

      {erro && <div className="aviso erro"><b>Não gravou</b>{erro}</div>}

      {sucesso && (
        <div className="cartao">
          <div className="aviso ok">
            <b>NF {sucesso.nota.numero} gravada (#{sucesso.nota.id})</b>
            O estoque e a apuração abaixo já refletem este lançamento.
          </div>
          <div className="grade g2">
            <div>
              <h3 style={{ fontSize: 13, color: '#6b7280', textTransform: 'uppercase' }}>Estoque atualizado</h3>
              <table><tbody>
                {sucesso.estoque.map((p) => (
                  <tr key={p.produto_id}>
                    <td>{p.produto}</td>
                    <td className="dir num">{kg(p.saldo_kg)} kg</td>
                    <td className="dir num">{rs(p.saldo_rs)}</td>
                  </tr>
                ))}
              </tbody></table>
            </div>
            <div>
              <h3 style={{ fontSize: 13, color: '#6b7280', textTransform: 'uppercase' }}>
                Apuração {sucesso.apuracao?.competencia}
              </h3>
              <table><tbody>
                <tr><td>Base beneficiada</td><td className="dir num">{rs(sucesso.apuracao?.base_beneficiada)}</td></tr>
                <tr><td>ICMS a recolher</td><td className="dir num">{rs(sucesso.apuracao?.icms_recolher)}</td></tr>
                <tr><td>Fundo Social</td><td className="dir num">{rs(sucesso.apuracao?.fundo_social)}</td></tr>
                <tr><td>Fundo Educação</td><td className="dir num">{rs(sucesso.apuracao?.fundo_educacao)}</td></tr>
                <tr><td>Carga efetiva</td><td className="dir num">{pct(sucesso.apuracao?.carga_efetiva)}</td></tr>
              </tbody></table>
            </div>
          </div>
        </div>
      )}

      <button className="acao" disabled={enviando}>
        {enviando ? 'Gravando…' : 'Gravar lançamento'}
      </button>
    </form>
  )
}
