# Telemetria In-Band — Ecossistema SDN

Laboratório P4/BMv2/Mininet para telemetria ativa in-band de latência, throughput e dispersão, com **Control Plane centralizado** baseado em CLI interativa e configuração persistente.

## Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│                    Data Plane (P4/BMv2)                  │
│  Sondas ──► Latência ──► Clone ──► UDP Report (porta 9999)│
└──────────────────────┬──────────────────────────────────┘
                       │ UDP
┌──────────────────────▼──────────────────────────────────┐
│                  Control Plane (Python)                   │
│  Coletor UDP ──► SQLite ──► Topology Discovery ──► CLI   │
│                                                          │
│  config.json ◄──► SDNConfig (configuração centralizada)  │
└──────────────────────────────────────────────────────────┘
```

1. O switch clona pacotes em sondas, calcula latência e exporta via UDP.
2. O Coletor recebe os reports binários (16 bytes) e persiste no SQLite.
3. A CLI interativa permite operar a rede: inferir topologia, tirar snapshots, alterar frequências.
4. Toda configuração fica centralizada em `config.json`.

## Estrutura do repositório

```
├── Dockerfile / docker-compose.yml    # Ambiente Docker pronto
├── p4/main.p4                         # Plano de dados P4_16 v1model
├── scripts/
│   ├── setup_ubuntu.sh                # Bootstrap (PI, BMv2, p4c, Mininet)
│   ├── health_check.sh                # Verificação da toolchain
│   └── build_p4.sh                    # Compila main.p4 → build/main.json
├── topologies/
│   ├── p4_mininet.py                  # Integração BMv2 + Mininet
│   ├── linear_topo.py                 # h1-s1-s2-h2
│   ├── triangle_topo.py               # h1-s1-s2-s3-h2 + s1-s3
│   └── packet_pair_topo.py            # Dispersão de packet-pair
├── control_plane/
│   ├── config.py                      # Classe SDNConfig (centraliza parâmetros)
│   ├── config.json                    # Gerado automaticamente na 1ª execução
│   ├── cli.py                         # CLI interativa (sdn>)
│   ├── database.py                    # Persistência SQLite
│   ├── telemetry_collector.py         # Coletor UDP (thread em background)
│   ├── topology_discovery.py          # Inferência de topologia
│   ├── program_linear.sh              # Programa switches (topologia linear)
│   ├── program_triangle.sh            # Programa switches (topologia triangular)
│   ├── program_packet_pair.sh         # Programa sondas de packet-pair
│   ├── test_integration.py            # Testes unitários (11 testes)
│   └── test_e2e.sh                    # Documentação do teste ponta-a-ponta
├── build/main.json                    # Artefato compilado para BMv2
```

## Pré-requisitos

- **Docker Desktop** (Windows/Mac) ou **Ubuntu Linux** com `sudo`.
- Acesso à internet (apenas no primeiro build).

---

## Início Rápido — Docker (Recomendado)

### Passo 1: Build e iniciar o container

```bash
docker compose up -d --build
```

> O primeiro build demora ~30-60 min (compila p4c, BMv2, PI do zero). Builds seguintes usam cache.

### Passo 2: Entrar no container

```bash
docker exec -it p4-mininet bash
```

A partir daqui, todos os comandos são executados **dentro do container**.

### Passo 3: Compilar o P4 (se necessário)

```bash
cd /workspace
./scripts/build_p4.sh
```

### Passo 4: Rodar os testes unitários

```bash
python3 control_plane/test_integration.py -v
```

Resultado esperado: `Ran 11 tests in 0.0Xs — OK`

---

## Executar o Ecossistema Completo

Você precisa de **3 terminais** abertos no container simultaneamente.

### Terminal 1 — Iniciar a Rede (Mininet)

```bash
docker exec -it p4-mininet bash
cd /workspace
sudo python3 topologies/linear_topo.py --json build/main.json
```

O prompt `mininet>` aparecerá. **Deixe este terminal aberto.**

### Terminal 2 — Programar os Switches

```bash
docker exec -it p4-mininet bash
cd /workspace
sh ./control_plane/program_linear.sh
```

> Os parâmetros são lidos automaticamente do `config.json`. Não é necessário passar variáveis de ambiente.

Saída esperada:
```
[INFO] Configuração carregada de: control_plane/config.json
[OK] s1 programmed
[OK] s2 programmed
Linear topology control plane loaded.
```

### Terminal 3 — Iniciar a CLI Interativa

```bash
docker exec -it p4-mininet bash
cd /workspace
python3 control_plane/cli.py
```

O prompt `sdn>` aparecerá. Agora você opera a rede.

### Terminal 1 — Gerar Tráfego

Volte ao Terminal 1 (Mininet) e gere tráfego:

```bash
mininet> h1 ping h2
```

### Terminal 3 — Operar a Rede

Volte ao Terminal 3 (CLI `sdn>`) e use os comandos:

```bash
sdn> topology load linear_2sw      # Carrega/cria a topologia
sdn> topology infer                 # Descobre enlaces via heurística
sdn> topology show                  # Exibe o mapa da rede com latências
sdn> snapshot create                # Tira foto do estado atual
sdn> snapshot list                  # Lista snapshots salvos
sdn> snapshot diff 1 2              # Compara dois snapshots
sdn> set frequency 1 2 200         # Altera intervalo de sonda (ms)
sdn> show frequency 1 2            # Mostra intervalo atual
sdn> config show                    # Exibe toda a configuração
sdn> config set probe_interval_us 500000  # Altera parâmetro
sdn> config save                    # Salva no disco
sdn> exit                           # Pergunta se quer salvar/resetar
```

---

## Executar: Topologia Triangular

Mesma lógica, mas com 3 switches:

```bash
# Terminal 1
sudo python3 topologies/triangle_topo.py --json build/main.json

