#!/usr/bin/env python3
"""
Módulo de descoberta e gerenciamento da topologia de rede.

Este módulo provê a classe TopologyDiscovery, responsável por registrar
switches/hosts (nós) e enlaces (arestas) no formato de Schema JSON canônico.
Também inclui heurísticas simples para inferir enlaces baseados em relatórios
de telemetria de latência.
"""

import json
from datetime import datetime

class TopologyDiscovery:
    """Descoberta e manipulação do grafo da topologia em JSON canônico."""

    def __init__(self, db):
        """
        Inicializa com uma instância de TelemetryDB.
        """
        self.db = db

    def load_or_create(self, name: str, description: str = "",
                       controller_ip: str = "10.0.0.254", udp_port: int = 9999) -> dict:
        """
        Tenta carregar a topologia do banco. Se não existir, cria uma topologia
        vazia no formato canônico e salva.
        """
        topo = self.db.load_topology(name)
        if topo is None:
            topo = {
                "metadata": {
                    "name": name,
                    "description": description,
                    "created_at": datetime.now().isoformat(),
                    "controller": {"ip": controller_ip, "udp_port": udp_port}
                },
                "nodes": [],
                "edges": []
            }
            self.db.save_topology(name, topo)
        return topo

    def register_node(self, name: str, node_dict: dict) -> None:
        """
        Adiciona ou atualiza um nó (switch ou host) no grafo da topologia.
        """
        topo = self.load_or_create(name)
        nodes = topo.setdefault("nodes", [])
        
        encontrado = False
        for i, n in enumerate(nodes):
            if n.get("id") == node_dict.get("id"):
                nodes[i] = node_dict
                encontrado = True
                break
        
        if not encontrado:
            nodes.append(node_dict)
            
        self.db.save_topology(name, topo)

    def register_edge(self, name: str, edge_dict: dict) -> None:
        """
        Adiciona ou atualiza um enlace no grafo da topologia.
        A unicidade é definida por (source, source_port).
        """
        topo = self.load_or_create(name)
        edges = topo.setdefault("edges", [])
        
        encontrado = False
        for i, e in enumerate(edges):
            if e.get("source") == edge_dict.get("source") and e.get("source_port") == edge_dict.get("source_port"):
                # Preserva a telemetria existente caso o novo dicionário não a tenha explicitamente
                if "telemetry" in e and "telemetry" not in edge_dict:
                    edge_dict["telemetry"] = e["telemetry"]
                elif "telemetry" in e and edge_dict.get("telemetry") is None:
                    edge_dict["telemetry"] = e["telemetry"]
                edges[i] = edge_dict
                encontrado = True
                break
                
        if not encontrado:
            # Garante que um novo enlace tenha a estrutura básica de telemetria inicializada
            if "telemetry" not in edge_dict or edge_dict["telemetry"] is None:
                edge_dict["telemetry"] = {
                    "latency_us": None, 
                    "throughput_bps": None, 
                    "last_updated": None
                }
            edges.append(edge_dict)
            
        self.db.save_topology(name, topo)

    def infer_links(self, name: str, threshold_us: int = 1000) -> int:
        """
        Infere novos enlaces bidirecionais comparando os relatórios de latência mais recentes.
        Se switch A/porta X e switch B/porta Y reportam latências similares
        (diferença menor que o limiar), eles são considerados vizinhos.
        
        Retorna o número de novos enlaces unidirecionais identificados.
        """
        # Busca relatórios recentes do tipo latência (0)
        reports = self.db.get_latest_metrics(metric_type=0, limit=500)
        
        # Agrupa pelo par (switch_id, port_id) ficando apenas com o mais recente
        latest_reports = {}
        for r in reports:
            chave = (r['switch_id'], r['port_id'])
            if chave not in latest_reports:
                latest_reports[chave] = r
                
        inferred_count = 0
        items = list(latest_reports.values())
        matched = set() # Índices já combinados
        
        # Compara todos os pares
        for i in range(len(items)):
            if i in matched: continue
            r1 = items[i]
            
            for j in range(i+1, len(items)):
                if j in matched: continue
                r2 = items[j]
                
                # Ignora enlaces na mesma caixa (não faz sentido p/ descoberta neste contexto)
                if r1['switch_id'] == r2['switch_id']:
                    continue
                    
                diff = abs(r1['metric_value'] - r2['metric_value'])
                if diff < threshold_us:
                    # Cria a aresta ida (A->B)
                    edge1 = {
                        "id": f"e_inf_{r1['switch_id']}_{r1['port_id']}",
                        "source": r1['switch_id'],
                        "source_port": r1['port_id'],
                        "target": r2['switch_id'],
                        "target_port": r2['port_id'],
                        "bandwidth_mbps": 10.0,
                        "telemetry": {
                            "latency_us": r1['metric_value'], 
                            "throughput_bps": None, 
                            "last_updated": datetime.now().isoformat()
                        }
                    }
                    # Cria a aresta volta (B->A)
                    edge2 = {
                        "id": f"e_inf_{r2['switch_id']}_{r2['port_id']}",
                        "source": r2['switch_id'],
                        "source_port": r2['port_id'],
                        "target": r1['switch_id'],
                        "target_port": r1['port_id'],
                        "bandwidth_mbps": 10.0,
                        "telemetry": {
                            "latency_us": r2['metric_value'], 
                            "throughput_bps": None, 
                            "last_updated": datetime.now().isoformat()
                        }
                    }
                    self.register_edge(name, edge1)
                    self.register_edge(name, edge2)
                    matched.add(i)
                    matched.add(j)
                    inferred_count += 2
                    break
                    
        return inferred_count

    def get_topology_dict(self, name: str) -> dict:
        """
        Retorna o dicionário completo do grafo da topologia.
        """
        return self.db.load_topology(name)

    def print_topology(self, name: str) -> None:
        """
        Imprime a topologia em formato legível no terminal.
        """
        topo = self.get_topology_dict(name)
        if not topo:
            print(f"Topologia '{name}' não encontrada.")
            return
            
        print(f"=== Topologia: {name} ===")
        nodes = topo.get("nodes", [])
        edges = topo.get("edges", [])
        
        print(f"Nós ({len(nodes)}):")
        for n in nodes:
            tipo = n.get("type", "desconhecido")
            label = n.get("label", str(n.get("id")))
            if tipo == "switch":
                portas = [str(p.get("id")) for p in n.get("ports", [])]
                portas_str = ",".join(portas) if portas else "nenhuma"
                print(f"  [switch] {label}  thrift={n.get('thrift_port', '?')}  device_id={n.get('device_id', '?')}  portas: {portas_str}")
            elif tipo == "host":
                print(f"  [host]   {label}  ip={n.get('ip', '?')}")
            else:
                print(f"  [{tipo}] {label}")
                
        print(f"\nEnlaces ({len(edges)}):")
        for e in edges:
            src = str(e.get("source"))
            src_p = str(e.get("source_port", "?"))
            tgt = str(e.get("target"))
            tgt_p = str(e.get("target_port", "?"))
            
            tel = e.get("telemetry", {})
            if tel:
                lat = tel.get("latency_us")
                th = tel.get("throughput_bps")
                
                lat_str = f"{lat/1000.0:.2f}ms" if lat is not None else "?ms"
                th_str = f"{th/1000000.0:.1f}Mbps" if th is not None else "?Mbps"
                
                print(f"  {src}:{src_p} ──── {tgt}:{tgt_p}  latency={lat_str}  throughput={th_str}")
            else:
                print(f"  {src}:{src_p} ──── {tgt}:{tgt_p}  (sem telemetria)")

    def export_gml(self, name: str, filepath: str) -> None:
        """
        Exporta a topologia no formato clássico GML.
        """
        topo = self.get_topology_dict(name)
        if not topo:
            raise ValueError(f"Topologia '{name}' não encontrada no banco.")
            
        linhas = [
            "graph [", 
            "  directed 0"
        ]
        
        for n in topo.get("nodes", []):
            linhas.append("  node [")
            linhas.append(f"    id {n.get('id')}")
            if "label" in n:
                linhas.append(f"    label \"{n.get('label')}\"")
            if "type" in n:
                linhas.append(f"    type \"{n.get('type')}\"")
            linhas.append("  ]")
            
        for e in topo.get("edges", []):
            linhas.append("  edge [")
            linhas.append(f"    source {e.get('source')}")
            linhas.append(f"    target {e.get('target')}")
            if e.get("source_port") is not None:
                linhas.append(f"    source_port {e.get('source_port')}")
            if e.get("target_port") is not None:
                linhas.append(f"    target_port {e.get('target_port')}")
            linhas.append("  ]")
            
        linhas.append("]")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(linhas))
