#!/usr/bin/env bash
# Corre UN ciclo del agente de noticias a mano, leyendo la clave de
# agent/.env (nunca se commitea — ya está en .gitignore).
#
# Primera vez:
#   echo 'ANTHROPIC_API_KEY=sk-ant-tu-clave-aqui' > agent/.env
#   chmod +x agent/run_local.sh
#
# Cada vez que quieras un ciclo nuevo:
#   ./agent/run_local.sh
#
# Este script solo corre agent.py (noticias). Para probar juridica.py o
# resenas.py a mano (Revista Jurídica / reseñas, leen de Supabase — ver
# agent/supabase_client.py) agrega también estas líneas a agent/.env y
# haz `set -a; source agent/.env; set +a` en tu shell antes de correrlos:
#   SUPABASE_URL=https://tu-proyecto.supabase.co
#   SUPABASE_SERVICE_ROLE_KEY=tu-service-role-key

set -euo pipefail
cd "$(dirname "$0")/.."   # raíz del proyecto (01-contexto-portal/)

if [ -f agent/.env ]; then
  set -a
  # shellcheck disable=SC1091
  source agent/.env
  set +a
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "⚠ No encontré ANTHROPIC_API_KEY."
  echo "  Crea agent/.env con esta línea (reemplaza con tu clave real):"
  echo "  ANTHROPIC_API_KEY=sk-ant-tu-clave-aqui"
  exit 1
fi

python3 agent/agent.py
