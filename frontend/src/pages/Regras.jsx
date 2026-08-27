import React, { useEffect, useState } from 'react'
import { api, pct, data as fdata } from '../api'

const VAZIO = { bloco: '1', descricao: '', aliquota: '', aliq_presumido: '', carga_efetiva: '',
                vigencia_inicio: '' }

export default function Regras() {
  const [regras, setRegras] = useState([])
  const [form, setForm] = useState(VAZIO)
  const [erro, setErro] = useState(null)
  const [ok, setOk] = useState(null)

  const carregar = () => api.regras().then(setRegras)
  useEffect(() => { carregar() }, [])

  async function salvar(e) {
    e.preventDefault(); setErro(null); setOk(null)
    try {
      await api.novaRegra({
        ...form,
        aliquota: Number(form.aliquota) / 100,
        aliq_presumido: Number(form.aliq_presumido) / 100,
        carga_efetiva: Number(form.carga_efetiva) / 100,
      })
      setForm(VAZIO); setOk('Vigência criada. A anterior foi encerrada no dia anterior.'); carregar()
    } catch (ex) { setErro(ex.corpo?.detail?.mensagem || 'não foi possível gravar') }
  }

  return (
    <>
      <div className="cartao">
        <h2>Alíquotas por vigência</h2>
        <p className="ajuda">
          A virada de fase do TTD é um registro novo, não uma alteração no código. Meses antigos
          continuam calculando com a regra que valia na data deles.
        </p>
        <div className="rolagem">
          <table>
            <thead><tr>
              <th>Bloco</th><th>Operação</th><th className="dir">Alíquota</th>
              <th className="dir">Presumido</th><th className="dir">Carga efetiva</th>
              <th>Vigência</th><th>Alterado por</th>
            </tr></thead>
            <tbody>
              {regras.map((r) => (
                <tr key={r.id}>
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
            </tbody>
          </table>
        </div>
      </div>

      <form className="cartao" onSubmit={salvar}>
        <h2>Nova vigência</h2>
        <p className="ajuda">A vigência anterior do mesmo bloco é encerrada no dia anterior, automaticamente.</p>
        <div className="grade g3">
          <div><label>Bloco</label>
            <select value={form.bloco} onChange={(e) => setForm({ ...form, bloco: e.target.value })}>
              <option value="1">1 — Interestadual</option>
              <option value="2">2 — Interestadual importado</option>
              <option value="3">3 — Interna</option>
            </select></div>
          <div><label>Descrição</label>
            <input required value={form.descricao}
                   onChange={(e) => setForm({ ...form, descricao: e.target.value })} /></div>
          <div><label>Início da vigência</label>
            <input type="date" required value={form.vigencia_inicio}
                   onChange={(e) => setForm({ ...form, vigencia_inicio: e.target.value })} /></div>
          <div><label>Alíquota (%)</label>
            <input required inputMode="decimal" value={form.aliquota}
                   onChange={(e) => setForm({ ...form, aliquota: e.target.value })} /></div>
          <div><label>Alíquota do presumido (%)</label>
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
