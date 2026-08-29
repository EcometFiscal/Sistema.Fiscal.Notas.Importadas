const BASE = import.meta.env.VITE_API_URL || '/api'

// A trava de senha vem desligada. Se alguem definir SENHA_ACESSO no ambiente da Vercel, a API
// passa a exigir o cabecalho X-Senha e a tela pede a senha uma vez, guardando no navegador.
export const senha = {
  ler: () => { try { return localStorage.getItem('lastro_senha') || '' } catch { return '' } },
  gravar: (v) => { try { localStorage.setItem('lastro_senha', v) } catch { /* ignora */ } },
  limpar: () => { try { localStorage.removeItem('lastro_senha') } catch { /* ignora */ } },
}

async function req(caminho, opcoes = {}) {
  const r = await fetch(BASE + caminho, {
    ...opcoes,
    headers: { 'Content-Type': 'application/json', 'X-Usuario': 'fiscal',
               'X-Senha': senha.ler(), ...(opcoes.headers || {}) },
  })
  if (r.status === 401) {
    senha.limpar()
    const informada = window.prompt('Esta instalação exige senha de acesso:')
    if (informada) { senha.gravar(informada); return req(caminho, opcoes) }
  }
  const texto = await r.text()
  const corpo = texto ? JSON.parse(texto) : null
  if (!r.ok) throw Object.assign(new Error('erro'), { status: r.status, corpo })
  return corpo
}

export const api = {
  resumo: () => req('/resumo'),
  produtos: () => req('/produtos'),
  parceiros: (q = '') => req(`/parceiros?limite=30${q ? `&q=${encodeURIComponent(q)}` : ''}`),
  blocos: (uf) => req(`/blocos${uf ? `?uf=${uf}` : ''}`),
  saldo: (id, data) => req(`/estoque/saldo/${id}${data ? `?data=${data}` : ''}`),
  posicao: (ate) => req(`/estoque/posicao?cobertura=false${ate ? `&ate=${ate}` : ''}`),
  razao: (id) => req(`/estoque/razao/${id}`),
  notas: (p = {}) => req('/notas?' + new URLSearchParams(p)),
  lancar: (nota) => req('/notas', { method: 'POST', body: JSON.stringify(nota) }),
  cancelar: (id, motivo) => req(`/notas/${id}/cancelar?motivo=${encodeURIComponent(motivo)}`, { method: 'POST' }),
  excecoes: () => req('/excecoes'),
  apuracao: (comp) => req(`/apuracao/${comp}`),
  competencias: () => req('/competencias'),
  fechar: (comp) => req(`/apuracao/${comp}/fechar`, { method: 'POST' }),
  reabrir: (comp, motivo) =>
    req(`/apuracao/${comp}/reabrir`, { method: 'POST', body: JSON.stringify({ motivo }) }),
  historico: (comp) => req(`/apuracao/${comp}/historico`),
  regras: () => req('/regras'),
  novaRegra: (r) => req('/regras', { method: 'POST', body: JSON.stringify(r) }),
  configuracao: () => req('/configuracao'),
  gravarConfig: (cnpj_empresa) =>
    req('/configuracao', { method: 'POST', body: JSON.stringify({ cnpj_empresa }) }),
  lotes: () => req('/importar/lotes'),
  lote: (id) => req(`/importar/lotes/${id}`),
  importarZip: async (arquivo) => {
    const fd = new FormData()
    fd.append('arquivo', arquivo)
    const r = await fetch(BASE + '/importar/zip', { method: 'POST', body: fd,
                                                    headers: { 'X-Usuario': 'fiscal',
                                                               'X-Senha': senha.ler() } })
    const texto = await r.text()
    let corpo
    try { corpo = texto ? JSON.parse(texto) : null }
    catch {
      // A funcao pode estourar o tempo limite no meio da importacao (pacote grande, rede ate'
      // o Supabase) - a resposta nesse caso nao e' JSON. Mensagem especifica em vez da generica
      // "nao foi possivel importar o pacote", que nao dizia o que fazer.
      throw Object.assign(new Error('erro'), { status: r.status, corpo: { detail: { mensagem:
        r.status === 504 || !r.ok
          ? 'A importação demorou demais e a função foi encerrada antes de terminar. O pacote é '
            + 'importado de uma vez só (tudo ou nada) - nada foi gravado, pode tentar de novo. Se '
            + 'continuar acontecendo, quebre o .zip em pacotes menores.'
          : 'Resposta inesperada do servidor ao importar.' } } })
    }
    if (!r.ok) throw Object.assign(new Error('erro'), { status: r.status, corpo })
    return corpo
  },
}

export const baixar = async (caminho) => {
  const r = await fetch(BASE + caminho, { headers: { 'X-Senha': senha.ler() } })
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = (r.headers.get('Content-Disposition') || '').split('filename="')[1]?.replace('"', '')
    || 'lastro.xlsx'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const kg = (v) =>
  (v ?? 0).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
export const rs = (v) =>
  (v ?? 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
export const pct = (v) => `${(v ?? 0).toLocaleString('pt-BR', { minimumFractionDigits: 3, maximumFractionDigits: 3 })}%`
export const data = (d) => (d ? new Date(d + 'T00:00:00').toLocaleDateString('pt-BR') : '—')
export const hoje = () => new Date().toISOString().slice(0, 10)
