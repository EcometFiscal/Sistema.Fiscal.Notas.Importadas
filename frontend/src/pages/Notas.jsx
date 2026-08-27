import React, { useEffect, useState } from 'react'
import { api, kg, rs, data as fdata } from '../api'

export default function Notas({ recarga, aoMudar }) {
  const [notas, setNotas] = useState([])
  const [filtro, setFiltro] = useState({ tipo: '', q: '' })

  const carregar = () => {
    const p = { limite: 200 }
    if (filtro.tipo) p.tipo = filtro.tipo
    if (filtro.q) p.q = filtro.q
    api.notas(p).then(setNotas)
  }
  useEffect(carregar, [recarga, filtro.tipo])

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
          <label>Operação</label>
          <select value={filtro.tipo} onChange={(e) => setFiltro({ ...filtro, tipo: e.target.value })}>
            <option value="">todas</option><option value="E">entradas</option><option value="S">saídas</option>
          </select>
        </div>
        <div>
          <label>Número da NF</label>
          <input value={filtro.q} onChange={(e) => setFiltro({ ...filtro, q: e.target.value })}
                 onKeyDown={(e) => e.key === 'Enter' && carregar()} placeholder="enter para buscar" />
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
            {!notas.length && <tr><td colSpan={8} className="vazio">nenhuma nota encontrada</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
