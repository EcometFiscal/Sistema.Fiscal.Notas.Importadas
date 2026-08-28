import React, { useEffect, useState } from 'react'
import { api, baixar, kg, rs } from '../api'

const ROTULOS = {
  saida_sem_saldo: 'Saída sem saldo',
  acerto_automatico: 'Acerto de estoque',
  nota_sem_data: 'Nota sem data',
  duplicata_confirmada: 'Duplicata confirmada',
}

export default function Excecoes({ recarga }) {
  const [lista, setLista] = useState([])
  useEffect(() => { api.excecoes().then(setLista) }, [recarga])

  const porTipo = lista.reduce((a, e) => ({ ...a, [e.tipo]: (a[e.tipo] || 0) + 1 }), {})

  return (
    <>
      <div className="kpis">
        {Object.entries(porTipo).map(([t, n]) => (
          <div className="kpi" key={t}>
            <div className="rot">{ROTULOS[t] || t}</div>
            <div className="val num">{n}</div>
          </div>
        ))}
        {!lista.length && <div className="kpi"><div className="rot">Pendências</div>
          <div className="val num">0</div><div className="obs">nada em aberto</div></div>}
      </div>

      <div className="cartao" style={{ marginTop: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <h2>Pendências</h2>
          <button type="button" className="leve" onClick={() => baixar('/exportar/pendencias')}>
            Relatório de erros em Excel
          </button>
        </div>
        <p className="ajuda">
          Aqui fica tudo que o sistema aceitou mas alguém precisa olhar — de apuração, estoque ou
          importação de dados. Na planilha isto não existia: o número saía errado e ninguém ficava
          sabendo.
        </p>
        <div className="rolagem">
          <table>
            <thead><tr>
              <th>Tipo</th><th>O que aconteceu</th><th>Justificativa</th>
              <th className="dir">Qtd</th><th className="dir">Valor</th><th>Usuário</th>
            </tr></thead>
            <tbody>
              {lista.map((e) => (
                <tr key={e.id}>
                  <td><span className="etiq">{ROTULOS[e.tipo] || e.tipo}</span></td>
                  <td style={{ maxWidth: 520 }}>{e.descricao}</td>
                  <td style={{ maxWidth: 280, color: '#6b7280' }}>{e.justificativa || '—'}</td>
                  <td className="dir num">{e.quantidade ? kg(e.quantidade) : '—'}</td>
                  <td className="dir num">{e.valor ? rs(e.valor) : '—'}</td>
                  <td>{e.criado_por}</td>
                </tr>
              ))}
              {!lista.length && <tr><td colSpan={6} className="vazio">nenhuma pendência</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
