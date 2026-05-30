#!/usr/bin/env python3
"""
Módulo de persistência SQLite para telemetria In-Band.

Armazena relatórios de telemetria, grafos de topologia (no formato canônico JSON)
e snapshots periódicos do estado da rede.
"""

import json
import sqlite3
from datetime import datetime


class TelemetryDB:
    """Gerencia o banco de dados SQLite de telemetria."""

    def __init__(self, db_path: str = "control_plane/telemetry.db"):
        """
        Abre a conexão com o banco e cria as tabelas caso não existam.

        Parâmetros:
            db_path – caminho do arquivo SQLite (padrão: control_plane/telemetry.db)
        """
        self.conn = sqlite3.connect(db_path)
        # Permite acessar colunas por nome nos resultados
        self.conn.row_factory = sqlite3.Row
        self._criar_tabelas()

    # ------------------------------------------------------------------
    # Criação de tabelas
    # ------------------------------------------------------------------
    def _criar_tabelas(self) -> None:
        """Cria as tabelas do schema caso ainda não existam."""
        with self.conn:
            # Tabela de relatórios individuais de telemetria
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_reports (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    switch_id        INTEGER NOT NULL,
                    port_id          INTEGER NOT NULL,
                    metric_type      INTEGER NOT NULL,
                    metric_value     INTEGER NOT NULL,
                    switch_timestamp INTEGER NOT NULL,
                    received_at      TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # Tabela de grafos de topologia (JSON canônico)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS topology_graphs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT NOT NULL UNIQUE,
                    graph_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # Tabela de snapshots completos da topologia
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    topology_name  TEXT NOT NULL,
                    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                    data           TEXT NOT NULL
                )
            """)

    # ------------------------------------------------------------------
    # Relatórios de telemetria
    # ------------------------------------------------------------------
    def insert_report(self, switch_id: int, port_id: int, metric_type: int,
                      metric_value: int, switch_timestamp: int) -> None:
        """
        Insere um relatório de telemetria na tabela telemetry_reports.

        Parâmetros:
            switch_id        – identificador do switch (uint8)
            port_id          – identificador da porta (uint16)
            metric_type      – tipo de métrica (0=latência, 1=throughput, 2=dispersão)
            metric_value     – valor da métrica
            switch_timestamp – timestamp do switch em microssegundos
        """
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO telemetry_reports
                    (switch_id, port_id, metric_type, metric_value, switch_timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (switch_id, port_id, metric_type, metric_value, switch_timestamp),
            )

    def get_latest_metrics(self, switch_id: int = None,
                           metric_type: int = None,
                           limit: int = 100) -> list:
        """
        Retorna os N relatórios mais recentes, opcionalmente filtrados.

        Parâmetros:
            switch_id   – filtro opcional por switch
            metric_type – filtro opcional por tipo de métrica
            limit       – número máximo de resultados (padrão: 100)

        Retorna:
            Lista de dicionários com as colunas da tabela.
        """
        consulta = "SELECT * FROM telemetry_reports WHERE 1=1"
        parametros: list = []

        if switch_id is not None:
            consulta += " AND switch_id = ?"
            parametros.append(switch_id)

        if metric_type is not None:
            consulta += " AND metric_type = ?"
            parametros.append(metric_type)

        consulta += " ORDER BY id DESC LIMIT ?"
        parametros.append(limit)

        cursor = self.conn.execute(consulta, parametros)
        # Converte cada Row para dict
        return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Topologias
    # ------------------------------------------------------------------
    def save_topology(self, name: str, graph_dict: dict) -> None:
        """
        Salva (ou atualiza) uma topologia no banco.

        Faz INSERT OR REPLACE para garantir unicidade pelo nome.
        O campo updated_at é atualizado com o horário corrente.

        Parâmetros:
            name       – nome único da topologia
            graph_dict – dicionário seguindo o Schema de Topologia canônico
        """
        graph_json = json.dumps(graph_dict, ensure_ascii=False)
        agora = datetime.now().isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO topology_graphs (name, graph_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    graph_json = excluded.graph_json,
                    updated_at = excluded.updated_at
                """,
                (name, graph_json, agora),
            )

    def load_topology(self, name: str) -> dict | None:
        """
        Carrega uma topologia pelo nome.

        Retorna:
            O dicionário da topologia, ou None se não existir.
        """
        cursor = self.conn.execute(
            "SELECT graph_json FROM topology_graphs WHERE name = ?",
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return json.loads(row["graph_json"])

    def list_topologies(self) -> list:
        """
        Lista todas as topologias armazenadas.

        Retorna:
            Lista de tuplas (name, created_at, updated_at).
        """
        cursor = self.conn.execute(
            "SELECT name, created_at, updated_at FROM topology_graphs ORDER BY name"
        )
        return [(row["name"], row["created_at"], row["updated_at"])
                for row in cursor.fetchall()]

    def update_edge_telemetry(self, topology_name: str, source_id: int,
                              source_port: int, metric_type: int,
                              metric_value: int) -> None:
        """
        Atualiza os dados de telemetria de uma aresta específica na topologia.

        Localiza a aresta pelo par (source, source_port) e atualiza:
            - latency_us     se metric_type == 0
            - throughput_bps  se metric_type == 1

        Parâmetros:
            topology_name – nome da topologia a ser atualizada
            source_id     – id do nó de origem da aresta (switch_id)
            source_port   – porta de origem da aresta (port_id)
            metric_type   – tipo de métrica (0 ou 1)
            metric_value  – novo valor da métrica
        """
        grafo = self.load_topology(topology_name)
        if grafo is None:
            raise ValueError(f"Topologia '{topology_name}' não encontrada no banco.")

        # Percorre as arestas procurando a que corresponde
        aresta_encontrada = False
        for aresta in grafo.get("edges", []):
            if aresta.get("source") == source_id and aresta.get("source_port") == source_port:
                # Garante que o objeto telemetry existe
                if aresta.get("telemetry") is None:
                    aresta["telemetry"] = {
                        "latency_us": None,
                        "throughput_bps": None,
                        "last_updated": None,
                    }

                # Atualiza o campo correto conforme o tipo de métrica
                if metric_type == 0:
                    aresta["telemetry"]["latency_us"] = metric_value
                elif metric_type == 1:
                    aresta["telemetry"]["throughput_bps"] = metric_value

                aresta["telemetry"]["last_updated"] = datetime.now().isoformat()
                aresta_encontrada = True
                break

        if not aresta_encontrada:
            raise ValueError(
                f"Aresta com source={source_id}, source_port={source_port} "
                f"não encontrada na topologia '{topology_name}'."
            )

        # Salva a topologia atualizada de volta no banco
        self.save_topology(topology_name, grafo)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    def save_snapshot(self, topology_name: str) -> int:
        """
        Cria um snapshot da topologia atual.

        Copia o JSON completo da topologia para a tabela snapshots.

        Parâmetros:
            topology_name – nome da topologia a ser fotografada

        Retorna:
            O ID do snapshot criado.
        """
        grafo = self.load_topology(topology_name)
        if grafo is None:
            raise ValueError(
                f"Topologia '{topology_name}' não encontrada para snapshot."
            )

        dados_json = json.dumps(grafo, ensure_ascii=False)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO snapshots (topology_name, data)
                VALUES (?, ?)
                """,
                (topology_name, dados_json),
            )
            return cursor.lastrowid

    def get_snapshots(self, limit: int = 10) -> list:
        """
        Retorna os N snapshots mais recentes.

        Retorna:
            Lista de tuplas (id, topology_name, created_at).
        """
        cursor = self.conn.execute(
            "SELECT id, topology_name, created_at FROM snapshots "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [(row["id"], row["topology_name"], row["created_at"])
                for row in cursor.fetchall()]

    def get_snapshot_by_id(self, snapshot_id: int) -> dict | None:
        """
        Retorna o conteúdo completo de um snapshot pelo ID.

        Retorna:
            O dicionário completo da topologia no momento do snapshot,
            ou None se o ID não existir.
        """
        cursor = self.conn.execute(
            "SELECT data FROM snapshots WHERE id = ?",
            (snapshot_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return json.loads(row["data"])

    # ------------------------------------------------------------------
    # Encerramento
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Fecha a conexão com o banco de dados."""
        self.conn.close()
