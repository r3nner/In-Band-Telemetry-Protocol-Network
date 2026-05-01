# Telemetria In-Band com Sonda Ativa e Truncamento (P4/BMv2/Mininet)

Este repositório implementa um laboratório ponta a ponta para estimar latência de enlace com sonda in-band refletida:

- o S1 clona pacotes IPv4 selecionados, remove o IPv4 do clone, injeta `telemetry_t` e envia a sonda.
- o switch vizinho reflete a sonda e adiciona o tempo de processamento local em `t_proc`.
- o switch de origem calcula `(t_receive - t_send - t_proc) / 2`, grava o resultado em `latency_reg[index]` e envia um relatório para o vizinho.
- o switch vizinho recebe o relatório e grava a mesma latência no seu próprio `latency_reg[index]`.

## Função De Cada Arquivo

- `README.md`: documentação principal do projeto e guia de execução.
- `p4/main.p4`: data plane P4 (v1model) com parser, ingress, egress, checksum e deparser.
- `scripts/setup_ubuntu.sh`: provisiona ambiente Ubuntu com dependências e build de PI/BMv2/p4c.
- `scripts/health_check.sh`: valida comandos, compilação P4, import Python e teste básico de Mininet.
- `scripts/build_p4.sh`: compila `p4/main.p4` e gera `build/main.json`.
- `control_plane/program_linear.sh`: programa rotas e sessão de clone da topologia linear via `simple_switch_CLI`.
- `control_plane/program_triangle.sh`: programa rotas e sessões de clone da topologia em triângulo via `simple_switch_CLI`.
- `control_plane/read_latency.py`: lê periodicamente `latency_reg` no BMv2 e imprime valores em milissegundos.
- `topologies/p4_mininet.py`: define as classes `P4Host` e `P4Switch` para execução de BMv2 no Mininet.
- `topologies/linear_topo.py`: sobe topologia linear (H1-S1-S2-H2).
- `topologies/triangle_topo.py`: sobe topologia com múltiplos caminhos (H1-S1-S2-S3-H2 e S1-S3).
- `build/main.json`: artefato gerado pelo compilador P4 para ser carregado no `simple_switch`.

## Fluxo Rápido

1. instalar dependências no Ubuntu:

```bash
chmod +x scripts/setup_ubuntu.sh
./scripts/setup_ubuntu.sh
```

1. validar ambiente:

```bash
chmod +x scripts/health_check.sh scripts/build_p4.sh
./scripts/health_check.sh
```

1. compilar o P4:

```bash
./scripts/build_p4.sh
```

## Teste 1: Topologia Linear

1. iniciar topologia:

```bash
sudo python3 topologies/linear_topo.py --json build/main.json
```

1. no CLI do Mininet, programar os switches e gerar tráfego:

```bash
PROBE_INTERVAL_US=200000 sh ./control_plane/program_linear.sh
h1 ping -c 5 10.0.0.2
```

1. em outro terminal, ler latência:

```bash
python3 control_plane/read_latency.py --thrift-port 9090 --indices 2
```

## Teste 2: Topologia Triângulo

1. iniciar topologia:

```bash
sudo python3 topologies/triangle_topo.py --json build/main.json
```

1. no CLI do Mininet, programar os switches e testar os dois destinos:

```bash
PROBE_INTERVAL_US=200000 sh ./control_plane/program_triangle.sh
h1 ping -c 5 10.0.20.2
h1 ping -c 5 10.0.30.2
```

1. em outro terminal, ler latências por índice:

```bash
python3 control_plane/read_latency.py --thrift-port 9090 --indices 2,3
```

## Intervalo De Telemetria

O intervalo entre sondas e configurado por registrador no data plane e pode ser ajustado sem recompilar o P4.

- variavel de ambiente: `PROBE_INTERVAL_US`
- unidade: microssegundos
- valor `0`: envia sonda em todo pacote elegivel

Exemplo:

```bash
PROBE_INTERVAL_US=500000 sh ./control_plane/program_triangle.sh
```

No exemplo acima, cada indice monitorado envia no maximo uma sonda a cada 500 ms.

## Observações Sobre Sessões De Clone

A primitiva `clone_preserving_field_list` depende de configuração explícita de mirror session no BMv2:

- topologia linear: sessão `250` mapeada para a porta S1->S2.
- topologia triângulo: sessão `250` para S1->S2 e sessão `251` para S1->S3.

Se a sessão de clone não estiver configurada, o encaminhamento IPv4 pode funcionar normalmente, mas as sondas de telemetria não serão emitidas.
