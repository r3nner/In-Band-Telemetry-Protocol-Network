# Projeto de Telemetria In-Band e Descoberta Dinâmica (Digital Twin)

Este projeto implementa um ecossistema **Software-Defined Networking (SDN)** utilizando **P4/BMv2** e **Mininet**. Ele suporta telemetria ativa in-band (latência, throughput, atraso de transmissão, packet-pair para capacidade) e um mecanismo inovador de **Descoberta Dinâmica de Topologia** para a geração de um **Gêmeo Digital (Digital Twin)** da rede em tempo real.

O grande diferencial deste projeto é a sua **Arquitetura Modular (Piggybacking)**. O seu sistema de telemetria atua como um "Observador Ativo", injetando suas regras de forma totalmente isolada em redes comerciais já em funcionamento, sem precisar alterar a inteligência de roteamento da infraestrutura.

Toda a lógica de descoberta de rotas e mitigação de loops é feita diretamente no **Plano de Dados (Data Plane)** pelo hardware/simulador P4, sem depender de pacotes de controle constantes sendo enviados à CPU.

## Visão Geral do Software

O repositório é rigorosamente separado em duas partes para provar a tese de modularidade:

1. **`network_simulation/` (Simulação da Infraestrutura Base):**
   Representa a rede do cliente/provedor. Os scripts Bash desta pasta (ex: `program_complex.sh`) apenas ligam as máquinas, atribuem um Datapath ID de fábrica para os switches e instalam rotas IP (IPv4) tradicionais. A rede não sabe nada sobre telemetria.

2. **`telemetry_system/` (Seu Software de Telemetria):**
   Contém a inteligência do TCC em Python. O seu software varre a rede ativa, instala regras de Multicast "por cima" das configurações existentes (`deploy_telemetry.py`), ejeta Sondas de Descoberta e extrai as métricas de latência e topologia do hardware BMv2 usando a API Thrift (`sdn_controller.py`).

---

## Arquitetura de Descoberta Dinâmica (O Gêmeo Digital)

O mecanismo de descoberta de topologia funciona através de um processo chamado **Stateful BFS Flooding** (Inundação em Largura com Guarda de Estado), operando puramente no Data Plane:

1. **Injeção da Sonda:** O controlador forja um único pacote (Sonda de Descoberta) com `EtherType 0x8899` e injeta em um switch raiz.
2. **Flooding (Inundação):** Quando o Switch P4 recebe a sonda, ele insere o seu próprio ID no pacote e clona/replica (Multicast) esse pacote para todas as suas outras portas ativas.
3. **Aprendizado Bidirecional:** Quando o Switch vizinho recebe a sonda, ele lê o ID do switch remetente no pacote e salva no seu `neighbor_id_reg` (Registrador de Vizinhos) no exato índice da porta em que o pacote entrou.
4. **Quebra de Loop (Stateful):** Redes complexas (em malha/mesh) com flooding podem gerar tempestades infinitas de pacotes (Broadcast Storms). Para resolver isso, o Switch P4 verifica no seu registrador se ele **já conhecia** o remetente daquela sonda. Se sim, ele destrói (Drop) a sonda imediatamente. Isso permite que a sonda faça exatamente 1 "ping-pong" para que ambos os lados do cabo aprendam quem é o vizinho, mapeando loops com segurança.
5. **Geração do Gêmeo Digital:** Após a poeira baixar, o Controlador SDN faz um Crawling acessando as portas de gerência. Ele varre as tabelas de vizinhos de forma recursiva e compila todos os links descobertos em um arquivo CSV (`network_state.csv`), representando o estado exato da rede naquele instante.

---

## Passo a Passo: Rodando a Rede Complexa (5 Switches)

Para validar a arquitetura modular e a resiliência contra Loops de roteamento, siga o passo a passo utilizando a topologia Complexa em Malha (*Mesh Topology*).

### 1. Levantar a Infraestrutura Base (Engenheiro de Redes)
Abra um terminal dentro do Docker (Terminal 1) e inicie a simulação física do Mininet:
```bash
sudo python3 topologies/complex_topo.py --json build/main.json
```
*(A topologia subirá com 5 switches e múltiplos loops entre eles, aguarde a mensagem `Complex Topology started`)*

Em outro terminal no Docker (Terminal 2), instale as rotas IPv4 e os IDs de hardware:
```bash
bash network_simulation/program_complex.sh
```
> **Nota:** A rede agora é capaz de rotear pings convencionais, mas é cega para telemetria.

### 2. Implantar a Telemetria (Seu Software)
Ainda no Terminal 2, ative o modo "Observador" do seu software. Ele injetará os grupos de espelhamento dinamicamente com base nas portas ativas detectadas:
```bash
python3 telemetry_system/deploy_telemetry.py
```
*(Saída esperada: "Telemetry Multicast successfully deployed to 5 switches".)*

### 3. Disparar a Sonda de Descoberta (Terminal 1)
No prompt do Mininet (`mininet>`), peça para o Host 1 soltar a Sonda de Inundação na rede:
```bash
mininet> h1 python3 telemetry_system/send_discovery.py --iface h1-eth0
```
> O Data Plane P4 fará toda a mitigação dos Loops da topologia complexa nos bastidores em microssegundos.

### 4. Extrair o Gêmeo Digital (Terminal 2)
Faça o seu controlador coletar a visão completa do hardware e montar o CSV:
```bash
python3 telemetry_system/sdn_controller.py
```

**Resultado Esperado:**
O controlador mapeará todo o labirinto de switches perfeitamente!
```text
[INFO] Starting Topology Discovery & Digital Twin Export...
[INFO] Connecting to Switch 1 (Thrift: 9090)
  -> Found Link: S1 (Port 2) ---> S2
  -> Found Link: S1 (Port 3) ---> S3
[INFO] Connecting to Switch 2 (Thrift: 9091)
  -> Found Link: S2 (Port 1) ---> S1
  -> Found Link: S2 (Port 2) ---> S4
...
[OK] Digital Twin exported to network_state.csv
```

### 5. Gerar Tráfego Real para Métricas (Opcional)
Como o Gêmeo Digital reflete o estado exato da memória (SRAM) do switch no instante em que foi executado, caso não haja fluxo na rede, métricas como `Throughput_bps` estarão zeradas. Para gerar uma carga real e embasar o throughput, utilize o `iperf` embutido no Mininet (no Terminal 1):
```bash
mininet> iperf h1 h2
```
Imediatamente após a conclusão do teste, repita o Passo 4 (`sdn_controller.py`). O novo CSV gerado mostrará a coluna `Throughput_bps` com altos valores para os switches da rota percorrida.

### 6. Visualizar o CSV Gerado
O arquivo `network_state.csv` é salvo dentro do contêiner Docker. Para sincronizá-lo com a sua máquina local (host) ou apenas visualizar o conteúdo, você pode usar os comandos abaixo em um terminal do seu Windows/Linux (fora do Mininet):

```bash
# Para visualizar o CSV diretamente no terminal:
docker exec p4-mininet cat /workspace/network_state.csv

# Para copiar o CSV para a sua máquina (na pasta atual):
docker cp p4-mininet:/workspace/network_state.csv ./
```

---

## Demais Métricas

As métricas tradicionais (Latência, Vazão e Atraso) permanecem 100% suportadas e isoladas no módulo de telemetria.
```bash
python3 telemetry_system/read_latency.py --thrift-port 9090 --indices 2
python3 telemetry_system/read_throughput.py --thrift-port 9090 --indices 2
```
