-- Migracao de schema para um banco JA' existente (Supabase em producao).
--
-- Base.metadata.create_all() (chamado no lifespan da aplicacao) so' cria tabela que nao existe -
-- nao adiciona coluna em tabela existente. Este arquivo faz so' isso, em duas frentes:
--
--   1. regra_ttd: colunas ncm/ambito (bloco do TTD passou a ser por NCM+ambito, nao por CFOP) -
--      limpa as 3 linhas antigas (por bloco, sem NCM/ambito) para o proximo start da aplicacao
--      semear a tabela nova (main.py ja' chama semear_regras + backfill_ncm_produtos no lifespan).
--   2. lote_importacao: coluna complementadas (casamento do XML com nota migrada da planilha,
--      sem chave de acesso - "complementada" e' situacao separada de "importada").
--
-- NAO mexe em nota, nota_item, produto nem em nenhum dado de lancamento - so' schema.
-- Idempotente (IF NOT EXISTS): pode rodar mais de uma vez sem problema. Nao precisa parar o
-- sistema pra rodar.
--
-- Como rodar: cole este arquivo inteiro no SQL Editor do Supabase e execute. Ou, se preferir
-- pela linha de comando com o Supabase CLI ja' logado no projeto:
--   supabase db push

ALTER TABLE regra_ttd ADD COLUMN IF NOT EXISTS ncm VARCHAR(8);
ALTER TABLE regra_ttd ADD COLUMN IF NOT EXISTS ambito VARCHAR(15);
DELETE FROM regra_ttd WHERE ncm IS NULL;

ALTER TABLE lote_importacao ADD COLUMN IF NOT EXISTS complementadas INTEGER DEFAULT 0;
