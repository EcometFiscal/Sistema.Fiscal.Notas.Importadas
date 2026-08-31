import React, { useEffect, useState } from 'react'
import { api, rs } from '../api'

const COR_SEVER = { alto: 'cancelada', revisar: 'acerto' }
const COR_STATUS = { aberta: '', justificada: 'e', corrigida_ecomet: 'e', devolvida_contabilidade: 'e' }
const ROTULO_STATUS = { aberta: 'aberta', justificada: 'justificada',
                         corrigida_ecomet: 'corrigida no Ecomet', devolvida_contabilidade: 'devolvida à contabilidade' }
const ROTULO_GRUPO = { debito: 'Débito', outros_debitos: 'Outros débitos', credito: 'Crédito',
                        outros_creditos: 'Outros créditos', saldo: 'Saldo' }
const ROTULO_TIPO = { cfop_saldo: 'CFOP divergente', cfop_nota: 'CFOP da nota diverge',
                       coerencia_interna_ecomet: 'Coerência interna Ecomet',
                       nota_ausente_ecomet: 'Nota ausente no Ecomet', pareamento_manual: 'Pareamento manual',
                       nota_cancelada: 'Nota cancelada', saldo_credor_anterior: 'Saldo credor anterior' }

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

function TabelaDivergencias({ titulo, ajuda, divergencias, aoSalvar }) {
  return (
    <div className="cartao">
      <h2>{titulo}</h2>
      {ajuda && <p className="ajuda">{ajuda}</p>}
      <div className="rolagem">
        <table>
          <thead><tr>
            <th>Severidade</th><th>Tipo</th><th>CFOP</th><th>NF</th><th>Descrição</th>
            <th className="dir">Contabilidade</th><th className="dir">Ecomet</th>
            <th className="dir">Diferença</th><th>Situação</th>
          </tr></thead>
          <tbody>
            {divergencias.map((d) => (
              <tr key={d.id}>
                <td><span className={`etiq ${COR_SEVER[d.severidade]}`}>{d.severidade}</span></td>
                <td style={{ fontSize: 12 }}>{ROTULO_TIPO[d.tipo] || d.tipo}</td>
                <td className="num">{d.cfop || '—'}</td>
                <td className="num">{d.numero_nota || '—'}</td>
                <td style={{ maxWidth: 340 }}>{d.descricao}</td>
                <td className="dir num">{d.valor_contabilidade != null ? rs(d.valor_contabilidade) : '—'}</td>
                <td className="dir num">{d.valor_ecomet != null ? rs(d.valor_ecomet) : '—'}</td>
                <td className="dir num">{d.diferenca != null ? rs(d.diferenca) : '—'}</td>
                <td><Justificar divergencia={d} aoSalvar={aoSalvar} /></td>
              </tr>
            ))}
            {!divergencias.length &&
              <tr><td colSpan={9} className="vazio">nenhuma divergência neste relatório</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const CAMPOS_ARQUIVO = [
  { grupo: 'Contabilidade', campo: 'contab_dime', rotulo: 'Prévia Dime', obrigatorio: true },
  { grupo: 'Contabilidade', campo: 'contab_livro', rotulo: 'Livro de Entradas', obrigatorio: true },
  { grupo: 'Contabilidade', campo: 'contab_saida', rotulo: 'Livro de Saídas', obrigatorio: false },
  { grupo: 'Empresa', campo: 'ecomet_raicms', rotulo: 'Livro Fiscal', obrigatorio: true },
  { grupo: 'Empresa', campo: 'ecomet_livro', rotulo: 'Livro de Entradas', obrigatorio: true },
  { grupo: 'Empresa', campo: 'ecomet_saida', rotulo: 'Livro de Saídas', obrigatorio: false },
]

function ImportarPeriodo({ competenciaInicial, aoImportar }) {
  const [aberto, setAberto] = useState(!competenciaInicial)
  const [competencia, setCompetencia] = useState(competenciaInicial || '')
  const [arquivos, setArquivos] = useState({})
  const [ciap, setCiap] = useState('')
  const [inscricaoEstadual, setInscricaoEstadual] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState(null)
  const [resultado, setResultado] = useState(null)

  const escolher = (campo) => (e) =>
    setArquivos((a) => ({ ...a, [campo]: e.target.files[0] || null }))

  const faltamObrigatorios = CAMPOS_ARQUIVO
    .filter((c) => c.obrigatorio && !arquivos[c.campo]).length > 0
  const compValida = /^\d{4}-\d{2}$/.test(competencia)

  async function enviar() {
    setErro(null)
    setResultado(null)
    setEnviando(true)
    try {
      const r = await api.importarConciliacaoIcms(competencia, arquivos, { ciap, inscricaoEstadual })
      setResultado(r)
      aoImportar(competencia)
    } catch (e) {
      setErro(e?.corpo?.detail?.mensagem || 'Não foi possível importar esta competência.')
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="cartao">
      <h2>Importar competência</h2>
      {!aberto ? (
        <button type="button" className="leve" onClick={() => setAberto(true)}>
          importar nova competência ou reimportar a atual
        </button>
      ) : (
        <>
          <p className="ajuda">
            Envie os 6 documentos da competência (os dois Livros de Saída são opcionais — sem
            eles, o relatório 3 fica vazio). Reimportar a mesma competência é seguro: apaga e
            regrava os documentos, lançamentos, saldos e divergências dela — o fechamento e as
            justificativas já dadas não são tocados.
          </p>
          <div className="grade g3" style={{ marginBottom: 12 }}>
            <div>
              <label>Competência (AAAA-MM)</label>
              <input value={competencia} onChange={(e) => setCompetencia(e.target.value)}
                     placeholder="2026-07" />
            </div>
            <div>
              <label>CIAP do mês (opcional)</label>
              <input type="number" step="0.01" value={ciap} onChange={(e) => setCiap(e.target.value)}
                     placeholder="não vem de nenhum documento" />
            </div>
            <div>
              <label>Inscrição estadual (opcional)</label>
              <input value={inscricaoEstadual} onChange={(e) => setInscricaoEstadual(e.target.value)}
                     placeholder="260070009" />
            </div>
          </div>

          {['Contabilidade', 'Empresa'].map((grupo) => (
            <div key={grupo} style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{grupo}</div>
              <div className="grade g3">
                {CAMPOS_ARQUIVO.filter((c) => c.grupo === grupo).map((c) => (
                  <div key={c.campo}>
                    <label>{c.rotulo}{!c.obrigatorio && ' (opcional)'}</label>
                    <input type="file" accept="application/pdf" onChange={escolher(c.campo)} />
                    {arquivos[c.campo] && <div style={{ fontSize: 12, color: 'var(--cinza)' }}>
                      {arquivos[c.campo].name}</div>}
                  </div>
                ))}
              </div>
            </div>
          ))}

          {erro && <p style={{ color: 'var(--vermelho)', fontSize: 13 }}>{erro}</p>}
          {resultado && (
            <p style={{ fontSize: 13 }}>
              Importado: {resultado.lancamentos} lançamento(s), {resultado.saldos} saldo(s) por
              CFOP, {resultado.divergencias} divergência(s) ({resultado.divergencias_altas} de
              severidade alta){!resultado.tem_saida && ' — sem Livro de Saídas'}.
            </p>
          )}

          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="acao" disabled={enviando || faltamObrigatorios || !compValida}
                    onClick={enviar}>
              {enviando ? 'importando… (pode levar um tempo)' : 'importar'}
            </button>
            {competenciaInicial && (
              <button type="button" className="leve" onClick={() => setAberto(false)}>fechar</button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default function ConciliacaoIcms() {
  const [periodos, setPeriodos] = useState([])
  const [comp, setComp] = useState(null)
  const [dados, setDados] = useState(null)
  const [carregando, setCarregando] = useState(false)
  const [fechando, setFechando] = useState(false)
  const [erroFechar, setErroFechar] = useState(null)

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

  const aoImportar = (competenciaImportada) => {
    setComp(competenciaImportada)
    carregarLista()
    if (comp === competenciaImportada) carregarPeriodo()
  }

  async function aprovarEFechar() {
    setErroFechar(null)
    setFechando(true)
    try {
      await api.fecharConciliacaoIcms(comp)
      atualizarTudo()
    } catch (e) {
      setErroFechar(e?.corpo?.detail?.mensagem || 'Não foi possível fechar esta competência.')
    } finally {
      setFechando(false)
    }
  }

  if (!periodos.length) {
    return (
      <>
        <div className="cartao">
          <h2>Conciliação de ICMS</h2>
          <p className="ajuda" style={{ marginBottom: 0 }}>
            Compara o ICMS normal (empresa toda) lançado pela contabilidade com o que o Ecomet/SAGI
            registrou — nota a nota e por CFOP, entradas e saídas — e monta a apuração mensal batendo
            com a Dime.
          </p>
          <div className="vazio">Nenhuma competência importada ainda.</div>
        </div>
        <ImportarPeriodo aoImportar={aoImportar} />
      </>
    )
  }

  const entradas = dados?.saldos.filter((s) => s.tipo === 'entrada' && s.fonte !== 'livro_ecomet') || []
  const cfopsEntrada = [...new Set(entradas.map((s) => s.cfop))].sort()
  const saidas = dados?.saldos.filter((s) => s.tipo === 'saida' && s.fonte !== 'livro_ecomet') || []
  const cfopsSaida = [...new Set(saidas.map((s) => s.cfop))].sort()
  const livroEcometEntrada = dados?.saldos.filter((s) => s.fonte === 'livro_ecomet' && s.tipo === 'entrada') || []
  const livroEcometSaida = dados?.saldos.filter((s) => s.fonte === 'livro_ecomet' && s.tipo === 'saida') || []
  const porFonte = (lista, cfop, fonte) => lista.find((s) => s.cfop === cfop && s.fonte === fonte)
  const totalCampo = (lista, cfops, fonte, campo) =>
    cfops.reduce((acc, c) => acc + (porFonte(lista, c, fonte)?.[campo] || 0), 0)
  const totalLivro = (livroLista) => livroLista.reduce((acc, s) => acc + (s.valor_contabil || 0), 0)

  const divergencias = dados?.divergencias || []
  const divCfop = divergencias.filter((d) => d.tipo === 'cfop_saldo' || d.tipo === 'coerencia_interna_ecomet'
                                              || d.tipo === 'saldo_credor_anterior')
  const divEntrada = divergencias.filter((d) => d.bloco === 'entrada'
    && d.tipo !== 'cfop_saldo' && d.tipo !== 'coerencia_interna_ecomet')
  const divSaida = divergencias.filter((d) => d.bloco === 'saida'
    && d.tipo !== 'cfop_saldo' && d.tipo !== 'coerencia_interna_ecomet')

  const abertasAltas = divergencias.filter((d) => d.status === 'aberta' && d.severidade === 'alto')
  const temDocSaida = (dados?.documentos || []).some((d) => d.tipo === 'livro_saidas')

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

      <ImportarPeriodo key={comp} competenciaInicial={comp} aoImportar={aoImportar} />

      {carregando && <div className="vazio">carregando…</div>}

      {dados && !carregando && (
        <>
          <div className="kpis" style={{ marginBottom: 20 }}>
            <div className="kpi"><div className="rot">Status</div>
              <div className="val">{dados.status}</div></div>
            <div className="kpi"><div className="rot">Divergências abertas</div>
              <div className="val num">{divergencias.filter((d) => d.status === 'aberta').length}</div></div>
            <div className="kpi"><div className="rot">Saldo credor anterior</div>
              <div className="val num">{rs(dados.saldo_credor_anterior)}</div>
              <div className="obs">Dime 05/010</div></div>
          </div>

          {!temDocSaida && (
            <div className="cartao" style={{ borderColor: 'var(--laranja, #b8860b)' }}>
              <p className="ajuda" style={{ marginBottom: 0 }}>
                Esta competência ainda não tem o Livro de Saídas importado (nem da contabilidade, nem
                da Empresa) — o relatório "Livro de Saídas" abaixo fica vazio até reimportar incluindo
                os dois documentos de saída.
              </p>
            </div>
          )}

          <TabelaDivergencias titulo="Relatório 1 — CFOP: Prévia Dime × Livro Fiscal"
            ajuda="Compara todos os valores de CFOP (entradas e saídas) entre a Prévia da Dime e o Livro Fiscal do Ecomet/SAGI."
            divergencias={divCfop} aoSalvar={atualizarTudo} />

          <TabelaDivergencias titulo="Relatório 2 — Livro de Entradas: Contabilidade × Empresa"
            ajuda="Casamento nota a nota. Vermelho exige correção; laranja é para revisar (normalmente uso/consumo, que a contabilidade lança e o Ecomet não)."
            divergencias={divEntrada} aoSalvar={atualizarTudo} />

          <TabelaDivergencias titulo="Relatório 3 — Livro de Saídas: Contabilidade × Empresa"
            ajuda="Casamento nota a nota. 'Nota cancelada' é um caso conhecido: a contabilidade zera o valor da nota cancelada e o Ecomet mantém o valor original anotado — confirme antes de aprovar."
            divergencias={divSaida} aoSalvar={atualizarTudo} />

          <div className="cartao">
            <h2>Saldos por CFOP — Entradas</h2>
            <p className="ajuda">No formato da Dime: C.F.O.P., Valor Contábil, Base de Cálculo e Imposto Creditado
              (Prévia Dime) — ao lado, para conferência, o Livro Fiscal (RAICMS) e o Livro de Entradas do Ecomet.</p>
            <div className="rolagem">
              <table>
                <thead>
                  <tr>
                    <th rowSpan={2}>C.F.O.P.</th>
                    <th colSpan={3} className="dir">Dime (Prévia)</th>
                    <th colSpan={3} className="dir">Livro Fiscal (RAICMS)</th>
                    <th rowSpan={2} className="dir">Livro Ecomet</th>
                    <th rowSpan={2} className="dir">Diferença</th>
                  </tr>
                  <tr>
                    <th className="dir">Valor Contábil</th><th className="dir">Base de Cálculo</th><th className="dir">Imposto Creditado</th>
                    <th className="dir">Valor Contábil</th><th className="dir">Base de Cálculo</th><th className="dir">Imposto Creditado</th>
                  </tr>
                </thead>
                <tbody>
                  {cfopsEntrada.map((cfop) => {
                    const dime = porFonte(entradas, cfop, 'dime')
                    const raicms = porFonte(entradas, cfop, 'raicms')
                    const livro = livroEcometEntrada.find((s) => s.cfop === cfop)
                    const dif = (dime?.valor_contabil || 0) - (raicms?.valor_contabil || 0)
                    return (
                      <tr key={cfop}>
                        <td className="num">{cfop}</td>
                        <td className="dir num">{dime ? rs(dime.valor_contabil) : '—'}</td>
                        <td className="dir num">{dime ? rs(dime.base_calculo) : '—'}</td>
                        <td className="dir num">{dime ? rs(dime.imposto) : '—'}</td>
                        <td className="dir num">{raicms ? rs(raicms.valor_contabil) : '—'}</td>
                        <td className="dir num">{raicms ? rs(raicms.base_calculo) : '—'}</td>
                        <td className="dir num">{raicms ? rs(raicms.imposto) : '—'}</td>
                        <td className="dir num">{livro ? rs(livro.valor_contabil) : '—'}</td>
                        <td className="dir num" style={{ color: Math.abs(dif) > 0.01 ? 'var(--vermelho)' : undefined }}>
                          {rs(dif)}</td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr style={{ fontWeight: 600, borderTop: '2px solid var(--linha)' }}>
                    <td>TOTAL</td>
                    <td className="dir num">{rs(totalCampo(entradas, cfopsEntrada, 'dime', 'valor_contabil'))}</td>
                    <td className="dir num">{rs(totalCampo(entradas, cfopsEntrada, 'dime', 'base_calculo'))}</td>
                    <td className="dir num">{rs(totalCampo(entradas, cfopsEntrada, 'dime', 'imposto'))}</td>
                    <td className="dir num">{rs(totalCampo(entradas, cfopsEntrada, 'raicms', 'valor_contabil'))}</td>
                    <td className="dir num">{rs(totalCampo(entradas, cfopsEntrada, 'raicms', 'base_calculo'))}</td>
                    <td className="dir num">{rs(totalCampo(entradas, cfopsEntrada, 'raicms', 'imposto'))}</td>
                    <td className="dir num">{rs(totalLivro(livroEcometEntrada))}</td>
                    <td className="dir num">
                      {rs(totalCampo(entradas, cfopsEntrada, 'dime', 'valor_contabil')
                        - totalCampo(entradas, cfopsEntrada, 'raicms', 'valor_contabil'))}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          <div className="cartao">
            <h2>Saldos por CFOP — Saídas</h2>
            <p className="ajuda">No formato da Dime: C.F.O.P., Valor Contábil, Base de Cálculo e Imposto Debitado
              (Prévia Dime) — ao lado, para conferência, o Livro Fiscal (RAICMS) e o Livro de Saídas do Ecomet.</p>
            <div className="rolagem">
              <table>
                <thead>
                  <tr>
                    <th rowSpan={2}>C.F.O.P.</th>
                    <th colSpan={3} className="dir">Dime (Prévia)</th>
                    <th colSpan={3} className="dir">Livro Fiscal (RAICMS)</th>
                    <th rowSpan={2} className="dir">Livro Ecomet</th>
                    <th rowSpan={2} className="dir">Diferença</th>
                  </tr>
                  <tr>
                    <th className="dir">Valor Contábil</th><th className="dir">Base de Cálculo</th><th className="dir">Imposto Debitado</th>
                    <th className="dir">Valor Contábil</th><th className="dir">Base de Cálculo</th><th className="dir">Imposto Debitado</th>
                  </tr>
                </thead>
                <tbody>
                  {cfopsSaida.map((cfop) => {
                    const dime = porFonte(saidas, cfop, 'dime')
                    const raicms = porFonte(saidas, cfop, 'raicms')
                    const livro = livroEcometSaida.find((s) => s.cfop === cfop)
                    const dif = (dime?.valor_contabil || 0) - (raicms?.valor_contabil || 0)
                    return (
                      <tr key={cfop}>
                        <td className="num">{cfop}</td>
                        <td className="dir num">{dime ? rs(dime.valor_contabil) : '—'}</td>
                        <td className="dir num">{dime ? rs(dime.base_calculo) : '—'}</td>
                        <td className="dir num">{dime ? rs(dime.imposto) : '—'}</td>
                        <td className="dir num">{raicms ? rs(raicms.valor_contabil) : '—'}</td>
                        <td className="dir num">{raicms ? rs(raicms.base_calculo) : '—'}</td>
                        <td className="dir num">{raicms ? rs(raicms.imposto) : '—'}</td>
                        <td className="dir num">{livro ? rs(livro.valor_contabil) : '—'}</td>
                        <td className="dir num" style={{ color: Math.abs(dif) > 0.01 ? 'var(--vermelho)' : undefined }}>
                          {rs(dif)}</td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr style={{ fontWeight: 600, borderTop: '2px solid var(--linha)' }}>
                    <td>TOTAL</td>
                    <td className="dir num">{rs(totalCampo(saidas, cfopsSaida, 'dime', 'valor_contabil'))}</td>
                    <td className="dir num">{rs(totalCampo(saidas, cfopsSaida, 'dime', 'base_calculo'))}</td>
                    <td className="dir num">{rs(totalCampo(saidas, cfopsSaida, 'dime', 'imposto'))}</td>
                    <td className="dir num">{rs(totalCampo(saidas, cfopsSaida, 'raicms', 'valor_contabil'))}</td>
                    <td className="dir num">{rs(totalCampo(saidas, cfopsSaida, 'raicms', 'base_calculo'))}</td>
                    <td className="dir num">{rs(totalCampo(saidas, cfopsSaida, 'raicms', 'imposto'))}</td>
                    <td className="dir num">{rs(totalLivro(livroEcometSaida))}</td>
                    <td className="dir num">
                      {rs(totalCampo(saidas, cfopsSaida, 'dime', 'valor_contabil')
                        - totalCampo(saidas, cfopsSaida, 'raicms', 'valor_contabil'))}</td>
                  </tr>
                </tfoot>
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

          <div className="cartao">
            <h2>Aprovação</h2>
            {dados.status === 'fechado' ? (
              <p className="ajuda" style={{ marginBottom: 0 }}>
                Competência fechada — o resultado desta conciliação já foi salvo.
              </p>
            ) : (
              <>
                <p className="ajuda">
                  Ao aprovar, o resultado (saldos, divergências e apuração) desta competência é salvo
                  como definitivo. {abertasAltas.length > 0
                    ? `Ainda há ${abertasAltas.length} divergência(s) de severidade alta em aberto — corrija os documentos e reimporte, ou justifique cada uma, antes de aprovar.`
                    : 'Divergências de severidade "revisar" (nota cancelada, uso/consumo etc.) podem ficar abertas e não bloqueiam.'}
                </p>
                {erroFechar && <p style={{ color: 'var(--vermelho)', fontSize: 13 }}>{erroFechar}</p>}
                <button type="button" className="acao" disabled={fechando || abertasAltas.length > 0}
                        onClick={aprovarEFechar}>
                  {fechando ? 'aprovando…' : 'aprovar e fechar competência'}
                </button>
              </>
            )}
          </div>
        </>
      )}
    </>
  )
}
