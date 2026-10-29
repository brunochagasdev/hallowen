-- Cole este texto no SQL Editor do Supabase e clique em Run.
create table if not exists votos (
  id            bigint generated always as identity primary key,
  criado_em     timestamptz not null default now(),
  jurado        text not null,
  jurado_chave  text not null,
  serie         text not null,
  aluno         text not null,
  aluno_chave   text not null,
  criatividade  numeric(3,1) not null check (criatividade between 0 and 2.5),
  execucao      numeric(3,1) not null check (execucao between 0 and 2.5),
  performance   numeric(3,1) not null check (performance between 0 and 2.5),
  adequacao     numeric(3,1) not null check (adequacao between 0 and 2.5),
  nota_final    numeric(4,1) generated always as (criatividade + execucao + performance + adequacao) stored,
  -- um voto por jurado para cada aluno, garantido pelo banco
  unique (jurado_chave, serie, aluno_chave)
);

-- Bloqueia acesso público; só o app (com a chave secreta) lê e grava.
alter table votos enable row level security;
