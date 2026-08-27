# Lastro — estoque fiscal e apuração de ICMS de importados (TTD 409/410/411)

Substitui as duas planilhas por uma base única. **A nota entra uma vez — hoje, pelo XML — e
alimenta estoque e apuração ao mesmo tempo.** Os dois deixam de poder discordar entre si.

Roda no seu computador para desenvolver e publica na Vercel com banco no Supabase.

---

## 1. Preparar o banco no Supabase

1. Crie um projeto em <https://supabase.com>. Guarde a senha do banco.
2. Em **Project Settings → Database → Connection string → URI**, copie a string do **Connection
   pooling** (porta `6543`, modo *Transaction*). É essa que a Vercel usa — a porta 5432 direta
   estoura o limite de conexões em função serverless.
3. Troque o começo `postgresql://` por `postgresql+psycopg2://`.

Vai ficar assim:

```
postgresql+psycopg2://postgres.xxxxxxxx:SENHA@aws-0-sa-east-1.pooler.supabase.com:6543/postgres
```

## 2. Rodar no seu computador

Precisa de Python 3.11+ e Node 20+.

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+psycopg2://...supabase...:6543/postgres"   # Windows: set
export PGSSLMODE=require

python -m scripts.criar_schema          # cria as tabelas e semeia as alíquotas do TTD
uvicorn app.main:app --reload           # http://localhost:8000/docs
```

```bash
# frontend, em outro terminal
cd frontend
npm install
npm run dev                             # http://localhost:5173
```

## 3. Carregar o histórico (uma vez)

```bash
cd backend
python -m scripts.seed_historico \
  --estoque "ESTOQUE FISCAL IMPORTADO.xlsm" \
  --apuracao "Apuração ICMS Nacional e Importado  072026.xlsx"
