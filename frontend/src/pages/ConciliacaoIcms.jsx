import React, { useEffect, useState } from 'react'
import { api, rs } from '../api'

const COR_SEVER = { alto: 'cancelada', revisar: 'acerto' }
const COR_STATUS = { aberta: '', justificada: 'e', corrigida_ecomet: 'e', devolvida_contabilidade: 'e' }
const ROTULO_STATUS = { aberta: 'aberta', justificada: 'justificada',
                         corrigida_ecomet: 'corrigida no Ecomet', devolvida_contabilidade: 'devolvida à contabilidade' }
const ROTULO_GRUPO = { debito: 'Débito', outros_debitos: 'Outros débitos', credito: 'Crédito',
                        outros_creditos: 'Outros créditos', saldo: 'Saldo' }

function Justificar({ divergencia, aoSalvar }) {
  const [aberto, setAberto] = useState(false)
  const [texto, setTexto] = useState(divergencia.justificativa || '')
  const [status, setStatus] = useState('justificada')
  const [enviando, setEnviando] = useState(false)

  if (divergencia.status !== 'aberta' && !aberto) {
    return (
      <div>
        <span className={`etiq ${COR_STATUS[divergencia.status]}`}>{ROTULO_STATUS[divergencia.status]}</span>
        {divergencia.justificativa && <div style={{ fontSize: 12, color: 'var(--cinza)', marginTop: 4 }}>
          {divergencia.justificativa}</div>}
        <button type="button" className="leve" style={{ marginTop: 6, padding: '4px 10px', fontSize: 12 }}
                onClick={() => setAberto(true)}>editar</button>
      </div>
    )
  }

  if (!aberto) {
    return <button type="button" className="leve" style={{ padding: '4px 10px', fontSize: 12 }}
                   onClick={() => setAberto(true)}>justificar</button>
  }

  async function salvar() {
    if (!texto.trim()) return
    setEnviando(true)
    try { await api.justificarDivergencia(divergencia.id, { justificativa: texto, status }); aoSalvar() }
    finally { setEnviando(false); setAberto(false) }
  }

  return (
    <div style={{ minWidth: 220 }}>
      <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ marginBottom: 6 }}>
        <option value="justificada">Justificada (fica assim)</option>
        <option value="corrigida_ecomet">Corrigida no Ecomet</option>
        <option value="devolvida_contabilidade">Devolvida à contabilidade</option>
      </select>
      <textarea rows={2} value={texto} onChange={(e) => setTexto(e.target.value)}
                placeholder="motivo da divergência" style={{ marginBottom: 6 }} />
      <div style={{ display: 'flex', gap: 6 }}>
        <button type="button" className="acao" disabled={enviando} onClick={salvar}
                style={{ padding: '6px 12px', fontSize: 12 }}>salvar</button>
        <button type="button" className="leve" onClick={() => setAberto(false)}
                style={{ padding: '6px 12px', fontSize: 12 }}>cancelar</button>
      </div>
    </div>
  )
}

