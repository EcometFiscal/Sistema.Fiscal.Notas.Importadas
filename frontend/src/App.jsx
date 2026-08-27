import React, { useState } from 'react'
import Lancamento from './pages/Lancamento'
import Estoque from './pages/Estoque'
import Notas from './pages/Notas'
import Apuracao from './pages/Apuracao'
import Excecoes from './pages/Excecoes'
import Regras from './pages/Regras'
import Importar from './pages/Importar'

const ABAS = [
  ['lancamento', 'Lançar nota'],
  ['importar', 'Importar XML'],
  ['estoque', 'Estoque'],
  ['notas', 'Notas'],
  ['apuracao', 'Apuração'],
  ['excecoes', 'Pendências'],
  ['regras', 'Alíquotas'],
]

export default function App() {
  const [aba, setAba] = useState('lancamento')
  const [recarga, setRecarga] = useState(0)
  const atualizar = () => setRecarga((n) => n + 1)

  return (
    <>
      <header className="topo">
        <div className="topo-linha">
          <div className="marca">LASTRO<span>estoque e apuração de importados · TTD 409</span></div>
          <nav>
            {ABAS.map(([id, rotulo]) => (
              <button key={id} className={aba === id ? 'ativo' : ''} onClick={() => setAba(id)}>
                {rotulo}
              </button>
            ))}
          </nav>
        </div>
      </header>
      <main>
        {aba === 'lancamento' && <Lancamento aoLancar={atualizar} />}
        {aba === 'importar' && <Importar aoImportar={atualizar} />}
        {aba === 'estoque' && <Estoque recarga={recarga} />}
        {aba === 'notas' && <Notas recarga={recarga} aoMudar={atualizar} />}
        {aba === 'apuracao' && <Apuracao recarga={recarga} aoMudar={atualizar} />}
        {aba === 'excecoes' && <Excecoes recarga={recarga} />}
        {aba === 'regras' && <Regras />}
        <p className="rodape">
          Fases 1 a 5 — a nota entra por XML ou pela tela, uma vez só, e alimenta estoque e
          apuração ao mesmo tempo.
        </p>
      </main>
    </>
  )
}
