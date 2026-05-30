#!/usr/bin/env python3
"""
Interface de Linha de Comando (CLI) para o Ecossistema SDN.
Integra banco de dados, descoberta de topologia e coleta de telemetria UDP.
"""

import argparse
import cmd
import json
import logging
import shlex
import sys
import threading

from database import TelemetryDB
from topology_discovery import TopologyDiscovery
import telemetry_collector

class SDNCLI(cmd.Cmd):
    intro = "Bem-vindo ao Ecossistema SDN. Digite 'help' ou '?' para listar os comandos.\n"
    prompt = "sdn> "

    def __init__(self, db_path: str, udp_port: int, initial_topo: str = None):
        super().__init__()
        
        # Inicialização do banco e discovery
        self.db = TelemetryDB(db_path)
        self.discovery = TopologyDiscovery(self.db)
        
        # Define topologia ativa
        self.active_topology = None
        
        # Injeção da instância do banco no coletor
        telemetry_collector.db_instance = self.db
        
        if initial_topo:
            self.do_topology(f"load {initial_topo}")
            
        # Iniciar thread do coletor UDP
        self.collector_thread = threading.Thread(
            target=telemetry_collector.run_collector,
            kwargs={'port': udp_port},
            daemon=True
        )
        self.collector_thread.start()
        print(f"[INFO] Coletor UDP rodando em background na porta {udp_port}")

    def emptyline(self):
        """Impede que a tecla enter repita o último comando executado."""
        pass

    def do_topology(self, arg):
        """
        Gerencia topologias. Subcomandos:
          topology list
          topology load <name>
          topology show
          topology export <name> <file>
          topology export-gml <name> <file>
          topology infer
        """
        args = shlex.split(arg)
        if not args:
            print("Uso: topology <subcomando> [argumentos]")
            return
            
        subcmd = args[0]
        
        try:
            if subcmd == "list":
                topos = self.db.list_topologies()
                if not topos:
                    print("Nenhuma topologia encontrada.")
                else:
                    print("Topologias salvas:")
                    for name, c_at, u_at in topos:
                        marca = "*" if name == self.active_topology else " "
                        print(f" [{marca}] {name} (Criada: {c_at}, Atualizada: {u_at})")
                        
            elif subcmd == "load":
                if len(args) < 2:
                    print("Erro: nome da topologia não fornecido. Uso: topology load <name>")
                    return
                name = args[1]
                self.discovery.load_or_create(name)
                self.active_topology = name
                # Atualizar a variável do coletor para associar os relatórios recebidos a esta topologia
                telemetry_collector.topology_name = name
                print(f"Topologia ativa definida para: '{name}'")
                
            elif subcmd == "show":
                if not self.active_topology:
                    print("Nenhuma topologia ativa. Use 'topology load <name>'.")
                    return
                self.discovery.print_topology(self.active_topology)
                
            elif subcmd == "export":
                if len(args) < 3:
                    print("Erro: argumentos insuficientes. Uso: topology export <name> <file>")
                    return
                name, filepath = args[1], args[2]
                topo_dict = self.discovery.get_topology_dict(name)
                if not topo_dict:
                    print(f"Topologia '{name}' não encontrada.")
                    return
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(topo_dict, f, indent=2, ensure_ascii=False)
                print(f"Topologia '{name}' exportada em JSON bruto para {filepath}")
                
            elif subcmd == "export-gml":
                if len(args) < 3:
                    print("Erro: argumentos insuficientes. Uso: topology export-gml <name> <file>")
                    return
                name, filepath = args[1], args[2]
                try:
                    self.discovery.export_gml(name, filepath)
                    print(f"Topologia '{name}' exportada em GML para {filepath}")
                except ValueError as e:
                    print(f"Erro: {e}")
                    
            elif subcmd == "infer":
                if not self.active_topology:
                    print("Nenhuma topologia ativa. Use 'topology load <name>'.")
                    return
                count = self.discovery.infer_links(self.active_topology)
                print(f"{count} links unidirecionais inferidos e salvos na topologia '{self.active_topology}'.")
                
            else:
                print(f"Subcomando desconhecido: {subcmd}")
                
        except Exception as e:
            print(f"Erro ao executar 'topology {subcmd}': {e}")

    def do_metric(self, arg):
        """
        Gerencia quais métricas estão ativas nas portas.
        Uso: 
          metric enable <switch_id> <egress_port> <reg_index> <remote_index> [clone_session]
          metric disable <switch_id> <entry_handle>
          metric list <switch_id>
        """
        args = shlex.split(arg)
        if not args:
            print("Uso: metric <enable|disable|list> [argumentos]")
            return
            
        subcmd = args[0]
        
        if not self.active_topology:
            print("Erro: Nenhuma topologia ativa carregada. Use 'topology load <name>'.")
            return
            
        topo = self.discovery.get_topology_dict(self.active_topology)
        
        def get_thrift_port(sid):
            for n in topo.get("nodes", []):
                if n.get("type") == "switch" and n.get("id") == sid:
                    return n.get("thrift_port")
            return None

        import subprocess
        
        try:
            if subcmd == "enable":
                if len(args) < 5:
                    print("Uso: metric enable <switch_id> <egress_port> <reg_index> <remote_index> [clone_session]")
                    return
                switch_id = int(args[1])
                egress_port = int(args[2])
                reg_index = int(args[3])
                remote_index = int(args[4])
                clone_session = int(args[5]) if len(args) > 5 else 250
                
                thrift_port = get_thrift_port(switch_id)
                if thrift_port is None:
                    print(f"Erro: switch_id {switch_id} não encontrado.")
                    return
                    
                cmd_str = f"table_add probe_profile enable_probe {egress_port} => {reg_index} {remote_index} {clone_session}"
                process = subprocess.Popen(["simple_switch_CLI", "--thrift-port", str(thrift_port)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(input=cmd_str + "\n")
                if process.returncode != 0:
                    print(f"Erro CLI: {stderr}")
                else:
                    import re
                    match = re.search(r'Entry has been added with handle (\d+)', stdout)
                    handle = match.group(1) if match else "?"
                    print(f"Métrica ativada no switch {switch_id}. Handle da entrada: {handle}")
                    
            elif subcmd == "disable":
                if len(args) < 3:
                    print("Uso: metric disable <switch_id> <entry_handle>")
                    return
                switch_id = int(args[1])
                handle = int(args[2])
                
                thrift_port = get_thrift_port(switch_id)
                if thrift_port is None:
                    print(f"Erro: switch_id {switch_id} não encontrado.")
                    return
                    
                cmd_str = f"table_delete probe_profile {handle}"
                process = subprocess.Popen(["simple_switch_CLI", "--thrift-port", str(thrift_port)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(input=cmd_str + "\n")
                if process.returncode != 0:
                    print(f"Erro CLI: {stderr}")
                else:
                    print(f"Métrica desativada no switch {switch_id} (Handle {handle}).")
                    
            elif subcmd == "list":
                if len(args) < 2:
                    print("Uso: metric list <switch_id>")
                    return
                switch_id = int(args[1])
                thrift_port = get_thrift_port(switch_id)
                if thrift_port is None:
                    print(f"Erro: switch_id {switch_id} não encontrado.")
                    return
                    
                cmd_str = "table_dump probe_profile"
                process = subprocess.Popen(["simple_switch_CLI", "--thrift-port", str(thrift_port)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(input=cmd_str + "\n")
                if process.returncode != 0:
                    print(f"Erro CLI: {stderr}")
                else:
                    print(f"--- Configuração de Sondas (Switch {switch_id}) ---")
                    for line in stdout.splitlines():
                        if "enable_probe" in line or "no_probe" in line:
                            print(line)
                            
            else:
                print(f"Subcomando desconhecido: {subcmd}")
                
        except ValueError:
            print("Erro: IDs, portas e handles devem ser números inteiros.")
        except Exception as e:
            print(f"Erro ao executar 'metric {subcmd}': {e}")

    def do_snapshot(self, arg):
        """
        Gerencia snapshots da rede. Subcomandos:
          snapshot create
          snapshot list
          snapshot show <id>
          snapshot diff <id_a> <id_b>
          snapshot export <id> <file>
        """
        args = shlex.split(arg)
        if not args:
            print("Uso: snapshot <subcomando> [argumentos]")
            return
            
        subcmd = args[0]
        
        try:
            if subcmd == "create":
                if not self.active_topology:
                    print("Erro: Nenhuma topologia ativa carregada. Use 'topology load <name>'.")
                    return
                snap_id = self.db.save_snapshot(self.active_topology)
                if snap_id:
                    snap_dict = self.db.get_snapshot_by_id(snap_id)
                    nodes_count = len(snap_dict.get("nodes", []))
                    edges_count = len(snap_dict.get("edges", []))
                    print(f"Snapshot #{snap_id} criado: {nodes_count} nós, {edges_count} enlaces.")
                    
                    import os
                    os.makedirs("control_plane/snapshots", exist_ok=True)
                    filepath = f"control_plane/snapshots/snapshot_{snap_id}.json"
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(snap_dict, f, indent=2, ensure_ascii=False)
                    print(f"Cópia automática salva em: {filepath}")
                else:
                    print("Falha ao criar snapshot (topologia não encontrada no banco).")
                    
            elif subcmd == "list":
                snaps = self.db.get_snapshots()
                if not snaps:
                    print("Nenhum snapshot salvo.")
                else:
                    print("Snapshots salvos:")
                    for snap_id, topo_name, created_at in snaps:
                        snap_dict = self.db.get_snapshot_by_id(snap_id)
                        nodes = len(snap_dict.get("nodes", []))
                        edges = len(snap_dict.get("edges", []))
                        print(f" [ID: {snap_id}] Topo: {topo_name} | Nós: {nodes} | Enlaces: {edges} | Criado em: {created_at}")
                        
            elif subcmd == "show":
                if len(args) < 2:
                    print("Uso: snapshot show <id>")
                    return
                snap_id = int(args[1])
                snap_dict = self.db.get_snapshot_by_id(snap_id)
                if not snap_dict:
                    print(f"Snapshot com ID {snap_id} não encontrado.")
                    return
                    
                print(f"=== Snapshot #{snap_id} ===")
                nodes = snap_dict.get("nodes", [])
                edges = snap_dict.get("edges", [])
                print(f"Nós ({len(nodes)}):")
                for n in nodes:
                    tipo = n.get("type", "?")
                    lbl = n.get("label", str(n.get("id")))
                    th = f" thrift={n.get('thrift_port')}" if n.get('thrift_port') else ""
                    ip = f" ip={n.get('ip')}" if n.get('ip') else ""
                    print(f"  [{tipo}] {lbl}{th}{ip}")
                print(f"\nEnlaces ({len(edges)}):")
                for e in edges:
                    src = e.get("source")
                    src_p = e.get("source_port", "?")
                    tgt = e.get("target")
                    tgt_p = e.get("target_port", "?")
                    lat = e.get("telemetry", {}).get("latency_us")
                    th = e.get("telemetry", {}).get("throughput_bps")
                    lat_str = f"{lat/1000.0:.2f}ms" if lat else "?ms"
                    th_str = f"{th/1000000.0:.1f}Mbps" if th else "?Mbps"
                    print(f"  {src}:{src_p} -> {tgt}:{tgt_p}  lat: {lat_str}  th: {th_str}")
                    
            elif subcmd == "diff":
                if len(args) < 3:
                    print("Uso: snapshot diff <id_a> <id_b>")
                    return
                id_a, id_b = int(args[1]), int(args[2])
                snap_a = self.db.get_snapshot_by_id(id_a)
                snap_b = self.db.get_snapshot_by_id(id_b)
                if not snap_a or not snap_b:
                    print("Erro: IDs de snapshot inválidos.")
                    return
                
                print(f"=== Diff: Snapshot #{id_a} -> Snapshot #{id_b} ===")
                edges_a = {(e.get("source"), e.get("source_port")): e for e in snap_a.get("edges", [])}
                edges_b = {(e.get("source"), e.get("source_port")): e for e in snap_b.get("edges", [])}
                
                for k in set(edges_a.keys()).union(edges_b.keys()):
                    ea = edges_a.get(k)
                    eb = edges_b.get(k)
                    if ea and not eb:
                        print(f"[-] Enlace removido: {k[0]}:{k[1]} -> {ea.get('target')}:{ea.get('target_port')}")
                    elif eb and not ea:
                        print(f"[+] Enlace adicionado: {k[0]}:{k[1]} -> {eb.get('target')}:{eb.get('target_port')}")
                    else:
                        l_a = ea.get("telemetry", {}).get("latency_us")
                        l_b = eb.get("telemetry", {}).get("latency_us")
                        if l_a is not None and l_b is not None and l_a != l_b:
                            pct = ((l_b - l_a) / l_a) * 100 if l_a else 0
                            print(f"[~] {k[0]}:{k[1]} -> {ea.get('target')}:{ea.get('target_port')} latência: {l_a/1000.0:.2f}ms -> {l_b/1000.0:.2f}ms ({pct:+.1f}%)")

            elif subcmd == "export":
                if len(args) < 3:
                    print("Erro: argumentos insuficientes. Uso: snapshot export <id> <file>")
                    return
                snap_id = int(args[1])
                filepath = args[2]
                snap_dict = self.db.get_snapshot_by_id(snap_id)
                if not snap_dict:
                    print(f"Snapshot com ID {snap_id} não encontrado.")
                    return
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(snap_dict, f, indent=2, ensure_ascii=False)
                print(f"Snapshot {snap_id} exportado em JSON para {filepath}")
                
            else:
                print(f"Subcomando desconhecido: {subcmd}")
                
        except ValueError:
            print("Erro: IDs devem ser números inteiros.")
        except Exception as e:
            print(f"Erro ao executar 'snapshot {subcmd}': {e}")

    def do_exit(self, arg):
        """Encerra a CLI e o banco de dados."""
        print("Encerrando SDN CLI...")
        self.db.close()
        return True

    def do_quit(self, arg):
        """Encerra a CLI."""
        return self.do_exit(arg)

    def do_set(self, arg):
        """
        Altera configurações no Data Plane.
        Uso: set frequency <switch_id> <port_id> <valor_em_ms>
        """
        args = shlex.split(arg)
        if len(args) < 4 or args[0] != "frequency":
            print("Uso: set frequency <switch_id> <port_id> <valor_em_ms>")
            return
            
        try:
            switch_id = int(args[1])
            port_id = int(args[2])
            ms_val = int(args[3])
        except ValueError:
            print("Erro: switch_id, port_id e valor_em_ms devem ser inteiros.")
            return

        if not self.active_topology:
            print("Erro: Nenhuma topologia ativa carregada. Use 'topology load <name>'.")
            return
            
        topo = self.discovery.get_topology_dict(self.active_topology)
        thrift_port = None
        for n in topo.get("nodes", []):
            if n.get("type") == "switch" and n.get("id") == switch_id:
                thrift_port = n.get("thrift_port")
                break
                
        if thrift_port is None:
            print(f"Erro: switch_id {switch_id} não encontrado na topologia ativa.")
            return
            
        us_val = ms_val * 1000
        cmd_str = f"register_write probe_interval_reg {port_id} {us_val}"
        print(f"Executando no switch {switch_id} (thrift {thrift_port}): {cmd_str}")
        
        import subprocess
        try:
            process = subprocess.Popen(
                ["simple_switch_CLI", "--thrift-port", str(thrift_port)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(input=cmd_str + "\n")
            if process.returncode != 0:
                print(f"Erro ao executar CLI do Thrift: {stderr}")
            else:
                print("Frequência atualizada com sucesso.")
        except Exception as e:
            print(f"Erro de subprocesso: {e}")

    def do_show(self, arg):
        """
        Exibe configurações do Data Plane.
        Uso: show frequency <switch_id> <port_id>
        """
        args = shlex.split(arg)
        if len(args) < 3 or args[0] != "frequency":
            print("Uso: show frequency <switch_id> <port_id>")
            return
            
        try:
            switch_id = int(args[1])
            port_id = int(args[2])
        except ValueError:
            print("Erro: switch_id e port_id devem ser inteiros.")
            return

        if not self.active_topology:
            print("Erro: Nenhuma topologia ativa carregada. Use 'topology load <name>'.")
            return
            
        topo = self.discovery.get_topology_dict(self.active_topology)
        thrift_port = None
        for n in topo.get("nodes", []):
            if n.get("type") == "switch" and n.get("id") == switch_id:
                thrift_port = n.get("thrift_port")
                break
                
        if thrift_port is None:
            print(f"Erro: switch_id {switch_id} não encontrado na topologia ativa.")
            return
            
        cmd_str = f"register_read probe_interval_reg {port_id}"
        
        import subprocess
        import re
        try:
            process = subprocess.Popen(
                ["simple_switch_CLI", "--thrift-port", str(thrift_port)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(input=cmd_str + "\n")
            if process.returncode != 0:
                print(f"Erro ao executar CLI do Thrift: {stderr}")
            else:
                match = re.search(r'=\s*(\d+)', stdout)
                if match:
                    us_val = int(match.group(1))
                    ms_val = us_val / 1000.0
                    print(f"Switch {switch_id}, Porta {port_id}: Intervalo = {ms_val} ms ({us_val} µs)")
                else:
                    print(f"Não foi possível extrair a resposta do Thrift: {stdout}")
        except Exception as e:
            print(f"Erro de subprocesso: {e}")



def main():
    parser = argparse.ArgumentParser(description="CLI do Ecossistema SDN")
    parser.add_argument("--db", default="control_plane/telemetry.db", help="Caminho para o banco de dados SQLite")
    parser.add_argument("--port", type=int, default=9999, help="Porta UDP para o coletor escutar")
    parser.add_argument("--topo", help="Nome da topologia a ser carregada ao iniciar")
    args = parser.parse_args()

    # Desabilitar verbose logging no coletor para não poluir a CLI
    logging.getLogger("telemetry_collector").setLevel(logging.WARNING)

    cli = SDNCLI(db_path=args.db, udp_port=args.port, initial_topo=args.topo)
    
    try:
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\nEncerrando SDN CLI...")
        cli.db.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