export default function ConciliacaoIcms() {
  const [periodos, setPeriodos] = useState([])
  const [comp, setComp] = useState(null)
  const [dados, setDados] = useState(null)
  const [carregando, setCarregando] = useState(false)

  const carregarLista = () => api.conciliacaoPeriodos().then((ps) => {
    setPeriodos(ps)
    if (!comp && ps.length) setComp(ps[0].competencia)
  })
  useEffect(carregarLista, [])

  const carregarPeriodo = () => {
    if (!comp) return
    setCarregando(true)
    api.conciliacaoPeriodo(comp).then(setDados).finally(() => setCarregando(false))
  }
  useEffect(carregarPeriodo, [comp])

  const atualizarTudo = () => { carregarLista(); carregarPeriodo() }

  if (!periodos.length) {
    return (
      <div className="cartao">
        <h2>Conciliação de ICMS</h2>
        <p className="ajuda" style={{ marginBottom: 0 }}>
          Compara o ICMS normal (empresa toda) lançado pela contabilidade com o que o Ecomet/SAGI
          registrou — nota a nota e por CFOP — e monta a apuração mensal batendo com a Dime.
        </p>
        <div className="vazio">
          Nenhuma competência importada ainda. A leitura dos 4 documentos (Prévia Dime, Livro de
          Entradas da contabilidade, Livro de Entradas e RAICMS do Ecomet) roda por um script local
          — peça para rodar <code>scripts/importar_conciliacao_icms.py</code> para a competência
          que faltar.
        </div>
      </div>
    )
  }

  const entradas = dados?.saldos.filter((s) => s.tipo === 'entrada' && s.fonte !== 'livro_ecomet') || []
  const cfopsEntrada = [...new Set(entradas.map((s) => s.cfop))].sort()
  const saidas = dados?.saldos.filter((s) => s.tipo === 'saida') || []
  const cfopsSaida = [...new Set(saidas.map((s) => s.cfop))].sort()
  const livroEcomet = dados?.saldos.filter((s) => s.fonte === 'livro_ecomet') || []
  const porFonte = (lista, cfop, fonte) => lista.find((s) => s.cfop === cfop && s.fonte === fonte)

  const grupos = ['debito', 'outros_debitos', 'credito', 'outros_creditos', 'saldo']

  return (
    <>
      <div className="cartao">
        <h2>Conciliação de ICMS</h2>
        <p className="ajuda">
          Contabilidade × Ecomet/SAGI — inscrição estadual {dados?.inscricao_estadual}.
        </p>
        <div className="grade g3">
          <div>
            <label>Competência</label>
            <select value={comp || ''} onChange={(e) => setComp(e.target.value)}>
              {periodos.map((p) => (
                <option key={p.competencia} value={p.competencia}>
                  {p.competencia} — {p.status}{p.divergencias_altas ? ` · ${p.divergencias_altas} alta(s)` : ''}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {carregando && <div className="vazio">carregando…</div>}

      {dados && !carregando && (
        <>
          <div className="kpis" style={{ marginBottom: 20 }}>
            <div className="kpi"><div className="rot">Status</div>
              <div className="val">{dados.status}</div></div>
            <div className="kpi"><div className="rot">Divergências abertas</div>
              <div className="val num">{dados.divergencias.filter((d) => d.status === 'aberta').length}</div></div>
            <div className="kpi"><div className="rot">Saldo credor anterior</div>
              <div className="val num">{rs(dados.saldo_credor_anterior)}</div>
              <div className="obs">Dime 05/010</div></div>
          </div>

          <div className="cartao">
            <h2>Divergências</h2>
            <p className="ajuda">Vermelho exige correção; laranja é para revisar (normalmente uso/consumo
              que a contabilidade lança e o Ecomet não).</p>
            <div className="rolagem">
              <table>
                <thead><tr>
                  <th>Severidade</th><th>Tipo</th><th>CFOP</th><th>NF</th><th>Descrição</th>
                  <th className="dir">Contabilidade</th><th className="dir">Ecomet</th>
                  <th className="dir">Diferença</th><th>Situação</th>
                </tr></thead>
                <tbody>
                  {dados.divergencias.map((d) => (
                    <tr key={d.id}>
                      <td><span className={`etiq ${COR_SEVER[d.severidade]}`}>{d.severidade}</span></td>
                      <td style={{ fontSize: 12 }}>{d.tipo}</td>
                      <td className="num">{d.cfop || '—'}</td>
                      <td className="num">{d.numero_nota || '—'}</td>
                      <td style={{ maxWidth: 340 }}>{d.descricao}</td>
                      <td className="dir num">{d.valor_contabilidade != null ? rs(d.valor_contabilidade) : '—'}</td>
                      <td className="dir num">{d.valor_ecomet != null ? rs(d.valor_ecomet) : '—'}</td>
                      <td className="dir num">{d.diferenca != null ? rs(d.diferenca) : '—'}</td>
                      <td><Justificar divergencia={d} aoSalvar={atualizarTudo} /></td>
                    </tr>
                  ))}
                  {!dados.divergencias.length &&
                    <tr><td colSpan={9} className="vazio">nenhuma divergência nesta competência</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          <div className="cartao">
            <h2>Saldos por CFOP — Entradas</h2>
            <p className="ajuda">Prévia Dime (contabilidade) × RAICMS (Ecomet) × Livro de Entradas do Ecomet.</p>
            <div className="rolagem">
              <table>
                <thead><tr>
                  <th>CFOP</th><th className="dir">Dime</th><th className="dir">RAICMS</th>
                  <th className="dir">Livro Ecomet</th><th className="dir">Diferença</th>
                </tr></thead>
                <tbody>
                  {cfopsEntrada.map((cfop) => {
                    const dime = porFonte(entradas, cfop, 'dime')
                    const raicms = porFonte(entradas, cfop, 'raicms')
                    const livro = livroEcomet.find((s) => s.cfop === cfop)
                    const dif = (dime?.valor_contabil || 0) - (raicms?.valor_contabil || 0)
                    return (
                      <tr key={cfop}>
                        <td className="num">{cfop}</td>
                        <td className="dir num">{dime ? rs(dime.valor_contabil) : '—'}</td>
                        <td className="dir num">{raicms ? rs(raicms.valor_contabil) : '—'}</td>
                        <td className="dir num">{livro ? rs(livro.valor_contabil) : '—'}</td>
                        <td className="dir num" style={{ color: Math.abs(dif) > 0.01 ? 'var(--vermelho)' : undefined }}>
                          {rs(dif)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="cartao">
            <h2>Saldos por CFOP — Saídas</h2>
            <div className="rolagem">
              <table>
                <thead><tr>
                  <th>CFOP</th><th className="dir">Dime</th><th className="dir">RAICMS</th>
                  <th className="dir">Diferença</th>
                </tr></thead>
                <tbody>
                  {cfopsSaida.map((cfop) => {
                    const dime = porFonte(saidas, cfop, 'dime')
                    const raicms = porFonte(saidas, cfop, 'raicms')
                    const dif = (dime?.valor_contabil || 0) - (raicms?.valor_contabil || 0)
                    return (
                      <tr key={cfop}>
                        <td className="num">{cfop}</td>
                        <td className="dir num">{dime ? rs(dime.valor_contabil) : '—'}</td>
                        <td className="dir num">{raicms ? rs(raicms.valor_contabil) : '—'}</td>
                        <td className="dir num" style={{ color: Math.abs(dif) > 0.01 ? 'var(--vermelho)' : undefined }}>
                          {rs(dif)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="cartao">
            <h2>Apuração</h2>
            <p className="ajuda">Débitos, créditos e saldo credor para o mês seguinte — mesma estrutura da Dime.</p>
            <div className="rolagem">
              <table>
                <thead><tr><th>Grupo</th><th>Linha</th><th className="dir">Valor</th><th>Origem</th></tr></thead>
                <tbody>
                  {grupos.map((g) => dados.apuracao.filter((l) => l.grupo === g).map((l, i) => (
                    <tr key={`${g}-${l.ordem}`}>
                      {i === 0 && <td rowSpan={dados.apuracao.filter((x) => x.grupo === g).length}
                                      style={{ fontWeight: 600 }}>{ROTULO_GRUPO[g]}</td>}
                      <td>{l.rotulo}</td>
                      <td className="dir num" style={{ fontWeight: g === 'saldo' ? 600 : 400 }}>{rs(l.valor)}</td>
                      <td style={{ fontSize: 12, color: 'var(--cinza)' }}>{l.origem_texto || '—'}</td>
                    </tr>
                  )))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  )
}
