import os

# Local: postgres do docker-compose. Producao: string do Supabase (pooler, porta 6543).
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://lastro:lastro@localhost:5432/lastro")
APP_NAME = "Lastro - Estoque e Apuracao de Importados"
VERSION = "0.5.0"
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# Criar as tabelas na subida so' faz sentido em desenvolvimento. Em serverless, cada chamada
# fria pagaria por isso - o schema e' criado uma vez por scripts/criar_schema.py.
CRIAR_TABELAS = os.getenv("CRIAR_TABELAS", "0" if os.getenv("VERCEL") else "1") == "1"

# Vazio = qualquer um com o link entra (escolha de 27/08/2026). Definir esta variavel de
# ambiente liga a trava de senha sem mexer em nenhuma linha de codigo.
SENHA_ACESSO = os.getenv("SENHA_ACESSO", "").strip()
