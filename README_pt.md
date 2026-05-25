# Telemetria de Latência

Laboratório P4/BMv2/Mininet para telemetria ativa in-band de latência.

Este projeto estima a latência por enlace clonando pacotes IPv4 selecionados em sondas de telemetria, refletindo-os no switch vizinho e armazenando valores derivados de ida-e-volta em registradores do plano de dados.

Também estima o atraso de transmissão como uma métrica derivada no control plane usando o comprimento de pacote informado pelo BMv2 e a largura de banda do enlace configurada no Mininet.

Inclui um caminho de throughput baseado em leitura periódica de contadores de bytes no control plane, além de um helper para executar iperf dentro da topologia Mininet.

Agora também inclui um experimento separado de dispersão de packet-pair usando sondas Scapy fora de banda e um caminho de encaminhamento L2 dedicado para telemetria `msg_type=2`.

## Como funciona

1. O switch de origem clona pacotes IPv4 selecionados e emite sondas de telemetria.
2. O switch vizinho reflete as sondas e adiciona o tempo de processamento local.
3. O switch de origem calcula a estimativa unidirecional:

$$
latency = (t_{receive} - t_{send} - t_{proc}) / 2
$$

4. A latência é escrita em `latency_reg[index]` e espelhada como um relatório para manter ambos os pares sincronizados.

5. O atraso de transmissão é calculado no control plane a partir de:

$$
d_{trans} = \frac{L}{R}
$$

onde `L` vem de `packet_length_reg[index]` e `R` vem da largura de banda do `TCLink` configurada para o caminho.

## Estrutura do repositório

- `p4/main.p4`: plano de dados P4_16 v1model.
- `scripts/setup_ubuntu.sh`: bootstrap completo para Ubuntu (PI, BMv2, p4c, Mininet, dependências Python).
- `scripts/health_check.sh`: verifica a toolchain, compilação, imports Python e faz um teste rápido do Mininet.
- `scripts/build_p4.sh`: compila `p4/main.p4` em `build/main.json`.
- `topologies/p4_mininet.py`: classes de integração BMv2 + Mininet.
- `topologies/linear_topo.py`: topologia linear `h1-s1-s2-h2`.
- `topologies/triangle_topo.py`: topologia triangular com dois caminhos de saída em S1.
- `topologies/packet_pair_topo.py`: topologia linear de packet-pair com `probe_s1` e `probe_s2`.
- `control_plane/program_linear.sh`: programa roteamento linear + espelhamento.
- `control_plane/program_triangle.sh`: programa roteamento triangular + espelhamento.
- `control_plane/program_packet_pair.sh`: programa o caminho de sonda de packet-pair.
- `control_plane/read_latency.py`: consulta registradores de latência via thrift.
- `control_plane/read_throughput.py`: consulta contadores de throughput via thrift e calcula bps a partir do delta de bytes.
- `control_plane/read_transmission_delay.py`: consulta registradores de comprimento de pacote via thrift e deriva o atraso de transmissão a partir da largura de banda do enlace.
- `control_plane/run_throughput_test.py`: executa uma demonstração completa de throughput com iperf.
- `control_plane/test_link_capacity.py`: teste automatizado de capacidade de packet-pair (um comando).
- `control_plane/send_probes.py`: transmissor Scapy para sondas de packet-pair back-to-back.
- `control_plane/sniff_probes.py`: receptor Scapy que marca o tempo de chegada de duas sondas e estima a capacidade.
- `build/main.json`: artefato JSON gerado para BMv2.

## Pré-requisitos

- Ubuntu Linux.
- Acesso `sudo`.
- Acesso à internet para clonar/compilar dependências.

## Início rápido

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

## Atraso de Transmissão

Os enlaces do Mininet já utilizam `TCLink`. Para tornar o atraso de transmissão reproduzível, os scripts de topologia agora aceitam `--link-bw-mbps` e aplicam esse valor para todos os enlaces.

Exemplo para a topologia linear:

```bash
sudo python3 topologies/linear_topo.py --json build/main.json --link-bw-mbps 10
```

Após programar o switch, leia a estimativa de atraso de transmissão com:

```bash
python3 control_plane/read_transmission_delay.py --thrift-port 9090 --indices 2 --link-bw-mbps 10
```

O control plane lê `packet_length_reg`, converte bytes para bits e calcula `L/R` em software. O valor é uma estimativa analítica, não uma medição com timestamp do BMv2.

## Executar: Topologia Linear

1. Iniciar a topologia no Mininet:

```bash
sudo python3 topologies/linear_topo.py --json build/main.json
```

2. No CLI do Mininet, programar switches e enviar tráfego:

