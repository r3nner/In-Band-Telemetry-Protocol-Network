#!/usr/bin/env python3
"""
Interface de Linha de Comando (CLI) para o Ecossistema SDN.
Integra banco de dados, descoberta de topologia e coleta de telemetria UDP.

Todas as configurações são centralizadas em config.json via SDNConfig.
"""

import argparse
import cmd
import json
import logging
import shlex
import sys
import threading

from config import SDNConfig
from database import TelemetryDB
from topology_discovery import TopologyDiscovery
import telemetry_collector

class SDNCLI(cmd.Cmd):
    intro = "Bem-vindo ao Ecossistema SDN. Digite 'help' ou '?' para listar os comandos.\n"
    prompt = "sdn> "

    def __init__(self, cfg: SDNConfig):
        super().__init__()
        self.cfg = cfg

        # Inicialização do banco e discovery
        self.db = TelemetryDB(cfg.db_path)
        self.discovery = TopologyDiscovery(self.db, cfg)

        # Define topologia ativa
        self.active_topology = None

        # Injeção da instância do banco no coletor
        telemetry_collector.db_instance = self.db

        # Se o config tem uma topologia salva, carregá-la automaticamente
        if cfg.topology_name:
            self.do_topology("load {}".format(cfg.topology_name))

        # Iniciar thread do coletor UDP
        self.collector_thread = threading.Thread(
            target=telemetry_collector.run_collector,
            kwargs={'port': cfg.udp_port},
            daemon=True
        )
        self.collector_thread.start()
        print("[INFO] Coletor UDP rodando em background na porta {}".format(cfg.udp_port))

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
                        print(" [{}] {} (Criada: {}, Atualizada: {})".format(marca, name, c_at, u_at))

            elif subcmd == "load":
                if len(args) < 2:
                    print("Erro: nome da topologia não fornecido. Uso: topology load <name>")
                    return
                name = args[1]
                self.discovery.load_or_create(name)
                self.active_topology = name
                # Persistir no config para restaurar na próxima sessão
                self.cfg.topology_name = name
                # Atualizar a variável do coletor para associar os relatórios recebidos a esta topologia
                telemetry_collector.topology_name = name
                print("Topologia ativa definida para: '{}'".format(name))

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
                    print("Topologia '{}' não encontrada.".format(name))
                    return

                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(topo_dict, f, indent=2, ensure_ascii=False)
                print("Topologia '{}' exportada em JSON bruto para {}".format(name, filepath))

            elif subcmd == "export-gml":
                if len(args) < 3:
                    print("Erro: argumentos insuficientes. Uso: topology export-gml <name> <file>")
                    return
                name, filepath = args[1], args[2]
                try:
                    self.discovery.export_gml(name, filepath)
                    print("Topologia '{}' exportada em GML para {}".format(name, filepath))
                except ValueError as e:
                    print("Erro: {}".format(e))

            elif subcmd == "infer":
                if not self.active_topology:
                    print("Nenhuma topologia ativa. Use 'topology load <name>'.")
                    return
                count = self.discovery.infer_links(self.active_topology)
                print("{} links unidirecionais inferidos e salvos na topologia '{}'.".format(count, self.active_topology))

            else:
                print("Subcomando desconhecido: {}".format(subcmd))

        except Exception as e:
            print("Erro ao executar 'topology {}': {}".format(subcmd, e))

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
                    print("Erro: switch_id {} não encontrado.".format(switch_id))
                    return

                cmd_str = "table_add probe_profile enable_probe {} => {} {} {}".format(
                    egress_port, reg_index, remote_index, clone_session)
                process = subprocess.Popen(["simple_switch_CLI", "--thrift-port", str(thrift_port)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(input=cmd_str + "\n")
                if process.returncode != 0:
                    print("Erro CLI: {}".format(stderr))
                else:
                    import re
                    match = re.search(r'Entry has been added with handle (\d+)', stdout)
                    handle = match.group(1) if match else "?"
                    print("Métrica ativada no switch {}. Handle da entrada: {}".format(switch_id, handle))

            elif subcmd == "disable":
                if len(args) < 3:
                    print("Uso: metric disable <switch_id> <entry_handle>")
                    return
                switch_id = int(args[1])
                handle = int(args[2])

                thrift_port = get_thrift_port(switch_id)
                if thrift_port is None:
                    print("Erro: switch_id {} não encontrado.".format(switch_id))
                    return

                cmd_str = "table_delete probe_profile {}".format(handle)
                process = subprocess.Popen(["simple_switch_CLI", "--thrift-port", str(thrift_port)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(input=cmd_str + "\n")
                if process.returncode != 0:
                    print("Erro CLI: {}".format(stderr))
                else:
                    print("Métrica desativada no switch {} (Handle {}).".format(switch_id, handle))

            elif subcmd == "list":
                if len(args) < 2:
                    print("Uso: metric list <switch_id>")
                    return
                switch_id = int(args[1])
                thrift_port = get_thrift_port(switch_id)
                if thrift_port is None:
                    print("Erro: switch_id {} não encontrado.".format(switch_id))
                    return

                cmd_str = "table_dump probe_profile"
                process = subprocess.Popen(["simple_switch_CLI", "--thrift-port", str(thrift_port)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(input=cmd_str + "\n")
                if process.returncode != 0:
                    print("Erro CLI: {}".format(stderr))
                else:
                    print("--- Configuração de Sondas (Switch {}) ---".format(switch_id))
                    for line in stdout.splitlines():
                        if "enable_probe" in line or "no_probe" in line:
                            print(line)

            else:
                print("Subcomando desconhecido: {}".format(subcmd))

        except ValueError:
            print("Erro: IDs, portas e handles devem ser números inteiros.")
        except Exception as e:
            print("Erro ao executar 'metric {}': {}".format(subcmd, e))

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
                    print("Snapshot #{} criado: {} nós, {} enlaces.".format(snap_id, nodes_count, edges_count))

                    import os
                    snap_dir = self.cfg.snapshot_dir
                    os.makedirs(snap_dir, exist_ok=True)
                    filepath = os.path.join(snap_dir, "snapshot_{}.json".format(snap_id))
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(snap_dict, f, indent=2, ensure_ascii=False)
                    print("Cópia automática salva em: {}".format(filepath))
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
                        print(" [ID: {}] Topo: {} | Nós: {} | Enlaces: {} | Criado em: {}".format(
                            snap_id, topo_name, nodes, edges, created_at))

            elif subcmd == "show":
                if len(args) < 2:
                    print("Uso: snapshot show <id>")
                    return
                snap_id = int(args[1])
                snap_dict = self.db.get_snapshot_by_id(snap_id)
                if not snap_dict:
                    print("Snapshot com ID {} não encontrado.".format(snap_id))
                    return

                print("=== Snapshot #{} ===".format(snap_id))
                nodes = snap_dict.get("nodes", [])
                edges = snap_dict.get("edges", [])
                print("Nós ({}):".format(len(nodes)))
                for n in nodes:
                    tipo = n.get("type", "?")
                    lbl = n.get("label", str(n.get("id")))
                    th = " thrift={}".format(n.get('thrift_port')) if n.get('thrift_port') else ""
                    ip = " ip={}".format(n.get('ip')) if n.get('ip') else ""
                    print("  [{}] {}{}{}".format(tipo, lbl, th, ip))
                print("\nEnlaces ({}):".format(len(edges)))
                for e in edges:
                    src = e.get("source")
                    src_p = e.get("source_port", "?")
                    tgt = e.get("target")
                    tgt_p = e.get("target_port", "?")
                    lat = e.get("telemetry", {}).get("latency_us")
                    th = e.get("telemetry", {}).get("throughput_bps")
                    lat_str = "{:.2f}ms".format(lat/1000.0) if lat else "?ms"
                    th_str = "{:.1f}Mbps".format(th/1000000.0) if th else "?Mbps"
                    print("  {}:{} -> {}:{}  lat: {}  th: {}".format(src, src_p, tgt, tgt_p, lat_str, th_str))

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

                print("=== Diff: Snapshot #{} -> Snapshot #{} ===".format(id_a, id_b))
                edges_a = {(e.get("source"), e.get("source_port")): e for e in snap_a.get("edges", [])}
                edges_b = {(e.get("source"), e.get("source_port")): e for e in snap_b.get("edges", [])}

                for k in set(edges_a.keys()).union(edges_b.keys()):
                    ea = edges_a.get(k)
                    eb = edges_b.get(k)
                    if ea and not eb:
                        print("[-] Enlace removido: {}:{} -> {}:{}".format(
                            k[0], k[1], ea.get('target'), ea.get('target_port')))
                    elif eb and not ea:
                        print("[+] Enlace adicionado: {}:{} -> {}:{}".format(
                            k[0], k[1], eb.get('target'), eb.get('target_port')))
                    else:
                        l_a = ea.get("telemetry", {}).get("latency_us")
                        l_b = eb.get("telemetry", {}).get("latency_us")
                        if l_a is not None and l_b is not None and l_a != l_b:
                            pct = ((l_b - l_a) / l_a) * 100 if l_a else 0
                            print("[~] {}:{} -> {}:{} latência: {:.2f}ms -> {:.2f}ms ({:+.1f}%)".format(
                                k[0], k[1], ea.get('target'), ea.get('target_port'),
                                l_a/1000.0, l_b/1000.0, pct))

            elif subcmd == "export":
                if len(args) < 3:
                    print("Erro: argumentos insuficientes. Uso: snapshot export <id> <file>")
                    return
                snap_id = int(args[1])
                filepath = args[2]
                snap_dict = self.db.get_snapshot_by_id(snap_id)
                if not snap_dict:
                    print("Snapshot com ID {} não encontrado.".format(snap_id))
                    return
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(snap_dict, f, indent=2, ensure_ascii=False)
                print("Snapshot {} exportado em JSON para {}".format(snap_id, filepath))

            else:
                print("Subcomando desconhecido: {}".format(subcmd))

        except ValueError:
            print("Erro: IDs devem ser números inteiros.")
        except Exception as e:
            print("Erro ao executar 'snapshot {}': {}".format(subcmd, e))

    def do_config(self, arg):
        """
        Gerencia a configuração centralizada. Subcomandos:
          config show                  — exibe todos os parâmetros
          config set <chave> <valor>   — altera um parâmetro em memória
          config save                  — persiste as alterações no config.json
          config reset                 — restaura todos os valores padrão
        """
        args = shlex.split(arg)
        if not args:
            print("Uso: config <show|set|save|reset> [argumentos]")
            return

        subcmd = args[0]

        try:
            if subcmd == "show":
                print(self.cfg.show())

            elif subcmd == "set":
                if len(args) < 3:
                    print("Uso: config set <chave> <valor>")
                    print("Chaves disponíveis: {}".format(", ".join(sorted(self.cfg.keys))))
                    return
                chave = args[1]
                # Junta o restante como valor (caso tenha espaços no caminho)
                valor = " ".join(args[2:])
                # Trata "None" / "null" como None
                if valor.lower() in ("none", "null"):
                    valor = None
                self.cfg.set(chave, valor)
                print("Parâmetro '{}' alterado para: {}".format(chave, valor))
                print("Use 'config save' para persistir a alteração.")

            elif subcmd == "save":
                self.cfg.save()
                print("Configuração salva em: {}".format(self.cfg.config_path))

            elif subcmd == "reset":
                self.cfg.reset()
                print("Configuração restaurada para os valores padrão e salva.")

            else:
                print("Subcomando desconhecido: {}".format(subcmd))

        except KeyError as e:
            print("Erro: {}".format(e))
        except Exception as e:
            print("Erro ao executar 'config {}': {}".format(subcmd, e))

    def do_exit(self, arg):
        """Encerra a CLI e o banco de dados."""
        if self.cfg.is_dirty:
            print("Há alterações de configuração não salvas.")
            resp = input("Deseja salvar? (s)im / (n)ão / (r)esetar: ").strip().lower()
            if resp in ("s", "sim", "y", "yes"):
                self.cfg.save()
                print("Configuração salva.")
            elif resp in ("r", "resetar", "reset"):
                self.cfg.reset()
                print("Configuração resetada para os padrões.")
            else:
                print("Alterações descartadas.")
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
            print("Erro: switch_id {} não encontrado na topologia ativa.".format(switch_id))
            return

        us_val = ms_val * 1000
        cmd_str = "register_write probe_interval_reg {} {}".format(port_id, us_val)
        print("Executando no switch {} (thrift {}): {}".format(switch_id, thrift_port, cmd_str))

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
                print("Erro ao executar CLI do Thrift: {}".format(stderr))
            else:
                print("Frequência atualizada com sucesso.")
        except Exception as e:
            print("Erro de subprocesso: {}".format(e))

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
            print("Erro: switch_id {} não encontrado na topologia ativa.".format(switch_id))
            return

        cmd_str = "register_read probe_interval_reg {}".format(port_id)

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
                print("Erro ao executar CLI do Thrift: {}".format(stderr))
            else:
                match = re.search(r'=\s*(\d+)', stdout)
                if match:
                    us_val = int(match.group(1))
                    ms_val = us_val / 1000.0
                    print("Switch {}, Porta {}: Intervalo = {} ms ({} µs)".format(
                        switch_id, port_id, ms_val, us_val))
                else:
                    print("Não foi possível extrair a resposta do Thrift: {}".format(stdout))
        except Exception as e:
            print("Erro de subprocesso: {}".format(e))



def main():
    parser = argparse.ArgumentParser(description="CLI do Ecossistema SDN")
    parser.add_argument("--config", default="control_plane/config.json",
                        help="Caminho para o arquivo de configuração (padrão: control_plane/config.json)")
    # Overrides individuais (prioridade sobre config.json)
    parser.add_argument("--db", default=None, help="Override: caminho do banco SQLite")
    parser.add_argument("--port", type=int, default=None, help="Override: porta UDP do coletor")
    parser.add_argument("--topo", default=None, help="Override: topologia a carregar ao iniciar")
    args = parser.parse_args()

    # Carrega a configuração centralizada
    cfg = SDNConfig(args.config)

    # Aplica overrides da linha de comando (se fornecidos)
    if args.db is not None:
        cfg.set("db_path", args.db)
    if args.port is not None:
        cfg.set("udp_port", args.port)
    if args.topo is not None:
        cfg.set("topology_name", args.topo)

    # Desabilitar verbose logging no coletor para não poluir a CLI
    logging.getLogger("telemetry_collector").setLevel(
        getattr(logging, cfg.log_level, logging.WARNING)
    )

    cli = SDNCLI(cfg=cfg)

    try:
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\nEncerrando SDN CLI...")
        if cfg.is_dirty:
            resp = input("Salvar configurações? (s/n): ").strip().lower()
            if resp in ("s", "sim", "y", "yes"):
                cfg.save()
                print("Configuração salva.")
        cli.db.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
