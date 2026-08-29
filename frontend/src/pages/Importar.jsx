import React, { useEffect, useRef, useState } from 'react'
import { api, baixar, data as fdata } from '../api'

const CORES = { importada: 'e', complementada: 's', duplicada: '', pendente: 'acerto',
                erro: 'cancelada', ignorada: '' }
const dataHora = (v) => (v ? new Date(v).toLocaleString('pt-BR') : '—')

function TabelaArquivos({ arquivos }) {
  return (
    <div className="rolagem">
      <table>
        <thead><tr>
          <th>Situação</th><th>Arquivo</th><th>NF</th><th>Op.</th><th>Chave</th><th>Motivo</th>
        </tr></thead>
        <tbody>
          {arquivos.map((a, i) => (
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
  )
}

function KpisLote({ lote }) {
  return (
    <div className="kpis" style={{ marginBottom: 18 }}>
      <div className="kpi"><div className="rot">Arquivos</div>
        <div className="val num">{lote.total}</div></div>
      <div className="kpi"><div className="rot">Importadas</div>
        <div className="val num">{lote.importadas}</div>
        <div className="obs">notas novas</div></div>
      <div className="kpi"><div className="rot">Complementadas</div>
        <div className="val num">{lote.complementadas}</div>
        <div className="obs">notas migradas que ganharam os dados do XML</div></div>
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
  )
}

function AbaImportar({ salvoCnpj, carregar, aoImportar }) {
  const [cnpj, setCnpj] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState(null)
  const [lote, setLote] = useState(null)
  const arquivo = useRef(null)

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
          que não for NF-e sua, e a chave de acesso impede a mesma nota de entrar duas vezes. Se o
          XML casar com uma nota migrada da planilha (sem chave de acesso), ele complementa —
          NCM, origem, CFOP e bloco do TTD — em vez de duplicar; quantidade e valor da planilha
          nunca mudam.
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
          <p className="ajuda">
            Confira o pacote nota a nota na aba Auditoria — o relatório em Excel de lá mostra a
            alíquota de cada item e destaca com cor o que entrou na apuração.
          </p>
          <KpisLote lote={lote} />
          <TabelaArquivos arquivos={lote.arquivos} />
        </div>
      )}
    </>
  )
}

function AbaAuditoria({ lotes }) {
  const [selecionado, setSelecionado] = useState(null)
  const [carregando, setCarregando] = useState(false)

  async function selecionar(id) {
    setCarregando(true)
    try { setSelecionado(await api.lote(id)) }
    finally { setCarregando(false) }
  }

  return (
    <>
      <div className="cartao">
        <h2>Auditoria de importação</h2>
        <p className="ajuda">
          Clique num pacote abaixo pra conferir nota a nota. O relatório em Excel lista todos os
          arquivos do pacote — inclusive os que não viraram nota — com a alíquota de ICMS de cada
          item (já com filtro pra agrupar por alíquota) e destaque de cor: verde para o que entrou
          na apuração do TTD, laranja para saída sem bloco atribuído (a conferir), vermelho para o
          que não virou nota (erro, duplicada ou evento ignorado). A aba LEGENDA do arquivo explica
          cada cor.
        </p>
        <div className="rolagem">
          <table>
            <thead><tr>
              <th>#</th><th>Quando</th><th>Origem</th><th>Pacote</th>
              <th className="dir">Arquivos</th><th className="dir">Importadas</th>
              <th className="dir">Complementadas</th>
              <th className="dir">Duplicadas</th><th className="dir">Pendentes</th>
              <th className="dir">Fora</th><th>Quem</th>
            </tr></thead>
            <tbody>
              {lotes.map((l) => (
                <tr key={l.id} style={{ cursor: 'pointer' }}
                    className={selecionado?.id === l.id ? 'ativo' : ''}
                    onClick={() => selecionar(l.id)}>
                  <td className="num">{l.id}</td>
                  <td className="num">{dataHora(l.criado_em)}</td>
                  <td><span className="etiq">{l.origem}</span></td>
                  <td>{l.nome}</td>
                  <td className="dir num">{l.total}</td>
                  <td className="dir num">{l.importadas}</td>
                  <td className="dir num">{l.complementadas}</td>
                  <td className="dir num">{l.duplicadas}</td>
                  <td className="dir num">{l.pendentes}</td>
                  <td className="dir num">{l.erros}</td>
                  <td>{l.criado_por}</td>
                </tr>
              ))}
              {!lotes.length && <tr><td colSpan={11} className="vazio">nenhum pacote importado ainda</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {carregando && <div className="vazio">carregando…</div>}

      {selecionado && !carregando && (
        <div className="cartao">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <h2>Pacote #{selecionado.id} — {selecionado.nome}</h2>
            <button type="button" className="acao"
                    onClick={() => baixar(`/exportar/auditoria/${selecionado.id}`)}>
              Baixar relatório de auditoria em Excel
            </button>
          </div>
          <KpisLote lote={selecionado} />
          <TabelaArquivos arquivos={selecionado.arquivos} />
        </div>
      )}
    </>
  )
}

export default function Importar({ aoImportar }) {
  const [aba, setAba] = useState('importar')
  const [salvoCnpj, setSalvoCnpj] = useState(null)
  const [lotes, setLotes] = useState([])

  const carregar = () => {
    api.configuracao().then((c) => setSalvoCnpj(c.cnpj_empresa?.valor || null))
    api.lotes().then(setLotes)
  }
  useEffect(carregar, [])

  return (
    <>
      <nav className="subnav">
        <button className={aba === 'importar' ? 'ativo' : ''} onClick={() => setAba('importar')}>
          Importar
        </button>
        <button className={aba === 'auditoria' ? 'ativo' : ''} onClick={() => setAba('auditoria')}>
          Auditoria
        </button>
      </nav>
      {aba === 'importar' &&
        <AbaImportar salvoCnpj={salvoCnpj} carregar={carregar} aoImportar={aoImportar} />}
      {aba === 'auditoria' && <AbaAuditoria lotes={lotes} />}
    </>
  )
}
