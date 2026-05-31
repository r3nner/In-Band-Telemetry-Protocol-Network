#!/usr/bin/env python3
"""
Testes de integração para o SDN Telemetry Ecosystem.
Testa o banco de dados (em memória), o parser do coletor e a lógica de descoberta de topologia.
"""

import unittest
import struct
from datetime import datetime

# Importa módulos locais do control_plane
from database import TelemetryDB
from topology_discovery import TopologyDiscovery
import telemetry_collector

class TestSDNIntegration(unittest.TestCase):

    def setUp(self):
        # Cria um banco de dados em memória limpo para cada teste
        self.db = TelemetryDB(":memory:")
        self.discovery = TopologyDiscovery(self.db)

    def tearDown(self):
        self.db.close()

    def test_database_and_snapshots(self):
        """Testa inserção de relatórios e criação/exportação de snapshots."""
        # Insere relatórios sintéticos
        self.db.insert_report(switch_id=1, port_id=2, metric_type=0, metric_value=500, switch_timestamp=1000)
        self.db.insert_report(switch_id=2, port_id=1, metric_type=0, metric_value=450, switch_timestamp=1100)
        
        # Recupera e checa se persistiu
        metrics = self.db.get_latest_metrics(metric_type=0, limit=10)
        self.assertEqual(len(metrics), 2)
        
        # Cria uma topologia básica
        topo_name = "test_topo"
        self.discovery.load_or_create(topo_name)
        self.discovery.register_node(topo_name, {"id": 1, "type": "switch"})
        
        # Cria snapshot
        snap_id = self.db.save_snapshot(topo_name)
        self.assertIsNotNone(snap_id)
        
        # Recupera snapshot
        snap_dict = self.db.get_snapshot_by_id(snap_id)
        self.assertIsNotNone(snap_dict)
        self.assertEqual(snap_dict["metadata"]["name"], topo_name)

    def test_telemetry_parser(self):
        """Testa o desempacotamento binário do telemetry_report_t (16 bytes)."""
        # Formato esperado: switch_id(1B), port_id(2B), metric_type(1B), metric_value(6B), timestamp(6B)
        switch_id = 1
        port_id = 2
        metric_type = 0
        metric_value = 1000
        timestamp = 50000
        
        # Construindo o payload binário manualmente
        b_switch = switch_id.to_bytes(1, 'big')
        b_port = port_id.to_bytes(2, 'big')
        b_type = metric_type.to_bytes(1, 'big')
        b_value = metric_value.to_bytes(6, 'big')
        b_ts = timestamp.to_bytes(6, 'big')
        
        payload = b_switch + b_port + b_type + b_value + b_ts
        self.assertEqual(len(payload), 16)
        
        # Executa a função privada do coletor para validar a decodificação
        res = telemetry_collector._parse_report(payload)
        
        self.assertIsNotNone(res)
        res_switch, res_port, res_type, res_value, res_ts = res
        self.assertEqual(res_switch, switch_id)
        self.assertEqual(res_port, port_id)
        self.assertEqual(res_type, metric_type)
        self.assertEqual(res_value, metric_value)
        self.assertEqual(res_ts, timestamp)

    def test_topology_discovery_infer_links(self):
        """Testa a heurística de inferência bidirecional de enlaces baseada em latência."""
        topo_name = "infer_topo"
        self.discovery.load_or_create(topo_name)
        
        # Simulando reports no banco com latências parecidas (diferença < 1000us)
        # S1 na porta 2 relata latência de 500us
        self.db.insert_report(switch_id=1, port_id=2, metric_type=0, metric_value=500, switch_timestamp=1000)
        # S2 na porta 1 relata latência de 550us
        self.db.insert_report(switch_id=2, port_id=1, metric_type=0, metric_value=550, switch_timestamp=1000)
        
        # Aciona a inferência
        inferred = self.discovery.infer_links(topo_name, threshold_us=1000)
        
        # Deve inferir 2 arestas (uma de ida, outra de volta)
        self.assertEqual(inferred, 2)
        
        topo_dict = self.discovery.get_topology_dict(topo_name)
        edges = topo_dict.get("edges", [])
        self.assertEqual(len(edges), 2)
        
        # Verifica se conectou S1 e S2
        sources = [e["source"] for e in edges]
        self.assertIn(1, sources)
        self.assertIn(2, sources)


class TestSDNConfig(unittest.TestCase):
    """Testes para a classe SDNConfig de configuração centralizada."""

    def setUp(self):
        import tempfile
        import os
        # Cria um arquivo temporário para cada teste
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        self.tmp.close()
        self.config_path = self.tmp.name
        # Remove o arquivo para testar a criação automática
        os.remove(self.config_path)

    def tearDown(self):
        import os
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

    def test_create_default_config(self):
        """Testa que um config.json é criado com defaults na primeira execução."""
        import os
        from config import SDNConfig
        cfg = SDNConfig(self.config_path)
        self.assertTrue(os.path.exists(self.config_path))
        self.assertEqual(cfg.udp_port, 9999)
        self.assertEqual(cfg.db_path, "control_plane/telemetry.db")
        self.assertIsNone(cfg.topology_name)

    def test_get_set(self):
        """Testa leitura e escrita de parâmetros."""
        from config import SDNConfig
        cfg = SDNConfig(self.config_path)
        cfg.set("udp_port", 8888)
        self.assertEqual(cfg.get("udp_port"), 8888)
        self.assertTrue(cfg.is_dirty)

    def test_get_invalid_key(self):
        """Testa que acessar chave inexistente levanta KeyError."""
        from config import SDNConfig
        cfg = SDNConfig(self.config_path)
        with self.assertRaises(KeyError):
            cfg.get("chave_inexistente")

    def test_set_invalid_key(self):
        """Testa que alterar chave inexistente levanta KeyError."""
        from config import SDNConfig
        cfg = SDNConfig(self.config_path)
        with self.assertRaises(KeyError):
            cfg.set("chave_inexistente", 123)

    def test_save_and_reload(self):
        """Testa que save persiste e uma nova instância lê os valores salvos."""
        from config import SDNConfig
        cfg1 = SDNConfig(self.config_path)
        cfg1.set("udp_port", 7777)
        cfg1.set("topology_name", "minha_topo")
        cfg1.save()

        # Cria uma nova instância lendo do mesmo arquivo
        cfg2 = SDNConfig(self.config_path)
        self.assertEqual(cfg2.udp_port, 7777)
        self.assertEqual(cfg2.topology_name, "minha_topo")

    def test_reset(self):
        """Testa que reset restaura os valores padrão."""
        from config import SDNConfig
        cfg = SDNConfig(self.config_path)
        cfg.set("udp_port", 1111)
        cfg.set("topology_name", "alterada")
        cfg.reset()
        self.assertEqual(cfg.udp_port, 9999)
        self.assertIsNone(cfg.topology_name)
        self.assertFalse(cfg.is_dirty)

    def test_type_conversion(self):
        """Testa que set converte tipos automaticamente."""
        from config import SDNConfig
        cfg = SDNConfig(self.config_path)
        cfg.set("udp_port", "5555")  # string -> int
        self.assertEqual(cfg.get("udp_port"), 5555)
        self.assertIsInstance(cfg.get("udp_port"), int)

    def test_show_output(self):
        """Testa que show retorna uma string formatada."""
        from config import SDNConfig
        cfg = SDNConfig(self.config_path)
        output = cfg.show()
        self.assertIn("udp_port", output)
        self.assertIn("db_path", output)
        self.assertIn("Configuração do Ecossistema SDN", output)


if __name__ == "__main__":
    unittest.main()

