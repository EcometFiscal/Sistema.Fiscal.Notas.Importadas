import React, { useEffect, useState } from 'react'
import { api, baixar, rs, pct, data as fdata } from '../api'

const compHoje = () => new Date().toISOString().slice(0, 7)
const dataHora = (v) => (v ? new Date(v).toLocaleString('pt-BR') : '—')

export default function Apuracao({ recarga, aoMudar }) {
  const [comp, setComp] = useState('2026-07')
  const [ap, setAp] = useState(null)
  const [competencias, setCompetencias] = useState([])
  const [historico, setHistorico] = useState([])
  const [erro, setErro] = useState(null)

  const carregar = () => {
    api.apuracao(comp).then(setAp).catch(() => setAp(null))
    api.historico(comp).then(setHistorico).catch(() => setHistorico([]))
    api.competencias().then(setCompetencias).catch(() => {})
  }
  useEffect(carregar, [comp, recarga])

  const fechada = ap?.fechamento?.status === 'fechada'

  async function fechar() {
    if (!confirm(`Fechar ${comp}? Depois disso, lançar nesta competência exige reabertura com motivo.`)) return
    setErro(null)
    try { await api.fechar(comp); carregar(); aoMudar?.() }
    catch (e) { setErro(e.corpo?.detail?.mensagem || 'não foi possível fechar') }
  }
  async function reabrir() {
    const motivo = prompt('Motivo da reabertura (fica registrado com seu usuário):')
    if (!motivo) return
    setErro(null)
    try { await api.reabrir(comp, motivo); carregar(); aoMudar?.() }
    catch (e) { setErro(e.corpo?.detail?.mensagem || 'não foi possível reabrir') }
  }

  return (
    <>
      <div className="cartao">
        <h2>Apuração da competência</h2>
        <p className="ajuda">
          Derivada dos lançamentos, nunca congelada em célula. Recalcular julho em dezembro devolve
          o mesmo número — a menos que alguém tenha mexido nos lançamentos, e aí o sistema avisa.
        </p>
        <div className="grade g3">
          <div>
            <label>Competência</label>
            <select value={comp} onChange={(e) => setComp(e.target.value)}>
              {!competencias.some((c) => c.competencia === comp) && <option value={comp}>{comp}</option>}
              {competencias.map((c) => (
                <option key={c.competencia} value={c.competencia}>
                  {c.competencia} {c.status === 'fechada' ? '· fechada' : ''}
                </option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            {fechada
              ? <button type="button" className="leve" onClick={reabrir}>Reabrir competência</button>
              : <button type="button" className="acao" onClick={fechar}>Fechar competência</button>}
            <button type="button" className="leve" onClick={() => baixar(`/exportar/apuracao/${comp}`)}>
              Exportar Excel
            </button>
          </div>
        </div>
        {fechada && (
          <div className="aviso ok" style={{ marginTop: 14 }}>
            <b>Competência fechada</b>
            Fechada em {dataHora(ap.fechamento.fechada_em)} por {ap.fechamento.fechada_por}.
            ICMS congelado no fechamento: {rs(ap.fechamento.icms_congelado)}. Lançar com data dentro
            deste mês exige reabertura registrada.
          </div>
        )}
        {ap?.conferencia && !ap.conferencia.coerente && (
          <div className="aviso alerta" style={{ marginTop: 14 }}>
            <b>Os lançamentos mudaram depois do fechamento</b>
            ICMS congelado {rs(ap.conferencia.congelado.icms_recolher)} · recalculado agora{' '}
            {rs(ap.conferencia.atual.icms_recolher)} · diferença{' '}
            {rs(ap.conferencia.diferencas.icms_recolher)}.
          </div>
        )}
        {erro && <div className="aviso erro"><b>Não deu</b>{erro}</div>}
      </div>

      {!ap ? <div className="vazio">sem lançamentos nesta competência</div> : (
        <>
          <div className="kpis">
            <div className="kpi"><div className="rot">Base beneficiada</div>
              <div className="val num">{rs(ap.base_beneficiada)}</div></div>
            <div className="kpi"><div className="rot">ICMS a recolher</div>
              <div className="val num">{rs(ap.icms_recolher)}</div>
              <div className="obs">(débito + estorno) − (presumido + devolução)</div></div>
            <div className="kpi"><div className="rot">Fundo Social</div>
              <div className="val num">{rs(ap.fundo_social)}</div></div>
            <div className="kpi"><div className="rot">Fundo Educação</div>
              <div className="val num">{rs(ap.fundo_educacao)}</div></div>
            <div className="kpi"><div className="rot">Carga efetiva</div>
              <div className="val num">{pct(ap.carga_efetiva)}</div>
              <div className="obs">média do mês</div></div>
          </div>

          <div className="cartao" style={{ marginTop: 20 }}>
            <h2>Por bloco</h2>
            <div className="rolagem">
              <table>
                <thead><tr>
                  <th>Bloco</th><th>Operação</th><th className="dir">Notas</th>
                  <th className="dir">Base</th><th className="dir">ICMS</th>
                  <th className="dir">Crédito presumido</th>
                </tr></thead>
                <tbody>
                  {ap.blocos.map((b, i) => (
                    <tr key={i}>
                      <td>{b.bloco}{b.devolucao ? 'D' : ''}</td>
                      <td>{b.descricao}{b.devolucao ? ' — devolução' : ''}</td>
                      <td className="dir num">{b.notas}</td>
                      <td className="dir num">{rs(b.base)}</td>
                      <td className="dir num">{rs(b.icms)}</td>
                      <td className="dir num">{rs(b.credito_presumido)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="cartao">
            <h2>Resumo</h2>
            <table><tbody>
              {[
                ['1. Débito do imposto das notas vinculadas ao crédito presumido', ap.debito],
                ['2. Estorno de créditos (devoluções)', ap.estorno],
                ['3. ICMS a deduzir da planilha de ICMS normal', ap.icms_deduzir],
                ['4. Crédito presumido calculado no período', ap.credito_presumido],
                ['5. ICMS a recolher das operações beneficiadas', ap.icms_recolher],
                ['6. Fundo Social a recolher', ap.fundo_social],
                ['7. Fundo Educação a recolher', ap.fundo_educacao],
              ].map(([r, v], i) => (
                <tr key={i}><td>{r}</td><td className="dir num">{rs(v)}</td></tr>
              ))}
            </tbody></table>
          </div>

          {historico.length > 0 && (
            <div className="cartao">
              <h2>Histórico da competência</h2>
              <table>
                <thead><tr><th>Quando</th><th>O quê</th><th>Quem</th><th>Motivo</th></tr></thead>
                <tbody>
                  {historico.map((h, i) => (
                    <tr key={i}>
                      <td className="num">{dataHora(h.em)}</td>
                      <td><span className="etiq">{h.operacao === 'FECHAR' ? 'fechamento' : 'reabertura'}</span></td>
                      <td>{h.usuario}</td>
                      <td>{h.depois?.motivo || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="cartao">
            <h2>Lançamentos ({ap.lancamentos.length})</h2>
            <div className="rolagem">
              <table>
                <thead><tr>
                  <th>Bloco</th><th>Data</th><th>NF</th><th>Parceiro</th><th>Produto</th>
                  <th className="dir">Base</th><th className="dir">ICMS</th>
                  <th className="dir">Presumido</th>
                </tr></thead>
                <tbody>
                  {ap.lancamentos.map((l, i) => (
                    <tr key={i}>
                      <td>{l.bloco}</td><td className="num">{fdata(l.data)}</td>
                      <td className="num">{l.numero}</td><td>{l.parceiro}</td><td>{l.produto}</td>
                      <td className="dir num">{rs(l.base)}</td>
                      <td className="dir num">{rs(l.icms)}</td>
                      <td className="dir num">{rs(l.credito_presumido)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  )
}
