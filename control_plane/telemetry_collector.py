#!/usr/bin/env python3
"""
Coletor de telemetria In-Band para BMv2.

Escuta pacotes UDP enviados pelo switch P4 contendo relatórios de telemetria
(header telemetry_report_t) e invoca um callback para cada relatório recebido.

Executar standalone:
    python3 control_plane/telemetry_collector.py --port 9999 --log-level DEBUG
"""

import argparse
import logging
import socket
import struct
import sys
from typing import Optional

from database import TelemetryDB

# ---------------------------------------------------------------------------
# Logger do módulo
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapa de tipos de métrica (conforme definido no programa P4)
# ---------------------------------------------------------------------------
METRIC_TYPE_NAMES = {
    0: "latência",
    1: "throughput",
    2: "dispersão",
}

# ---------------------------------------------------------------------------
# Contador global de relatórios recebidos (acessível externamente)
# ---------------------------------------------------------------------------
report_count: int = 0

# ---------------------------------------------------------------------------
# Instância do banco de dados (inicializada no main ou externamente)
# ---------------------------------------------------------------------------
db_instance: Optional[TelemetryDB] = None

# ---------------------------------------------------------------------------
# Nome da topologia ativa (definido via argparse ou externamente)
# ---------------------------------------------------------------------------
topology_name: Optional[str] = None

# ---------------------------------------------------------------------------
# Layout do wire format do header telemetry_report_t (16 bytes)
# ---------------------------------------------------------------------------
#
#  Offset  Tamanho  Campo          Formato struct
#  ------  -------  -------------- ---------------
#   0       1 B     switch_id      B  (uint8)
#   1       2 B     port_id        H  (uint16 big-endian, 9 bits úteis)
#   3       1 B     metric_type    B  (uint8)
#   4       6 B     metric_value   — (manual via int.from_bytes)
#  10       6 B     timestamp      — (manual via int.from_bytes)
#  ------  -------
#  Total:  16 bytes
#
REPORT_SIZE = 16
# Formato struct para os primeiros 4 bytes: switch_id(1B) + port_id(2B) + metric_type(1B)
HEADER_FMT = "!BHB"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 4 bytes


def _parse_report(data: bytes):
    """
    Faz o parsing de um relatório de telemetria de 16 bytes.

    Retorna uma tupla:
        (switch_id, port_id, metric_type, metric_value, timestamp)

    Levanta ValueError se o tamanho do payload for insuficiente.
    """
    if len(data) < REPORT_SIZE:
        raise ValueError(
            f"Payload muito curto: esperado {REPORT_SIZE} bytes, "
            f"recebido {len(data)} bytes"
        )

    # Desempacota os primeiros 4 bytes com struct
    switch_id, port_id, metric_type = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])

    # Converte os 6 bytes de metric_value (offset 4..10) manualmente
    metric_value = int.from_bytes(data[4:10], "big")

    # Converte os 6 bytes de timestamp (offset 10..16) manualmente
    timestamp = int.from_bytes(data[10:16], "big")

    return switch_id, port_id, metric_type, metric_value, timestamp


def on_report(switch_id: int, port_id: int, metric_type: int,
              metric_value: int, timestamp: int) -> None:
    """
    Callback padrão: imprime o relatório e persiste no banco de dados.

    Formato de impressão:
        [REPORT] switch=<id> port=<port> tipo=<nome> valor=<val> ts=<ts>

    Se db_instance estiver inicializado, insere o relatório na tabela
    telemetry_reports e tenta atualizar a aresta correspondente na topologia.
    """
    global topology_name  # noqa: PLW0602 — leitura da variável global

    tipo_nome = METRIC_TYPE_NAMES.get(metric_type, f"desconhecido({metric_type})")
    print(
        f"[REPORT] switch={switch_id} port={port_id} "
        f"tipo={tipo_nome} valor={metric_value} ts={timestamp}"
    )

    # Persistência no banco de dados SQLite
    if db_instance is not None:
        db_instance.insert_report(
            switch_id, port_id, metric_type, metric_value, timestamp
        )
        # Tenta atualizar a aresta na topologia (pode falhar se não houver topologia)
        if topology_name is not None:
            try:
                db_instance.update_edge_telemetry(
                    topology_name, switch_id, port_id, metric_type, metric_value
                )
            except Exception:  # noqa: BLE001 — não interromper o coletor
                logger.debug(
                    "Não foi possível atualizar aresta na topologia '%s' "
                    "para switch=%d port=%d",
                    topology_name, switch_id, port_id,
                )


