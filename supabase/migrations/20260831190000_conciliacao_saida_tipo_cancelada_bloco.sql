-- Migracao de schema para um banco JA' existente (Supabase em producao).
--
-- Amplia o modulo de Conciliacao de ICMS (conc_*) para tambem conciliar o Livro de Saidas
-- (contabilidade x Empresa), alem do Livro de Entradas ja' existente. So' schema, tres colunas
-- novas:
--
--   1. conc_lancamento_entrada.tipo (entrada|saida, default 'entrada') - a tabela agora guarda
--      nota a nota de entrada OU de saida; o nome da tabela ficou de antes, quando so' existia
--      entrada.
--   2. conc_lancamento_entrada.cancelada (boolean, default false) - nota que a contabilidade
--      zerou e o Ecomet manteve com anotacao "Cancelada" (achado real da competencia 07/2026).
--   3. conc_divergencia.bloco (entrada|saida|null) - separa os 3 relatorios de divergencia
--      (CFOP Dime x Livro Fiscal, Livro de Entradas, Livro de Saidas).
--
-- Tabelas ja' existem e estao vazias (nenhuma competencia com saida foi importada ainda) - ALTER
-- simples, sem backfill de dado. Idempotente (IF NOT EXISTS / DROP CONSTRAINT IF EXISTS antes de
-- recriar): pode rodar mais de uma vez sem problema. Nao precisa parar o sistema pra rodar.
--
-- Como rodar: cole este arquivo inteiro no SQL Editor do Supabase e execute. Ou, se preferir
-- pela linha de comando com o Supabase CLI ja' logado no projeto:
--   supabase db push

ALTER TABLE conc_lancamento_entrada ADD COLUMN IF NOT EXISTS tipo VARCHAR(8) NOT NULL DEFAULT 'entrada';
ALTER TABLE conc_lancamento_entrada ADD COLUMN IF NOT EXISTS cancelada BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE conc_lancamento_entrada DROP CONSTRAINT IF EXISTS ck_conclanc_tipo;
ALTER TABLE conc_lancamento_entrada ADD CONSTRAINT ck_conclanc_tipo CHECK (tipo in ('entrada','saida'));

ALTER TABLE conc_divergencia ADD COLUMN IF NOT EXISTS bloco VARCHAR(8);
ALTER TABLE conc_divergencia DROP CONSTRAINT IF EXISTS ck_concdiv_bloco;
ALTER TABLE conc_divergencia ADD CONSTRAINT ck_concdiv_bloco CHECK (bloco is null or bloco in ('entrada','saida'));
