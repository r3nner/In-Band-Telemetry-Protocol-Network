# Telemetria de Latência

Laboratório P4/BMv2/Mininet para telemetria ativa in-band de latência.

Este projeto estima a latência por enlace clonando pacotes IPv4 selecionados em sondas de telemetria, refletindo-os no switch vizinho e armazenando valores derivados de ida-e-volta em registradores do plano de dados.

Também há um caminho de throughput baseado em leitura periódica de contadores no control plane, além de um helper para executar iperf dentro da topologia Mininet.

## Como funciona

1. O switch de origem clona pacotes IPv4 selecionados e emite sondas de telemetria.
2. O switch vizinho reflete as sondas e adiciona o tempo de processamento local.
3. O switch de origem calcula a estimativa unidirecional:

$$
latency = (t_{receive} - t_{send} - t_{proc}) / 2
$$

4. A latência é escrita em `latency_reg[index]` e espelhada como um relatório para manter ambos os pares sincronizados.

## Estrutura do repositório

- `p4/main.p4`: plano de dados P4_16 v1model.
- `scripts/setup_ubuntu.sh`: bootstrap completo para Ubuntu (PI, BMv2, p4c, Mininet, dependências Python).
- `scripts/health_check.sh`: verifica a toolchain, compilação, imports Python e faz um teste rápido do Mininet.
- `scripts/build_p4.sh`: compila `p4/main.p4` em `build/main.json`.
- `topologies/p4_mininet.py`: classes de integração BMv2 + Mininet.
- `topologies/linear_topo.py`: topologia linear `h1-s1-s2-h2`.
- `topologies/triangle_topo.py`: topologia triangular com dois caminhos de saída em S1.
- `control_plane/program_linear.sh`: programa roteamento linear + espelhamento.
- `control_plane/program_triangle.sh`: programa roteamento triangular + espelhamento.
- `control_plane/read_latency.py`: consulta registradores de latência via thrift.
- `control_plane/read_throughput.py`: consulta contadores de throughput via thrift e calcula bps a partir do delta de bytes.
- `control_plane/run_throughput_test.py`: executa uma demonstração completa de throughput com iperf.
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

2. Validar o ambiente:

```bash
chmod +x scripts/health_check.sh scripts/build_p4.sh
./scripts/health_check.sh
```

3. Compilar P4:

```bash
./scripts/build_p4.sh
```

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
sudo python3 control_plane/run_throughput_test.py --topology linear --json build/main.json
```

O helper sobe o iperf em `h2`, executa o cliente em `h1` e acompanha `throughput_reg` durante o tráfego.

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
sudo python3 control_plane/run_throughput_test.py --topology triangle --json build/main.json
```

O helper programa os switches, inicia o tráfego e lê os contadores de throughput por índice em paralelo.

## Configuração

- `PROBE_INTERVAL_US`: intervalo de emissão das sondas em microssegundos.
- `PROBE_INTERVAL_US=0`: emite sonda a cada pacote elegível.
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