def run_collector(port: int = 9999, callback=None) -> None:
    """
    Inicia o loop de coleta de telemetria UDP.

    Parâmetros:
        port     – porta UDP para bind (padrão: 9999)
        callback – função chamada para cada relatório recebido. Assinatura:
                   callback(switch_id, port_id, metric_type, metric_value, timestamp)
                   Se None, usa on_report (impressão no stdout).

    Esta função pode ser chamada tanto standalone quanto dentro de uma thread.
    O loop é interrompido por KeyboardInterrupt (Ctrl+C).
    """
    global report_count  # noqa: PLW0603 — contador global intencional

    if callback is None:
        callback = on_report

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind(("0.0.0.0", port))
        logger.info("Coletor de telemetria escutando em 0.0.0.0:%d", port)

        while True:
            data, addr = sock.recvfrom(1024)
            logger.debug(
                "Pacote recebido de %s:%d (%d bytes)", addr[0], addr[1], len(data)
            )

            try:
                switch_id, port_id, metric_type, metric_value, timestamp = (
                    _parse_report(data)
                )
            except ValueError as err:
                logger.warning("Relatório inválido de %s:%d — %s", addr[0], addr[1], err)
                continue

            report_count += 1
            logger.debug(
                "Relatório #%d parseado: switch=%d port=%d tipo=%d valor=%d ts=%d",
                report_count, switch_id, port_id, metric_type, metric_value, timestamp,
            )

            try:
                callback(switch_id, port_id, metric_type, metric_value, timestamp)
            except Exception:  # noqa: BLE001 — não deixar callback derrubar o coletor
                logger.exception("Erro no callback para relatório #%d", report_count)

    except KeyboardInterrupt:
        logger.info(
            "Encerramento solicitado (Ctrl+C). Total de relatórios: %d", report_count
        )
    finally:
        sock.close()
        logger.info("Socket UDP fechado.")


def main() -> int:
    """Ponto de entrada para execução standalone via linha de comando."""
    global db_instance, topology_name  # noqa: PLW0603 — inicialização global intencional

    # Carrega a configuração centralizada para obter os defaults
    try:
        from config import SDNConfig
        cfg = SDNConfig()
        default_port = cfg.udp_port
        default_log = cfg.log_level
        default_topo = cfg.topology_name
        default_db = cfg.db_path
    except Exception:
        default_port = 9999
        default_log = "INFO"
        default_topo = None
        default_db = "control_plane/telemetry.db"

    parser = argparse.ArgumentParser(
        description="Coletor de telemetria In-Band para BMv2 (UDP)."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help="Porta UDP para escuta (padrão: {})".format(default_port),
    )
    parser.add_argument(
        "--log-level",
        default=default_log,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Nível de log (padrão: {})".format(default_log),
    )
    parser.add_argument(
        "--topology-name",
        default=default_topo,
        help="Nome da topologia ativa para atualização de arestas (padrão: {})".format(default_topo),
    )

    args = parser.parse_args()

    # Configura o logging com o nível escolhido
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Inicializa o banco de dados de telemetria
    db_instance = TelemetryDB(default_db)
    topology_name = args.topology_name
    logger.info("Banco de dados de telemetria inicializado.")
    if topology_name:
        logger.info("Topologia ativa: %s", topology_name)

    logger.info("Iniciando coletor de telemetria na porta %d …", args.port)
    run_collector(port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
