-- =====================================================================
-- Modulo: Conciliacao e Fechamento de ICMS (normal, empresa toda)
-- Prefixo conc_ para nao colidir com o dominio de importados (TTD 409) ja' existente.
-- Sem chave estrangeira para nenhuma tabela de fora deste modulo.
--
-- Equivalente ao que backend/scripts/migrar_conciliacao_icms.py cria via SQLAlchemy - id
-- inteiro (nao uuid), status/origem/etc como text + check constraint (nao enum nativo), para
-- ficar igual ao padrao do resto do schema do Lastro (ex.: nota.tipo).
-- =====================================================================

create table if not exists conc_periodo (
  id                     serial primary key,
  competencia            varchar(7)  not null,                 -- 'AAAA-MM'
  inscricao_estadual     varchar(14) not null default '260070009',
  status                 varchar(15) not null default 'aberto',
  saldo_credor_anterior  numeric(15,2),
  criado_em              timestamp   not null default now(),
  fechado_em             timestamp,
  fechado_por            varchar(60),
  constraint ck_concperiodo_status check (status in ('aberto','em_analise','fechado')),
  constraint ix_concperiodo_comp unique (competencia, inscricao_estadual)
);

create table if not exists conc_documento_fonte (
  id               serial primary key,
  periodo_id       integer not null references conc_periodo(id) on delete cascade,
  tipo             varchar(30) not null,          -- dime | livro_entradas | raicms
  origem           varchar(15) not null,          -- contabilidade | ecomet
  nome_original    text not null,
  total_documento  numeric(15,2),
  total_extraido   numeric(15,2),
  conferido        boolean not null default false,
  erro             text,
  lido_em          timestamp,
  constraint ck_concdoc_origem check (origem in ('contabilidade','ecomet')),
  constraint ix_concdoc_periodo_tipo unique (periodo_id, tipo, origem)
);

create table if not exists conc_lancamento_entrada (
  id               serial primary key,
  periodo_id       integer not null references conc_periodo(id) on delete cascade,
  documento_id     integer not null references conc_documento_fonte(id) on delete cascade,
  origem           varchar(15) not null,
  data_entrada     date,
  data_documento   date,
  especie          varchar(10),
  serie            varchar(6),
  numero           varchar(20) not null,
  emitente_codigo  varchar(30),
  emitente_cnpj    varchar(14),
  uf               varchar(2),
  valor_contabil   numeric(15,2) not null default 0,
  cfop             varchar(4),
  cod_fiscal       varchar(1),
  base_calculo     numeric(15,2) not null default 0,
  aliquota         numeric(6,2)  not null default 0,
  imposto          numeric(15,2) not null default 0,
  difal            numeric(15,2) not null default 0,
  constraint ck_conclanc_origem check (origem in ('contabilidade','ecomet'))
);
create index if not exists ix_conclanc_periodo_num on conc_lancamento_entrada (periodo_id, origem, numero);
create index if not exists ix_conclanc_periodo_cfop on conc_lancamento_entrada (periodo_id, cfop);

create table if not exists conc_saldo_cfop (
  id              serial primary key,
  periodo_id      integer not null references conc_periodo(id) on delete cascade,
  fonte           varchar(15) not null,    -- dime|raicms|livro_ecomet|cfop_contabil
  tipo            varchar(8)  not null,    -- entrada|saida
  cfop            varchar(4)  not null,
  valor_contabil  numeric(15,2) not null default 0,
  base_calculo    numeric(15,2) not null default 0,
  imposto         numeric(15,2) not null default 0,
  isentas         numeric(15,2) not null default 0,
  outras          numeric(15,2) not null default 0,
  difal           numeric(15,2) not null default 0,
  constraint ck_concsaldo_tipo check (tipo in ('entrada','saida')),
  constraint ix_concsaldo_unico unique (periodo_id, fonte, tipo, cfop)
);

create table if not exists conc_regra_justificativa (
  id                  serial primary key,
  inscricao_estadual  varchar(14) not null default '260070009',
  escopo              varchar(20) not null,    -- cfop | emitente | tipo_divergencia
  chave               varchar(40) not null,
  motivo              text not null,
  ativa               boolean not null default true,
  criada_em           timestamp not null default now(),
  criada_por          varchar(60),
  constraint ix_concregra_unico unique (inscricao_estadual, escopo, chave)
);

create table if not exists conc_divergencia (
  id                   serial primary key,
  periodo_id           integer not null references conc_periodo(id) on delete cascade,
  tipo                 varchar(40) not null,
  severidade           varchar(10) not null,
  status               varchar(25) not null default 'aberta',
  cfop                 varchar(4),
  numero_nota          varchar(20),
  descricao            text not null,
  valor_contabilidade  numeric(15,2),
  valor_ecomet         numeric(15,2),
  diferenca            numeric(15,2),
  justificativa        text,
  regra_id             integer references conc_regra_justificativa(id),
  responsavel          varchar(60),
  resolvido_em         timestamp,
  constraint ck_concdiv_severidade check (severidade in ('alto','revisar')),
  constraint ck_concdiv_status
    check (status in ('aberta','corrigida_ecomet','devolvida_contabilidade','justificada'))
);
create index if not exists ix_concdiv_periodo on conc_divergencia (periodo_id, status, severidade);

create table if not exists conc_apuracao_linha (
  id             serial primary key,
  periodo_id     integer not null references conc_periodo(id) on delete cascade,
  grupo          varchar(20) not null,   -- debito|outros_debitos|credito|outros_creditos|saldo
  ordem          integer not null,
  rotulo         text not null,
  valor          numeric(15,2) not null default 0,
  origem_texto   text,
  editavel       boolean not null default false,
  constraint ix_concapur_unico unique (periodo_id, grupo, ordem)
);

create table if not exists conc_fechamento (
  id                          serial primary key,
  periodo_id                  integer not null unique references conc_periodo(id) on delete restrict,
  total_debitos               numeric(15,2) not null,
  total_creditos              numeric(15,2) not null,
  imposto_a_recolher          numeric(15,2) not null default 0,
  saldo_credor_transportado   numeric(15,2) not null default 0,
  snapshot                    json not null,
  fechado_em                  timestamp not null default now(),
  fechado_por                 varchar(60)
);
