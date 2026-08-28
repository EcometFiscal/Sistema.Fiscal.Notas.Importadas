import React, { useEffect, useState } from 'react'
import { api, pct, data as fdata } from '../api'

const VAZIO = { ncm: '', ambito: 'interestadual', bloco: '2', descricao: '', aliquota: '',
                aliq_presumido: '', carga_efetiva: '', vigencia_inicio: '' }

export default function Regras() {
  const [regras, setRegras] = useState([])
  const [produtos, setProdutos] = useState([])
  const [form, setForm] = useState(VAZIO)
  const [erro, setErro] = useState(null)
  const [ok, setOk] = useState(null)

  const carregar = () => {
    api.regras().then(setRegras)
    api.produtos().then((ps) => setProdutos(ps.filter((p) => p.ncm)))
  }
  useEffect(carregar, [])

  const produtoDoNcm = (ncm) => produtos.find((p) => p.ncm === ncm)

  function escolherNcm(ncm) {
    const p = produtoDoNcm(ncm)
    setForm({ ...form, ncm,
             descricao: p ? `${form.ambito === 'interna' ? 'Interna' : 'Interestadual'} — ${p.descricao}` : form.descricao })
  }

  async function salvar(e) {
    e.preventDefault(); setErro(null); setOk(null)
    try {
      await api.novaRegra({
        ...form,
        aliquota: Number(form.aliquota) / 100,
        aliq_presumido: Number(form.aliq_presumido) / 100,
        carga_efetiva: Number(form.carga_efetiva) / 100,
      })
      setForm(VAZIO); setOk('Vigência criada para esse NCM + âmbito. A anterior foi encerrada no dia anterior.')
      carregar()
    } catch (ex) { setErro(ex.corpo?.detail?.mensagem || 'não foi possível gravar') }
  }

  return (
    <>
      <div className="cartao">
        <h2>Alíquotas por NCM e âmbito</h2>
        <p className="ajuda">
          O bloco do TTD é decidido pelo NCM do produto e pelo âmbito da operação (interna em SC ou
          interestadual), não mais pelo CFOP. A virada de fase é um registro novo com data, não uma
          alteração no código — meses antigos continuam calculando com a alíquota que valia na data
          deles.
        </p>
        <div className="rolagem">
          <table>
            <thead><tr>
              <th>NCM</th><th>Âmbito</th><th>Bloco</th><th>Operação</th>
              <th className="dir">ICMS normal</th><th className="dir">Presumido</th>
              <th className="dir">Carga efetiva</th><th>Vigência</th><th>Alterado por</th>
            </tr></thead>
            <tbody>
              {regras.map((r) => (
                <tr key={r.id}>
                  <td className="num">{r.ncm}</td>
                  <td>{r.ambito === 'interna' ? 'Interna' : 'Interestadual'}</td>
                  <td>{r.bloco}</td><td>{r.descricao}</td>
                  <td className="dir num">{pct(r.aliquota * 100)}</td>
                  <td className="dir num">{pct(r.aliq_presumido * 100)}</td>
                  <td className="dir num">{pct(r.carga_efetiva * 100)}</td>
                  <td className="num">
                    {fdata(r.vigencia_inicio)} → {r.vigencia_fim ? fdata(r.vigencia_fim) : 'em vigor'}
                  </td>
                  <td>{r.alterado_por || '—'}</td>
                </tr>
              ))}
              {!regras.length && <tr><td colSpan={9} className="vazio">nenhuma regra cadastrada</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <form className="cartao" onSubmit={salvar}>
        <h2>Ajustar alíquota de um NCM</h2>
        <p className="ajuda">
          Escolha o produto (o NCM vem sozinho) e o âmbito da operação. A vigência anterior desse
          mesmo NCM + âmbito é encerrada no dia anterior, automaticamente — nunca sobrescrita.
        </p>
        <div className="grade g3">
          <div><label>Produto / NCM</label>
            <select required value={form.ncm} onChange={(e) => escolherNcm(e.target.value)}>
              <option value="">selecione</option>
              {produtos.map((p) => (
                <option key={p.id} value={p.ncm}>{p.descricao} — {p.ncm}</option>
              ))}
            </select></div>
          <div><label>Âmbito da operação</label>
            <select value={form.ambito}
                    onChange={(e) => setForm({ ...form, ambito: e.target.value })}>
              <option value="interestadual">Interestadual</option>
              <option value="interna">Interna (dentro de SC)</option>
            </select></div>
          <div><label>Bloco (layout da contabilidade)</label>
            <select value={form.bloco} onChange={(e) => setForm({ ...form, bloco: e.target.value })}>
              <option value="1">1 — Interestadual 12%</option>
              <option value="2">2 — Interestadual importado</option>
              <option value="3">3 — Interna</option>
            </select></div>
          <div><label>Descrição</label>
            <input required value={form.descricao}
                   onChange={(e) => setForm({ ...form, descricao: e.target.value })} /></div>
          <div><label>Início da vigência</label>
            <input type="date" required value={form.vigencia_inicio}
                   onChange={(e) => setForm({ ...form, vigencia_inicio: e.target.value })} /></div>
          <div><label>ICMS normal (%)</label>
            <input required inputMode="decimal" value={form.aliquota}
                   onChange={(e) => setForm({ ...form, aliquota: e.target.value })} /></div>
          <div><label>ICMS presumido (%)</label>
            <input required inputMode="decimal" value={form.aliq_presumido}
                   onChange={(e) => setForm({ ...form, aliq_presumido: e.target.value })} /></div>
          <div><label>Carga efetiva (%)</label>
            <input required inputMode="decimal" value={form.carga_efetiva}
                   onChange={(e) => setForm({ ...form, carga_efetiva: e.target.value })} /></div>
        </div>
        {erro && <div className="aviso erro"><b>Não gravou</b>{erro}</div>}
        {ok && <div className="aviso ok">{ok}</div>}
        <button className="acao" style={{ marginTop: 14 }}>Criar vigência</button>
      </form>
    </>
  )
}
