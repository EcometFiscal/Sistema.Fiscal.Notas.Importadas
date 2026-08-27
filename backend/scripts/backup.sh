#!/usr/bin/env sh
# Condicao inegociavel do projeto: backup diario PARA FORA do servidor e restauracao testada.
# Sugestao de agendamento no host (crontab -e):
#   15 2 * * *  /caminho/lastro-app/backend/scripts/backup.sh >> /var/log/lastro-backup.log 2>&1
#
# Restaurar (teste isto pelo menos uma vez antes de desligar a planilha):
#   gunzip -c lastro-2026-08-27.sql.gz | docker compose exec -T banco psql -U lastro -d lastro
set -e
DESTINO="${DESTINO:-/backup}"
ARQUIVO="$DESTINO/lastro-$(date +%F).sql.gz"
docker compose exec -T banco pg_dump -U "${POSTGRES_USER:-lastro}" "${POSTGRES_DB:-lastro}" | gzip > "$ARQUIVO"
echo "$(date +'%F %T') backup gravado em $ARQUIVO ($(du -h "$ARQUIVO" | cut -f1))"
# guarda 30 dias
find "$DESTINO" -name 'lastro-*.sql.gz' -mtime +30 -delete
