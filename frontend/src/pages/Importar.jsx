import React, { useEffect, useRef, useState } from 'react'
import { api, data as fdata } from '../api'

const CORES = { importada: 'e', duplicada: '', pendente: 'acerto', erro: 'cancelada', ignorada: '' }
const dataHora = (v) => (v ? new Date(v).toLocaleString('pt-BR') : '—')

export default function Importar({ aoImportar }) {
  const [cnpj, setCnpj] = useState('')
  const [salvoCnpj, setSalvoCnpj] = useState(null)
  const [lotes, setLotes] = useState([])
  const [lote, setLote] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState(null)
  const arquivo = useRef(null)

  const carregar = () => {
    api.configuracao().then((c) => setSalvoCnpj(c.cnpj_empresa?.valor || null))
    api.lotes().then(setLotes)
  }
  useEffect(carregar, [])

  async function gravarCnpj(e) {
    e.preventDefault(); setErro(null)
    try { await api.gravarConfig(cnpj); setCnpj(''); carregar() }
    catch (ex) { setErro(ex.corpo?.detail?.mensagem || 'não foi possível gravar') }
  }

  async function enviar(e) {
    e.preventDefault()
    const f = arquivo.current?.files?.[0]
    if (!f) return
    setEnviando(true); setErro(null); setLote(null)
    try { const r = await api.importarZip(f); setLote(r); carregar(); aoImportar?.() }
    catch (ex) { setErro(ex.corpo?.detail?.mensagem || 'não foi possível importar o pacote') }
    finally { setEnviando(false) }
  }

  return (
    <>
      {!salvoCnpj && (
        <form className="cartao" onSubmit={gravarCnpj}>
          <h2>CNPJ do estabelecimento</h2>
          <p className="ajuda">
            É o CNPJ que decide se cada NF-e do pacote é entrada ou saída. Se você não informar,
            o primeiro pacote resolve sozinho: o CNPJ da empresa é o único que aparece dos dois
            lados das operações — emitindo as saídas e recebendo as entradas.
          </p>
          <div className="grade g3">
            <div><label>CNPJ da empresa</label>
              <input required value={cnpj} onChange={(e) => setCnpj(e.target.value)}
                     placeholder="somente números" /></div>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button className="acao">Gravar</button>
            </div>
          </div>
        </form>
      )}

      <form className="cartao" onSubmit={enviar}>
        <h2>Importar pacote de XML</h2>
        <p className="ajuda">
          O pacote que você exporta do sistema atual. Lê subpastas e zips dentro do zip, ignora o
          que não for NF-e sua, e a chave de acesso impede a mesma nota de entrar duas vezes.
          {salvoCnpj && <> CNPJ configurado: <b>{salvoCnpj}</b>.</>}
        </p>
        <div className="grade g3">
          <div><label>Arquivo .zip</label>
            <input ref={arquivo} type="file" accept=".zip" required /></div>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button className="acao" disabled={enviando}>
              {enviando ? 'Lendo o pacote…' : 'Importar'}
            </button>
          </div>
        </div>
        {erro && <div className="aviso erro"><b>Não importou</b>{erro}</div>}
      </form>

      {lote && (
        <div className="cartao">
          <h2>Resultado do lote #{lote.id}</h2>
          <div className="kpis" style={{ marginBottom: 18 }}>
            <div className="kpi"><div className="rot">Arquivos</div>
              <div className="val num">{lote.total}</div></div>
            <div className="kpi"><div className="rot">Importadas</div>
              <div className="val num">{lote.importadas}</div></div>
            <div className="kpi"><div className="rot">Já existiam</div>
              <div className="val num">{lote.duplicadas}</div>
              <div className="obs">mesma chave de acesso</div></div>
            <div className="kpi"><div className="rot">Pendentes</div>
              <div className="val num">{lote.pendentes}</div>
              <div className="obs">entraram, mas alguém precisa olhar</div></div>
            <div className="kpi"><div className="rot">Fora</div>
              <div className="val num">{lote.erros}</div>
              <div className="obs">erro de leitura ou nota de terceiros</div></div>
          </div>
          <div className="rolagem">
            <table>
              <thead><tr>
                <th>Situação</th><th>Arquivo</th><th>NF</th><th>Op.</th><th>Chave</th><th>Motivo</th>
              </tr></thead>
              <tbody>
                {lote.arquivos.map((a, i) => (
                  <tr key={i}>
                    <td><span className={`etiq ${CORES[a.situacao] || ''}`}>{a.situacao}</span></td>
                    <td style={{ maxWidth: 220, wordBreak: 'break-all' }}>{a.arquivo}</td>
                    <td className="num">{a.numero || '—'}</td>
                    <td>{a.tipo === 'E' ? 'entrada' : a.tipo === 'S' ? 'saída' : '—'}</td>
                    <td className="num" style={{ fontSize: 11, wordBreak: 'break-all', maxWidth: 200 }}>
                      {a.chave_acesso || '—'}</td>
                    <td style={{ maxWidth: 420 }}>{a.motivo || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="cartao">
        <h2>Pacotes importados</h2>
        <div className="rolagem">
          <table>
            <thead><tr>
              <th>#</th><th>Quando</th><th>Origem</th><th>Pacote</th>
              <th className="dir">Arquivos</th><th className="dir">Importadas</th>
              <th className="dir">Duplicadas</th><th className="dir">Pendentes</th>
              <th className="dir">Fora</th><th>Quem</th>
            </tr></thead>
            <tbody>
              {lotes.map((l) => (
                <tr key={l.id} style={{ cursor: 'pointer' }}
                    onClick={() => api.lote(l.id).then(setLote)}>
                  <td className="num">{l.id}</td>
                  <td className="num">{dataHora(l.criado_em)}</td>
                  <td><span className="etiq">{l.origem}</span></td>
                  <td>{l.nome}</td>
                  <td className="dir num">{l.total}</td>
                  <td className="dir num">{l.importadas}</td>
                  <td className="dir num">{l.duplicadas}</td>
                  <td className="dir num">{l.pendentes}</td>
                  <td className="dir num">{l.erros}</td>
                  <td>{l.criado_por}</td>
                </tr>
              ))}
              {!lotes.length && <tr><td colSpan={10} className="vazio">nenhum pacote importado ainda</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