# Terminal 2
sh ./control_plane/program_triangle.sh

# Terminal 3
python3 control_plane/cli.py

# Terminal 1 (Mininet)
mininet> h1 ping -c 5 10.0.20.2   # Rota via S2
mininet> h1 ping -c 5 10.0.30.2   # Rota direta via S3
```

---

## Configuração Centralizada (`config.json`)

Todos os parâmetros configuráveis do ecossistema ficam em `control_plane/config.json`, gerado automaticamente na primeira execução:

| Parâmetro | Default | Descrição |
|---|---|---|
| `db_path` | `control_plane/telemetry.db` | Caminho do banco SQLite |
| `udp_port` | `9999` | Porta UDP do coletor |
| `topology_name` | `null` | Topologia ativa (persistida entre sessões) |
| `controller_ip` | `10.0.0.254` | IP do controlador SDN |
| `controller_udp_port` | `9999` | Porta UDP do controlador |
| `log_level` | `INFO` | Nível de log |
| `probe_interval_us` | `1000000` | Intervalo de sonda (µs) |
| `report_interval_us` | `1000000` | Intervalo de report de throughput (µs) |
| `infer_threshold_us` | `1000` | Limiar de latência para inferência (µs) |
| `default_bandwidth_mbps` | `10.0` | Largura de banda padrão (Mbps) |
| `s1_thrift_port` | `9090` | Porta Thrift do S1 |
| `s2_thrift_port` | `9091` | Porta Thrift do S2 |
| `s3_thrift_port` | `9092` | Porta Thrift do S3 |
| `snapshot_dir` | `control_plane/snapshots` | Diretório de snapshots |

### Comandos de configuração na CLI

```bash
sdn> config show                           # Exibe todos os parâmetros
sdn> config set <chave> <valor>            # Altera em memória
sdn> config save                           # Persiste no config.json
sdn> config reset                          # Restaura valores padrão
```

Os shell scripts (`program_linear.sh`, `program_triangle.sh`) leem diretamente do `config.json`, sem necessidade de variáveis de ambiente.

---

## Executar: Teste de Capacidade de Packet-Pair

### Teste Rápido (Automatizado)

```bash
sudo python3 control_plane/test_link_capacity.py \
  --json build/main.json \
  --bottleneck-bw-mbps 10 \
  --frame-size 1500
```

### Teste Manual

```bash
# Terminal 1 — Topologia
sudo python3 topologies/packet_pair_topo.py --json build/main.json --probe-bw-mbps 1000 --bottleneck-bw-mbps 10

# Terminal 1 — Programar
sh ./control_plane/program_packet_pair.sh

# Terminal 2 — Receptor
sudo python3 control_plane/sniff_probes.py --iface probe_s2-eth0

# Terminal 3 — Emissor
sudo python3 control_plane/send_probes.py --iface probe_s1-eth0
```

---

## Início Rápido — Ubuntu Nativo (sem Docker)

1. Bootstrap do ambiente (somente na primeira vez):

```bash
chmod +x scripts/setup_ubuntu.sh
./scripts/setup_ubuntu.sh
```

2. Valide o ambiente:

```bash
chmod +x scripts/health_check.sh scripts/build_p4.sh
./scripts/health_check.sh
```

3. Compile P4:

```bash
./scripts/build_p4.sh
```

4. Siga os mesmos passos da seção "Executar o Ecossistema Completo" acima.

---

## Atraso de Transmissão

Os enlaces do Mininet utilizam `TCLink`. Para tornar o atraso de transmissão reproduzível, os scripts de topologia aceitam `--link-bw-mbps`:

```bash
sudo python3 topologies/linear_topo.py --json build/main.json --link-bw-mbps 10
```

Após programar o switch, leia a estimativa:

```bash
python3 control_plane/read_transmission_delay.py --thrift-port 9090 --indices 2 --link-bw-mbps 10
```

---

## Solução de problemas

- **Nenhum valor de telemetria mudando:**
  - Verifique se o script de control-plane finalizou sem erros.
  - Confirme se sessões de espelhamento estão configuradas (`mirroring_add`).
  - Verifique se o tráfego está atravessando as portas monitoradas.

- **`simple_switch_CLI` falha logo após a inicialização:**
  - Tente novamente após um pequeno atraso; os scripts incluem verificações automáticas.

- **Saída de registrador permanece zero:**
  - Garanta que os pings sejam direcionados aos endereços nas tabelas de rota.
  - Reduza o `probe_interval_us` via `config set` para aumentar a frequência.

- **Volume Docker vazio no Windows:**
  - O Docker Desktop pode falhar ao montar volumes de discos de rede (Google Drive, OneDrive). O `Dockerfile` já inclui `COPY . /workspace` como fallback.

## Observações

`build/main.json` é gerado. Recompile após alterar `p4/main.p4`:

```bash
./scripts/build_p4.sh
```
