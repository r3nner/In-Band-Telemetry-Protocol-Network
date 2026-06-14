# Projeto de Telemetria In-Band e Descoberta Dinâmica (Digital Twin)

Este projeto implementa um ecossistema **Software-Defined Networking (SDN)** utilizando **P4/BMv2** e **Mininet**. Ele suporta telemetria ativa in-band (latência, throughput, atraso de transmissão, packet-pair para capacidade) e um mecanismo inovador de **Descoberta Dinâmica de Topologia** para a geração de um **Gêmeo Digital (Digital Twin)** da rede em tempo real.

Toda a lógica de descoberta de rotas e mitigação de loops é feita diretamente no **Plano de Dados (Data Plane)** pelo hardware/simulador P4, sem depender de pacotes de controle constantes sendo enviados à CPU.

## Visão Geral do Software

O software é dividido em duas grandes camadas:
1. **Plano de Dados (P4):** Escrito em linguagem P4_16 (`main.p4`). É responsável por processar os pacotes linha por linha. Ele contém tabelas de roteamento, tabelas de controle multicast (para replicação de pacotes), e registradores (memória SRAM) que armazenam o estado da rede, como a **Tabela de Vizinhos** e contadores de tempo/bytes.
2. **Plano de Controle (Python/Thrift):** Conjunto de scripts Python (`control_plane/`) que interagem com os switches P4. Eles não processam pacotes, mas sim injetam regras nas tabelas, disparam pacotes forjados na rede (usando a biblioteca `Scapy`) e fazem a leitura assíncrona da memória SRAM (registradores) do switch através da API Thrift para extrair métricas e gerar o arquivo de estado da rede (CSV).

---

## Arquitetura de Descoberta Dinâmica (O Gêmeo Digital)

O mecanismo de descoberta de topologia funciona através de um processo chamado **Stateful BFS Flooding** (Inundação em Largura com Guarda de Estado), operando puramente no Data Plane:

1. **Injeção da Sonda:** O controlador forja um único pacote (Sonda de Descoberta) com `EtherType 0x8899` e injeta em um switch raiz.
2. **Flooding (Inundação):** Quando o Switch P4 recebe a sonda, ele insere o seu próprio ID no pacote e clona/replica (Multicast) esse pacote para todas as suas outras portas ativas.
3. **Aprendizado Bidirecional:** Quando o Switch vizinho recebe a sonda, ele lê o ID do switch remetente no pacote e salva no seu `neighbor_id_reg` (Registrador de Vizinhos) no exato índice da porta em que o pacote entrou.
4. **Quebra de Loop (Stateful):** Redes com flooding podem gerar tempestades infinitas de pacotes (Broadcast Storms). Para resolver isso, antes de propagar um pacote adiante, o Switch P4 verifica no seu registrador se ele **já conhecia** o remetente daquela sonda. Se já conhecia, ele destrói (Drop) a sonda imediatamente. Isso permite que a sonda faça exatamente 1 "ping-pong" para que ambos os lados do cabo aprendam quem é o vizinho, e a tempestade de pacotes cessa naturalmente e de forma extremamente rápida.
5. **Geração do Gêmeo Digital:** Após a poeira da inundação baixar, o Controlador SDN (script Python) faz uma varredura (Crawling) acessando o Thrift Port do primeiro switch. Ele lê a tabela de vizinhos, encontra quem está conectado, salta para os IPs de Thrift desses vizinhos descobertos, e repete o processo recursivamente. No fim, ele compila todos os links descobertos em um arquivo CSV (`network_state.csv`), representando o estado exato da rede naquele instante.

---

## Passo a Passo: Descobrindo a Topologia da Rede

Para gerar o Digital Twin da rede em um determinado instante, abra seu terminal (com o Docker rodando e os arquivos compilados) e siga os passos abaixo. São necessários dois terminais interativos dentro do container.

### 1. Iniciar a Rede (Terminal 1)
Levante a topologia linear com os switches virtuais BMv2.
```bash
sudo python3 topologies/linear_topo.py --json build/main.json
```
**O que acontece:** O script usa o Mininet para alocar espaços isolados de rede, criando hosts (`h1`, `h2`) e switches (`s1`, `s2`) e conectando-os fisicamente por portas virtuais. O arquivo `main.json` instrui o switch a rodar o nosso código P4. Deixe esse terminal aberto (você estará no CLI `mininet>`).

### 2. Inicializar as Regras SDN (Terminal 2)
Em outro terminal no mesmo container, execute:
```bash
bash ./control_plane/program_sdn.sh
```
**O que acontece:** Este script usa a ferramenta `simple_switch_CLI` para popular as tabelas P4 via Thrift. Ele atribui um ID único para cada Switch (ex: `s1` = ID 1) inserindo uma regra na tabela `node_info`. Também cria os grupos de Multicast no motor de replicação do BMv2, permitindo que a sonda de descoberta seja espelhada para todas as portas.

### 3. Disparar a Sonda de Descoberta (Terminal 1)
No prompt do Mininet (`mininet>`), injete o pacote de descoberta:
```bash
mininet> h1 python3 control_plane/send_discovery.py --iface h1-eth0
```
**O que acontece:** O host `h1` usa o pacote `Scapy` do Python para construir um quadro Ethernet cru com o tipo customizado `0x8899`. Como esse comando é rodado "dentro" do `h1`, o pacote entra fisicamente na porta do switch `s1`. O P4 intercepta, reconhece o tipo, e dá o gatilho na Arquitetura de Flooding (explicada na seção anterior). Em milissegundos, toda a rede descobre os seus vizinhos bidirecionalmente e os salva na SRAM.

### 4. Gerar o Digital Twin (Terminal 2)
Com a rede já autodescoberta na memória dos switches, rode o extrator:
```bash
python3 control_plane/sdn_controller.py
```
**O que acontece:** O Python conecta no `s1` (porta Thrift `9090`), pede para ler o array do `neighbor_id_reg`. Ele descobre que na porta 2 há um vizinho com ID 2 (`s2`). Ele anota a conexão, conecta no Thrift do `s2` (`9091`), faz a mesma leitura e cruza os dados. Ao finalizar a recursão, ele cospe o arquivo `network_state.csv` detalhando cada link e porta bidirecional da sua rede.

---

## Demais Métricas

As outras métricas de telemetria também continuam disponíveis na camada de plano de controle. Use os scripts na pasta `control_plane/` (como `read_latency.py`, `read_throughput.py`, `read_link_capacity.py`, etc) passando o `thrift-port` para ler os dados de hardware instantaneamente.