```bash
PROBE_INTERVAL_US=200000 sh ./control_plane/program_linear.sh
h1 ping -c 5 10.0.0.2
```

3. Em outro terminal, ler o registrador de latência:

```bash
python3 control_plane/read_latency.py --thrift-port 9090 --indices 2
```

### Teste de throughput

Execute a demonstração automatizada de throughput no host:

```bash
sudo python3 control_plane/run_throughput_test.py --topology linear --json build/main.json --link-bw-mbps 10
```

O helper sobe o iperf em `h2`, executa o cliente em `h1` e acompanha `throughput_reg` durante o tráfego.
Também deriva o atraso de transmissão a partir da largura de banda configurada e do último comprimento de pacote visto por cada índice monitorado.

## Executar: Topologia Triangular

1. Iniciar a topologia no Mininet:

```bash
sudo python3 topologies/triangle_topo.py --json build/main.json
```

2. No CLI do Mininet, programar switches e testar ambas as classes de rota:

```bash
PROBE_INTERVAL_US=200000 sh ./control_plane/program_triangle.sh
h1 ping -c 5 10.0.20.2
h1 ping -c 5 10.0.30.2
```

3. Em outro terminal, ler ambos os índices monitorados:

```bash
python3 control_plane/read_latency.py --thrift-port 9090 --indices 2,3
```

### Teste de throughput

Execute a demonstração automatizada de throughput no host:

```bash
sudo python3 control_plane/run_throughput_test.py --topology triangle --json build/main.json --link-bw-mbps 10
```

O helper programa os switches, inicia o tráfego e lê os contadores de throughput por índice em paralelo.
Também deriva o atraso de transmissão a partir da largura de banda configurada e do último comprimento de pacote visto por cada índice monitorado.

## Executar: Teste de Capacidade de Packet-Pair

### Teste Rápido (Automatizado)

Execute um teste de capacidade completo em um único comando:

```bash
sudo python3 control_plane/test_link_capacity.py \
  --json build/main.json \
  --bottleneck-bw-mbps 10 \
  --frame-size 1500
```

Este script:
1. Inicia a topologia de packet-pair
2. Programa os switches
3. Inicia o sniffer em `probe_s2-eth0`
4. Envia sondas back-to-back de `probe_s1-eth0`
5. Relata a capacidade estimada do enlace em bps

### Teste Manual (Passo-a-passo)

1. Iniciar a topologia dedicada:

```bash
sudo python3 topologies/packet_pair_topo.py --json build/main.json --probe-bw-mbps 1000 --bottleneck-bw-mbps 10
```

2. No CLI do Mininet, carregar as regras de encaminhamento de sonda:

```bash
sh ./control_plane/program_packet_pair.sh
```

3. Iniciar o receptor primeiro no host de sonda anexado a S2:

```bash
sudo python3 control_plane/sniff_probes.py --iface probe_s2-eth0
```

4. Enviar as sondas back-to-back do host anexado a S1:

```bash
sudo python3 control_plane/send_probes.py --iface probe_s1-eth0
```

O receptor registra a chegada do pacote 1 e pacote 2, calcula `delta_t` e imprime a capacidade estimada em bps usando `bits / delta_t`.

## Configuração

- `PROBE_INTERVAL_US`: intervalo de emissão das sondas em microssegundos.
- `PROBE_INTERVAL_US=0`: emite sonda a cada pacote elegível.
- `--link-bw-mbps`: largura de banda Mininet usada para modelar atraso de transmissão.
- `--probe-bw-mbps`: largura de banda dos enlaces de sonda de packet-pair.
- `--bottleneck-bw-mbps`: largura de banda do gargalo inter-switch de packet-pair.
- Portas thrift padrão:
  - `s1=9090`
  - `s2=9091`
  - `s3=9092`

Exemplo:

```bash
PROBE_INTERVAL_US=500000 sh ./control_plane/program_triangle.sh
```

## Solução de problemas

- Nenhum valor de telemetria mudando:
  - Verifique se o script de control-plane finalizou sem erros no CLI.
  - Confirme se sessões de espelhamento estão configuradas (`mirroring_add`) em cada switch.
  - Verifique se o tráfego está realmente atravessando as portas de saída monitoradas.

- `simple_switch_CLI` falha logo após a inicialização da topologia:
  - Tente novamente após um pequeno atraso; os scripts já incluem verificações de disponibilidade do thrift.

- Saída de registrador permanece zero:
  - Garanta que os pings sejam direcionados aos endereços programados nas tabelas de rota.
  - Reduza o `PROBE_INTERVAL_US` para aumentar a frequência de sondas.

## Observações

`build/main.json` é gerado. Recompile após alterar `p4/main.p4`:

```bash
./scripts/build_p4.sh
```
