import React, { useEffect, useState } from 'react'
import { api, baixar, kg, rs, data as fdata } from '../api'

export default function Estoque({ recarga }) {
  const [pos, setPos] = useState(null)
  const [aberto, setAberto] = useState(null)
  const [razao, setRazao] = useState([])

  useEffect(() => { api.posicao().then(setPos) }, [recarga])

  function abrir(p) {
    if (aberto === p.produto_id) { setAberto(null); return }
    setAberto(p.produto_id)
    api.razao(p.produto_id).then((r) => setRazao(r.slice(-60).reverse()))
  }

  if (!pos) return <div className="vazio">carregando…</div>

  return (
    <>
      <div className="kpis">
        <div className="kpi">
          <div className="rot">Estoque total</div>
          <div className="val num">{kg(pos.total_kg)} kg</div>
          <div className="obs">posição em {fdata(pos.data)}</div>
        </div>
        <div className="kpi">
          <div className="rot">Estoque valorizado</div>
          <div className="val num">{rs(pos.total_rs)}</div>
          <div className="obs">custeio PEPS — a planilha nunca teve isto</div>
        </div>
        <div className="kpi">
          <div className="rot">Produtos</div>
          <div className="val num">{pos.produtos.length}</div>
          <div className="obs">descrição canônica, sem variação de acento</div>
        </div>
      </div>

      <div className="cartao" style={{ marginTop: 20 }}>
        <h2>Saldo por produto</h2>
        <p className="ajuda">Clique em um produto para ver o extrato com saldo corrido.</p>
        <button type="button" className="leve" style={{ marginBottom: 14 }}
                onClick={() => baixar('/exportar/estoque')}>Exportar estoque fiscal em Excel</button>
        <div className="rolagem">
          <table>
            <thead>
              <tr>
                <th>Produto</th><th className="dir">Saldo (kg)</th><th className="dir">Saldo (R$)</th>
                <th className="dir">Custo médio</th>
              </tr>
            </thead>
            <tbody>
              {pos.produtos.map((p) => (
                <React.Fragment key={p.produto_id}>
                  <tr onClick={() => abrir(p)} style={{ cursor: 'pointer' }}>
                    <td>{p.produto}</td>
                    <td className="dir num">{kg(p.saldo_kg)}</td>
                    <td className="dir num">{rs(p.saldo_rs)}</td>
                    <td className="dir num">{p.custo_medio ? rs(p.custo_medio) + '/kg' : '—'}</td>
                  </tr>
                  {aberto === p.produto_id && (
                    <tr><td colSpan={4} style={{ background: '#fafbfc' }}>
                      <table>
                        <thead><tr>
                          <th>Data</th><th>Movimento</th><th>NF</th><th>Parceiro</th>
                          <th className="dir">Qtd</th><th className="dir">Saldo</th>
                        </tr></thead>
                        <tbody>
                          {razao.map((l, i) => (
                            <tr key={i}>
                              <td className="num">{fdata(l.data)}</td>
                              <td><span className={`etiq ${l.natureza === 'ACERTO' ? 'acerto' : l.tipo.toLowerCase()}`}>
                                {l.natureza === 'ACERTO' ? 'acerto' : l.tipo === 'E' ? 'entrada' : 'saída'}
                              </span></td>
                              <td className="num">{l.numero || '—'}</td>
                              <td>{l.parceiro || '—'}</td>
                              <td className="dir num">{kg(l.quantidade)}</td>
                              <td className="dir num">{kg(l.saldo)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td></tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
