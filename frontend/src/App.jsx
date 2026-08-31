import React, { useEffect, useState } from 'react'
import logoEcomet from './assets/ecomet-logo.png'
import Lancamento from './pages/Lancamento'
import Estoque from './pages/Estoque'
import Notas from './pages/Notas'
import Apuracao from './pages/Apuracao'
import Excecoes from './pages/Excecoes'
import Regras from './pages/Regras'
import Importar from './pages/Importar'
import ConciliacaoIcms from './pages/ConciliacaoIcms'

// Cada secao do menu lateral pode ter sub-abas (o segundo elemento). "Importação XML" fica sem
// sub-aba de proposito: e' so' entrada de dados, nada mais mora la'. "Conciliação ICMS" e' o
// ICMS normal da empresa toda (contabilidade x Ecomet/SAGI) - modulo separado do TTD 409 de
// importados acima, sem nenhum dado em comum entre os dois.
const SECOES = [
  ['inicio', 'Início', null],
  ['apuracao_importado', 'Apuração Importado', [
    ['apuracao', 'Apuração'],
    ['regras', 'Alíquotas'],
  ]],
  ['estoque_importado', 'Estoque Importado', [
    ['estoque', 'Saldo por produto'],
    ['lancamento', 'Lançar nota'],
    ['notas', 'Notas lançadas'],
    ['excecoes', 'Pendências'],
  ]],
  ['importacao_xml', 'Importação XML', null],
  ['conciliacao_icms', 'Conciliação ICMS', null],
]

function temaAtual() {
  try { return document.documentElement.getAttribute('data-theme') || 'light' }
  catch { return 'light' }
}

export default function App() {
  const [secao, setSecao] = useState('inicio')
  const [sub, setSub] = useState({})
  const [recarga, setRecarga] = useState(0)
  const [tema, setTema] = useState(temaAtual)
  const atualizar = () => setRecarga((n) => n + 1)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', tema)
    try { localStorage.setItem('lastro_tema', tema) } catch { /* ignora */ }
  }, [tema])

  const subsDaSecao = SECOES.find(([id]) => id === secao)?.[2]
  const abaAtiva = subsDaSecao ? (sub[secao] || subsDaSecao[0][0]) : null

  return (
    <>
      <header className="topo">
        <div className="topo-linha">
          <div className="marca">
            <img src={logoEcomet} alt="Ecomet" className="marca-logo" />
            <span>estoque e apuração de importados · TTD 409</span>
          </div>
          <button type="button" className="tema-botao"
                  title={tema === 'dark' ? 'Modo claro' : 'Modo escuro'}
                  onClick={() => setTema((t) => (t === 'dark' ? 'light' : 'dark'))}>
            {tema === 'dark' ? '🌞' : '🌙'}
          </button>
        </div>
      </header>
      <div className="corpo">
        <aside className="lateral">
          {SECOES.map(([id, rotulo]) => (
            <button key={id} className={secao === id ? 'ativo' : ''} onClick={() => setSecao(id)}>
              {rotulo}
            </button>
          ))}
        </aside>

        <main>
          {subsDaSecao && (
            <nav className="subnav">
              {subsDaSecao.map(([id, rotulo]) => (
                <button key={id} className={abaAtiva === id ? 'ativo' : ''}
                        onClick={() => setSub((s) => ({ ...s, [secao]: id }))}>
                  {rotulo}
                </button>
              ))}
            </nav>
          )}

          {secao === 'inicio' && (
            <div className="cartao">
              <h2>Bem-vindo</h2>
              <p className="ajuda" style={{ marginBottom: 0 }}>
                Fases 1 a 5 concluídas — a nota entra por XML ou pela tela, uma vez só, e alimenta
                estoque e apuração ao mesmo tempo. Esta tela vai virar o painel do sistema; por
                enquanto, use o menu ao lado para Apuração Importado, Estoque Importado ou
                Importação XML.
              </p>
            </div>
          )}

          {secao === 'apuracao_importado' && abaAtiva === 'apuracao' &&
            <Apuracao recarga={recarga} aoMudar={atualizar} />}
          {secao === 'apuracao_importado' && abaAtiva === 'regras' && <Regras />}

          {secao === 'estoque_importado' && abaAtiva === 'estoque' && <Estoque recarga={recarga} />}
          {secao === 'estoque_importado' && abaAtiva === 'lancamento' &&
            <Lancamento aoLancar={atualizar} />}
          {secao === 'estoque_importado' && abaAtiva === 'notas' &&
            <Notas recarga={recarga} aoMudar={atualizar} />}
          {secao === 'estoque_importado' && abaAtiva === 'excecoes' && <Excecoes recarga={recarga} />}

          {secao === 'importacao_xml' && <Importar aoImportar={atualizar} />}

          {secao === 'conciliacao_icms' && <ConciliacaoIcms />}
        </main>
      </div>
    </>
  )
}
