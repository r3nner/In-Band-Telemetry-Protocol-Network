# Telemetria In-Band — Ecossistema SDN

Laboratório P4/BMv2/Mininet para telemetria ativa in-band de latência, throughput, atraso de transmissão e capacidade do enlace (packet-pair), sem a necessidade de banco de dados ou CLI central.

## Arquitetura Simplificada

1. O switch P4 intercepta quadros ou clona sondas para calcular a telemetria em Data Plane.
2. Os resultados (tempos, bytes, comprimentos) são armazenados em `registers` nativos do P4 (SRAM).
3. Scripts Python independentes consultam esses `registers` via Thrift (API padrão do BMv2) de forma desacoplada, calculam a métrica e a exibem na tela.

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
│   ├── program_linear.sh              # Programa switches (topologia linear)
│   ├── program_triangle.sh            # Programa switches (topologia triangular)
│   ├── program_packet_pair.sh         # Programa sondas de packet-pair
│   ├── read_latency.py                # Leitura de registrador de latência
│   ├── read_throughput.py             # Leitura de contador de vazão
│   ├── read_transmission_delay.py     # Estimativa baseada no tamanho do pacote
│   ├── read_link_capacity.py          # Leitura de registrador de dispersão (delta_t)
│   ├── run_throughput_test.py         # Automação de vazão via iperf
│   ├── send_probes.py                 # Scapy para forjar sonda no packet-pair
│   └── test_link_capacity.py          # Automação do packet-pair
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



## Executar o Ecossistema Completo

Você precisa de **2 terminais** abertos no container simultaneamente.

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
bash ./control_plane/program_linear.sh
```

### Terminal 2 — Ler as Métricas

Com o tráfego rodando, use um terminal separado para invocar os leitores Python via protocolo Thrift:

```bash
# Ler Latência
python3 control_plane/read_latency.py --thrift-port 9090 --indices 2

# Ler Vazão (rodará indefinidamente atualizando por segundo)
python3 control_plane/read_throughput.py --thrift-port 9090 --indices 2

# Ler Atraso de Transmissão (assumindo link configurado com 10 Mbps)
python3 control_plane/read_transmission_delay.py --thrift-port 9090 --indices 2 --link-bw-mbps 10
```

---

## Executar: Topologia Triangular

Mesma lógica, mas com 3 switches:

```bash
# Terminal 1
sudo python3 topologies/triangle_topo.py --json build/main.json

# Terminal 2
bash ./control_plane/program_triangle.sh

# Terminal 2 (Leitura)
python3 control_plane/read_latency.py --thrift-port 9090 --indices 2,3

# Terminal 1 (Mininet)
mininet> h1 ping -c 5 10.0.20.2   # Rota via S2
mininet> h1 ping -c 5 10.0.30.2   # Rota direta via S3
```



## Visualizando as Métricas (Passo a Passo)

Abaixo explicamos como testar cada um dos 4 parâmetros de rede suportados por esta arquitetura, detalhando o comando a ser executado e a mecânica por trás da medição.

### 1. Latência (Latency)
**Como funciona:** 
O Switch de origem clona pacotes de dados e cria uma sonda (Probe) de telemetria inserindo seu timestamp de envio ($t_{send}$). O Switch destino (refletor) recebe a sonda, marca o tempo de processamento gasto internamente ($t_{proc}$) e a devolve. A origem recebe de volta, pega seu tempo atual ($t_{recv}$) e calcula a ida e volta exata via hardware: `(t_recv - t_send - t_proc) / 2`.
O resultado é gravado no registrador do Switch e enviado para o Control Plane.

**Passo a passo:**
1. Inicie a topologia e programe o switch:
   ```bash
   sudo python3 topologies/linear_topo.py --json build/main.json
   bash ./control_plane/program_linear.sh
   ```
2. Gere o tráfego (no terminal do Mininet):
   ```bash
   mininet> h1 ping -c 5 10.0.0.2
   ```
3. Leia o registrador de latência diretamente do P4:
   ```bash
   python3 control_plane/read_latency.py --thrift-port 9090 --indices 2
   ```

### 2. Vazão (Throughput)
**Como funciona:**
O Switch P4 possui contadores em hardware que somam o tamanho de cada pacote que sai por uma porta. Os scripts de control plane podem consultar esse contador (`throughput_reg`) via Thrift e subtrair o valor anterior para obter bytes/segundo.

**Passo a passo:**
1. Execute o teste automatizado (que usa `iperf` por baixo dos panos para gerar tráfego TCP na topologia):
   ```bash
   sudo python3 control_plane/run_throughput_test.py --topology linear --json build/main.json --link-bw-mbps 10
   ```
*Nota: Este comando levanta a topologia, inicia o iperf entre H1 e H2 e interroga os registradores `throughput_reg` para calcular e exibir a banda (bps) em tempo real.*

### 3. Atraso de Transmissão (Transmission Delay)
**Como funciona:**
É uma métrica analítico-híbrida. O hardware P4 armazena em um registrador o tamanho ($L$) do último pacote encaminhado. O plano de controle (script Python) faz a leitura deste registrador e o divide pela configuração de velocidade física do enlace ($R$, ex: 10 Mbps) que o Mininet configurou, resultando na fórmula: $d_{trans} = L / R$.

**Passo a passo:**
1. Execute a topologia definindo a banda física dos links (ex: 10 Mbps):
   ```bash
   sudo python3 topologies/linear_topo.py --json build/main.json --link-bw-mbps 10
   bash ./control_plane/program_linear.sh
   ```
2. Gere um ping: `mininet> h1 ping -c 1 10.0.0.2`
3. Leia o atraso de transmissão (passando a mesma banda configurada para o cálculo matemático no script):
   ```bash
   python3 control_plane/read_transmission_delay.py --thrift-port 9090 --indices 2 --link-bw-mbps 10
   ```

### 4. Capacidade do Link (In-Band Packet-Pair)
**Como funciona:**
A capacidade física real do link é descoberta utilizando dois pacotes em rajada. 
O script gera *apenas 1 pacote* de sonda e envia ao **Switch Injetor**. O P4 deste switch usa o motor de hardware para clonar o pacote e jogar os dois na mesma fila de saída com prioridade máxima (Packet-Pair Back-to-Back). 
Ao cruzar o gargalo da rede, eles se distanciam (dispersão). O **Switch Receptor** anota a hora que o Pacote 1 chegou ($t_1$). Quando o Pacote 2 chega, ele faz $\Delta T = t_2 - t_1$ usando as ALUs do P4, gravando o resultado de $\Delta T$ num registrador. O plano de controle simplesmente lê o $\Delta T$ via Thrift e finaliza o cálculo: $C = L_{bits} / \Delta T$.

**Passo a passo:**
Com a topologia (linear ou triangular) rodando e configurada em um terminal, simplesmente execute o teste de capacidade em outro:
```bash
python3 control_plane/test_link_capacity.py --host h1 --thrift-port 9091 --frame-size 1500
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
