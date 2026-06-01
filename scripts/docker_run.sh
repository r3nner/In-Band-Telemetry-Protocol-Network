#!/usr/bin/env bash
# Este script entra no ambiente interativo do Docker

# Primeiro garante que o container está rodando
docker-compose up -d

echo "=========================================================="
echo "Entrando no ambiente do Mininet/P4..."
echo "Execute seus comandos Mininet ou Python normalmente."
echo "Exemplo: ./scripts/health_check.sh"
echo "Exemplo: python3 topologies/linear_topo.py --json build/main.json"
echo "=========================================================="

docker exec -it p4-mininet bash
