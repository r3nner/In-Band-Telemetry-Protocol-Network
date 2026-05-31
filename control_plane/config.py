#!/usr/bin/env python3
"""
Módulo de configuração centralizada do Ecossistema SDN.

Gerencia todos os parâmetros configuráveis em um único arquivo JSON
(config.json), permitindo leitura, alteração, persistência e reset
para os valores padrão.

Compatível com Python 3.8+.
"""

import json
import os
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Valores padrão — usados na primeira execução ou após um reset
# ---------------------------------------------------------------------------
DEFAULTS: Dict[str, Any] = {
    # Banco de dados SQLite
    "db_path": "control_plane/telemetry.db",

    # Coletor de telemetria (UDP)
    "udp_port": 9999,

    # Topologia ativa (persistida entre sessões da CLI)
    "topology_name": None,

    # Controlador
    "controller_ip": "10.0.0.254",
    "controller_udp_port": 9999,

    # Logging
    "log_level": "INFO",

    # Intervalos do Data Plane (microssegundos)
    "probe_interval_us": 1000000,
    "report_interval_us": 1000000,

    # Heurística de inferência de topologia
    "infer_threshold_us": 1000,
    "default_bandwidth_mbps": 10.0,

    # Portas Thrift dos switches
    "s1_thrift_port": 9090,
    "s2_thrift_port": 9091,
    "s3_thrift_port": 9092,

    # Diretório de snapshots
    "snapshot_dir": "control_plane/snapshots",
}

# Descrições legíveis para exibição no comando 'config show'
DESCRIPTIONS: Dict[str, str] = {
    "db_path":               "Caminho do banco SQLite",
    "udp_port":              "Porta UDP do coletor de telemetria",
    "topology_name":         "Nome da topologia ativa",
    "controller_ip":         "IP do controlador SDN",
    "controller_udp_port":   "Porta UDP do controlador",
    "log_level":             "Nível de log (DEBUG/INFO/WARNING/ERROR)",
    "probe_interval_us":     "Intervalo de sonda (µs)",
    "report_interval_us":    "Intervalo de report de throughput (µs)",
    "infer_threshold_us":    "Limiar de latência p/ inferência (µs)",
    "default_bandwidth_mbps": "Largura de banda padrão dos enlaces (Mbps)",
    "s1_thrift_port":        "Porta Thrift do switch S1",
    "s2_thrift_port":        "Porta Thrift do switch S2",
    "s3_thrift_port":        "Porta Thrift do switch S3",
    "snapshot_dir":          "Diretório para snapshots JSON",
}


class SDNConfig:
    """Gerencia a configuração centralizada do ecossistema SDN."""

    def __init__(self, config_path: str = "control_plane/config.json"):
        """
        Carrega a configuração do disco ou cria com valores padrão.

        Parâmetros:
            config_path – caminho do arquivo JSON de configuração
        """
        self._config_path = config_path
        self._dirty = False  # indica se houve alteração não salva
        self._data: Dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Leitura e escrita
    # ------------------------------------------------------------------
    def get(self, key: str) -> Any:
        """
        Retorna o valor de um parâmetro.

        Levanta KeyError se a chave não existir.
        """
        if key not in self._data:
            raise KeyError(f"Parâmetro desconhecido: '{key}'")
        return self._data[key]

    def set(self, key: str, value: Any) -> None:
        """
        Altera o valor de um parâmetro em memória.

        A alteração só é persistida no disco quando save() for chamado.
        Levanta KeyError se a chave não existir nos defaults.
        """
        if key not in DEFAULTS:
            raise KeyError(
                f"Parâmetro desconhecido: '{key}'. "
                f"Chaves válidas: {', '.join(sorted(DEFAULTS.keys()))}"
            )
        # Converte o tipo para o mesmo tipo do default (quando possível)
        valor_default = DEFAULTS[key]
        if valor_default is not None and value is not None:
            try:
                tipo = type(valor_default)
                value = tipo(value)
            except (ValueError, TypeError):
                pass
        self._data[key] = value
        self._dirty = True

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------
    def save(self) -> None:
        """Salva a configuração atual no arquivo JSON."""
        diretorio = os.path.dirname(self._config_path)
        if diretorio:
            os.makedirs(diretorio, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        self._dirty = False

    def reset(self) -> None:
        """Restaura todos os parâmetros para os valores padrão e salva."""
        self._data = dict(DEFAULTS)
        self._dirty = False
        self.save()

    # ------------------------------------------------------------------
    # Exibição
    # ------------------------------------------------------------------
    def show(self) -> str:
        """Retorna uma string formatada com todos os parâmetros."""
        linhas = ["=== Configuração do Ecossistema SDN ===", ""]
        # Calcula alinhamento
        max_key = max(len(k) for k in self._data)
        for key in sorted(self._data.keys()):
            valor = self._data[key]
            desc = DESCRIPTIONS.get(key, "")
            valor_str = str(valor) if valor is not None else "(não definido)"
            linhas.append(f"  {key:<{max_key}}  =  {valor_str:<20}  # {desc}")
        if self._dirty:
            linhas.append("")
            linhas.append("  (*) Há alterações não salvas. Use 'config save' para persistir.")
        return "\n".join(linhas)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    @property
    def is_dirty(self) -> bool:
        """Indica se há alterações em memória que não foram salvas."""
        return self._dirty

    @property
    def config_path(self) -> str:
        """Retorna o caminho do arquivo de configuração."""
        return self._config_path

    @property
    def keys(self):
        """Retorna as chaves de configuração disponíveis."""
        return list(self._data.keys())

    # ------------------------------------------------------------------
    # Propriedades de conveniência para acesso rápido
    # ------------------------------------------------------------------
    @property
    def db_path(self) -> str:
        return self._data["db_path"]

    @property
    def udp_port(self) -> int:
        return self._data["udp_port"]

    @property
    def topology_name(self):
        return self._data["topology_name"]

    @topology_name.setter
    def topology_name(self, value):
        self._data["topology_name"] = value
        self._dirty = True

    @property
    def controller_ip(self) -> str:
        return self._data["controller_ip"]

    @property
    def controller_udp_port(self) -> int:
        return self._data["controller_udp_port"]

    @property
    def log_level(self) -> str:
        return self._data["log_level"]

    @property
    def probe_interval_us(self) -> int:
        return self._data["probe_interval_us"]

    @property
    def report_interval_us(self) -> int:
        return self._data["report_interval_us"]

    @property
    def infer_threshold_us(self) -> int:
        return self._data["infer_threshold_us"]

    @property
    def default_bandwidth_mbps(self) -> float:
        return self._data["default_bandwidth_mbps"]

    @property
    def s1_thrift_port(self) -> int:
        return self._data["s1_thrift_port"]

    @property
    def s2_thrift_port(self) -> int:
        return self._data["s2_thrift_port"]

    @property
    def s3_thrift_port(self) -> int:
        return self._data["s3_thrift_port"]

    @property
    def snapshot_dir(self) -> str:
        return self._data["snapshot_dir"]

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Carrega do disco ou inicializa com defaults."""
        if os.path.exists(self._config_path):
            with open(self._config_path, "r", encoding="utf-8") as f:
                dados_disco = json.load(f)
            # Garante que todas as chaves existam (migrando novos parâmetros)
            self._data = dict(DEFAULTS)
            self._data.update(dados_disco)
        else:
            self._data = dict(DEFAULTS)
            self.save()
