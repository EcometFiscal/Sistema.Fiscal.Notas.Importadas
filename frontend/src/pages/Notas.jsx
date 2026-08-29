import React, { useEffect, useState } from 'react'
import { api, kg, rs, data as fdata } from '../api'

const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto',
              'setembro', 'outubro', 'novembro', 'dezembro']
const compHoje = () => new Date().toISOString().slice(0, 7)
const nomeComp = (c) => { const [a, m] = c.split('-').map(Number); return `${MESES[m - 1]} de ${a}` }
function limitesDoMes(c) {
  const [a, m] = c.split('-').map(Number)
  return { de: `${c}-01`, ate: new Date(a, m, 0).toISOString().slice(0, 10) }
}

export default function Notas({ recarga, aoMudar }) {
  const [notas, setNotas] = useState([])
  const [filtro, setFiltro] = useState({ tipo: '', q: '' })
  const [comp, setComp] = useState(compHoje())
  const [competencias, setCompetencias] = useState([])

  const carregar = () => {
    const p = { limite: 200 }
    if (filtro.tipo) p.tipo = filtro.tipo
    if (filtro.q) p.q = filtro.q
    // Busca por numero vale pra qualquer mes - so' filtra por competencia quando nao ha busca.
    else if (comp) Object.assign(p, limitesDoMes(comp))
    api.notas(p).then(setNotas)
    api.competencias().then(setCompetencias).catch(() => {})
  }
  useEffect(carregar, [recarga, filtro.tipo, comp])

  async function cancelar(n) {
    const motivo = prompt(`Cancelar a NF ${n.numero}. Motivo:`)
    if (!motivo) return
    await api.cancelar(n.id, motivo)
    carregar(); aoMudar?.()
  }

  return (
    <div className="cartao">
      <h2>Notas lançadas</h2>
      <p className="ajuda">Cancelar uma nota devolve o saldo e refaz o custeio do produto na hora.</p>
      <div className="grade g3" style={{ marginBottom: 16 }}>
        <div>
          <label>Mês</label>
          <select value={comp} onChange={(e) => setComp(e.target.value)}>
            <option value="">todos os meses</option>
            {!competencias.some((c) => c.competencia === comp) && comp && (
              <option value={comp}>{nomeComp(comp)}</option>)}
            {competencias.map((c) => (
              <option key={c.competencia} value={c.competencia}>
                {nomeComp(c.competencia)}{c.status === 'fechada' ? ' · fechada' : ''}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label>Operação</label>
          <select value={filtro.tipo} onChange={(e) => setFiltro({ ...filtro, tipo: e.target.value })}>
            <option value="">todas</option><option value="E">entradas</option><option value="S">saídas</option>
          </select>
        </div>
        <div>
          <label>Número da NF</label>
          <input value={filtro.q} onChange={(e) => setFiltro({ ...filtro, q: e.target.value })}
                 onKeyDown={(e) => e.key === 'Enter' && carregar()}
                 placeholder="enter para buscar em todos os meses" />
        </div>
      </div>
      <div className="rolagem">
        <table>
          <thead><tr>
            <th>Data</th><th>Op.</th><th>NF</th><th>Parceiro</th><th>Produtos</th>
            <th className="dir">Qtd (kg)</th><th className="dir">Valor</th><th></th>
          </tr></thead>
          <tbody>
            {notas.map((n) => (
              <tr key={n.id}>
                <td className="num">{fdata(n.data_mov)}</td>
                <td>
                  <span className={`etiq ${n.status === 'cancelada' ? 'cancelada'
                    : n.natureza === 'ACERTO' ? 'acerto' : n.tipo.toLowerCase()}`}>
                    {n.status === 'cancelada' ? 'cancelada'
                      : n.natureza === 'ACERTO' ? 'acerto' : n.tipo === 'E' ? 'entrada' : 'saída'}
                  </span>
                </td>
                <td className="num">{n.numero || '—'}</td>
                <td>{n.parceiro?.nome || '—'}</td>
                <td>{n.itens.length} item{n.itens.length > 1 ? 'ns' : ''}</td>
                <td className="dir num">{kg(n.itens.reduce((s, i) => s + i.quantidade, 0))}</td>
                <td className="dir num">{rs(n.valor_total)}</td>
                <td className="dir">
                  {n.status === 'lancada' && n.natureza !== 'ACERTO' && (
                    <button className="leve" onClick={() => cancelar(n)}>cancelar</button>
                  )}
                </td>
              </tr>
            ))}
            {!notas.length && (
              <tr><td colSpan={8} className="vazio">
                nenhuma nota encontrada{comp && !filtro.q ? ` em ${nomeComp(comp)}` : ''}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
