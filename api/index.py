"""Ponto de entrada antigo da Vercel - RETIRADO em 01/09/2026.

A API deixou de ser publicada como uma unica funcao serverless Python (o jeito zero-config
antigo, "api/" na raiz) e passou a rodar como o service "backend" em container Docker
(ver vercel.json na raiz e backend/Dockerfile.vercel) - so' assim o `pdftotext` (poppler-utils)
fica disponivel em producao para o modulo de Conciliacao de ICMS.

Este arquivo nao roda mais nada: fica so' como marcador, para nao reintroduzir sem querer a
funcao serverless antiga (que colidiria com o rewrite de /api/* pro service "backend"). Se algum
dia isso for revertido, o codigo antigo era so' importar `app.main.app` - ver o historico do git.
"""