```

Roda o saneamento da Fase 1 sobre os arquivos originais e importa o resultado: 981 notas,
60 parceiros, 6 produtos, custeio PEPS refeito do zero.

## 4. Publicar na Vercel

```bash
npm i -g vercel
vercel link
vercel env add DATABASE_URL      # cole a string do pooler do Supabase
vercel env add PGSSLMODE         # require
vercel --prod
```

Ou suba o repositório no GitHub e importe pelo painel da Vercel — as duas variáveis de ambiente
acima são tudo o que ele precisa.

`vercel.json` já está pronto: o `frontend/` é construído como site estático e todo `/api/*` cai na
função Python que é o mesmo FastAPI que você roda em casa. Não existe uma versão "de nuvem" e
outra "local".

### Acesso

O link é público e sem senha, por decisão de 27/08/2026. A trava existe e está desligada: definir
a variável `SENHA_ACESSO` na Vercel faz a aplicação passar a exigir o cabeçalho `X-Senha` em toda
chamada de API, sem mexer em nenhuma linha de código. Enquanto ela estiver vazia, quem tiver o
link lança, cancela e fecha competência.

### Fluxo de trabalho

O repositório é a fonte da verdade. A Vercel acompanha o branch `main`: todo push publica.

```bash
git add -A && git commit -m "o que mudou" && git push
```

Trabalhe em branch quando a mudança for grande — a Vercel gera um link de pré-visualização por
branch, e aí dá para conferir sem mexer no que está no ar.

O `.github/workflows/testes.yml` roda a cada push: sobe a aplicação, roda os testes e faz o mesmo
build que a Vercel faz. Quebrar no GitHub é melhor que quebrar no deploy.

**Nunca comite o `.env`** — a senha do Supabase vive só nas variáveis de ambiente da Vercel e na
sua máquina. O `.gitignore` já cobre isso, mas confira antes do primeiro push.

Para a suíte rodar completa no CI, os dois arquivos originais precisam existir: coloque-os em
`planilhas/` (fora do git) ou aponte `ARQ_ESTOQUE` e `ARQ_APURACAO`. Sem eles a suíte pula e
diz por quê, em vez de dar falso positivo.

---

## Como a nota entra

Pela aba **Importar XML**: o pacote `.zip` que você exporta do sistema atual. Lê subpastas e zips
dentro do zip, e a chave de acesso de 44 dígitos impede a mesma nota de entrar duas vezes.

**O sistema separa entrada de saída sozinho.** O CNPJ do estabelecimento é o critério: se ele é o
emitente, é saída; se é o destinatário, é entrada; se não é nenhum dos dois, a nota é ignorada. E
você não precisa nem digitar o CNPJ — no primeiro pacote o sistema identifica qual é: é o único
que aparece dos dois lados das operações.

Do XML sai tudo o mais que a planilha pedia à mão:

| O que | De onde |
|---|---|
| Bloco do TTD | CFOP + UF + alíquota. 5xxx/12% → bloco 3 · 6xxx/4% → bloco 2 · 6xxx/12% nacional → bloco 1 · 7xxx fora do benefício |
| Natureza | CFOP 3xxx → importação · 1201/1202/2201/2202 ou finNFe=4 → devolução · demais → compra ou venda |
| NCM e origem | Campos nomeados do item |
| CNPJ dos parceiros | Preenche sozinho os 60 que vieram da planilha sem CNPJ |
| Cancelamento | Evento 110111 dentro do pacote cancela a nota e refaz o custeio |

O que não encaixa na tabela do TTD vira **pendência com o motivo escrito** — não vira palpite.
Nenhum valor fiscal é lido de PDF.

Quando houver acesso à máquina que enxerga a pasta de rede, `scripts/pasta_vigiada.py` faz a
mesma coisa sem upload manual.

## O que o sistema faz

| | |
|---|---|
| Lançamento manual | Para o que não tem XML. Mesma trava, mesmo efeito nos dois lados |
| Estoque por saldo | Saldo por produto em qualquer data, valorizado por custeio PEPS |
| Saída sem saldo | Aceita com justificativa obrigatória e lança o acerto datado na mesma data |
| Data futura | Recusada |
| Lançamento retroativo | Refaz o custeio do produto inteiro. Recalcular é idempotente |
| Apuração TTD | Débito, crédito presumido, estorno, Fundo Social, Fundo Educação e carga efetiva |
| Fechamento | Congela o mês; lançar dentro dele exige reabertura com motivo registrado |
| Alíquotas por vigência | Virada de fase do TTD é um registro com data, não alteração no código |
| Exportação em Excel | Apuração no layout da contabilidade e estoque fiscal com movimentação |
| Pendências | Tudo que o sistema aceitou mas alguém precisa olhar, com quem aceitou e por quê |

## Testes

```bash
cd backend && python -m pytest tests -q
```

56 testes. Precisam de um PostgreSQL local (o `docker-compose.yml` sobe um), porque criam e
destroem um banco `lastro_test` a cada execução — não aponte para o Supabase.

Os que mais importam:

- `test_saldo_por_produto_bate_com_o_painel` — o saldo de cada produto bate com o painel da planilha, com as duas diferenças conhecidas explicadas em código.
- `test_julho_bate_centavo_a_centavo` — a apuração derivada do banco reproduz julho/2026: base 3.500.502,40 · ICMS 44.914,38 · Fundo Social 7.819,20 · Fundo Educação 3.742,76 · carga 1,283%.
- `test_bloco_vem_do_proprio_xml` e `test_chave_repetida_nao_duplica`.
- `test_o_pacote_diz_qual_e_o_cnpj_do_estabelecimento`.
- `test_lancamento_em_mes_fechado_e_bloqueado` e `test_reabertura_exige_motivo_e_fica_registrada`.

## Estrutura

```
api/index.py               ponto de entrada da Vercel (importa o mesmo FastAPI)
vercel.json                build do frontend + rota /api para a função Python
backend/
  app/models.py            tabelas
  app/services/xml_nfe.py  leitor de NF-e 4.00
  app/services/importacao.py  pacote ZIP, deduplicação, bloco do TTD, CNPJ automático
  app/services/estoque.py  saldo, custeio PEPS, acerto datado
  app/services/apuracao.py motor TTD com alíquotas por vigência
  app/services/fechamento.py  trava de competência
  app/services/exportacao.py  Excel no layout da contabilidade
  scripts/criar_schema.py · seed_historico.py · pasta_vigiada.py · backup.sh
frontend/src/pages/        Lançar nota · Importar XML · Estoque · Notas · Apuração · Pendências · Alíquotas
```

## Backup

O Supabase faz backup automático do plano, mas **teste uma restauração antes de a planilha virar
somente leitura**. `backend/scripts/backup.sh` faz `pg_dump` para um arquivo local — vale rodar de
vez em quando e guardar fora da nuvem também.
