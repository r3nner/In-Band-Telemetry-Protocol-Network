#include <core.p4>
#include <v1model.p4>

// tipos base usados nos cabeçalhos e nos cálculos de tempo
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;
typedef bit<48> timestamp_t;

// constantes de etherType e metadados de clone para o protocolo
const bit<16> ETHERTYPE_IPV4 = 16w0x0800;
const bit<16> ETHERTYPE_TELEMETRY = 16w0x88B5;
const bit<32> CLONE_SESSION_DEFAULT = 32w250;
const bit<32> INSTANCE_TYPE_INGRESS_CLONE = 32w1;
const bit<8> TELEMETRY_MSG_PROBE = 8w0;
const bit<8> TELEMETRY_MSG_REPORT = 8w1;
const bit<8> TELEMETRY_MSG_PAIR = 8w2;

// sessão de clone dedicada à exportação de relatórios UDP para o controlador
const bit<32> CLONE_SESSION_REPORT = 32w252;

// cabeçalho ethernet padrão de camada 2
header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16> etherType;
}

// cabeçalho ipv4 mínimo necessário para encaminhamento l3
header ipv4_t {
    bit<4> version;
    bit<4> ihl;
    bit<8> diffserv;
    bit<16> totalLen;
    bit<16> identification;
    bit<3> flags;
    bit<13> fragOffset;
    bit<8> ttl;
    bit<8> protocol;
    bit<16> hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

// cabeçalho UDP para encapsular relatórios de telemetria
header udp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<16> length;
    bit<16> checksum;
}

// cabeçalho de relatório de telemetria exportado via UDP ao controlador
// tamanho total: 8 + 16 + 8 + 48 + 48 = 128 bits = 16 bytes
header telemetry_report_t {
    bit<8>  switch_id;      // identificador do switch que gerou o report
    bit<16> port_id;        // porta do enlace medido (9 bits usados, padded a 16)
    bit<8>  metric_type;    // tipo de métrica: 0=latência, 1=throughput, 2=dispersão
    bit<48> metric_value;   // valor calculado da métrica
    bit<48> timestamp;      // instante da medição
}

// cabeçalho customizado de telemetria ativa
 
header telemetry_t {
    bit<8> msg_type; // 0=probe, 1=report
    bit<8> probe_index; // índice local para o emissor monitorar a latência daquele enlace
    bit<8> report_index; // índice remoto para o vizinho monitorar a latência recebida da origem
    bit<8> is_returning; // 0 indica ida para o vizinho, 1 indica retorno para origem
    timestamp_t t_send; // tempo de envio da sonda no emissor
    timestamp_t t_proc; // tempo de processamento da sonda no refletor
    timestamp_t latency_value; // latência calculada
}

// metadados internos usados para controlar clone e medir processamento
struct metadata {
    // preserva a sessão de clone entre ingress e egress do pacote clonado
    @field_list(1)
    bit<32> clone_session_id;

    // preserva o índice do registrador para gravação da latência
    @field_list(1)
    bit<8> probe_index;

    // preserva o índice remoto para sincronizar a latência no vizinho
    @field_list(1)
    bit<8> report_index;

    // habilita ou desabilita geração de sonda por pacote
    bit<1> clone_enable;

    // guarda o tempo de entrada da sonda no switch refletor
    timestamp_t s2_ingress_time;

    // snapshot de tempo para decidir se a sonda pode ser emitida no intervalo configurado
    timestamp_t now_ts;

    // último instante em que uma sonda foi emitida para o índice monitorado
    timestamp_t last_probe_ts;

    // intervalo mínimo entre sondas para o índice monitorado
    timestamp_t probe_interval;

    // --- campos para preservar dados no clone de report UDP ---
    // valor da métrica a ser exportada (latência, throughput ou dispersão)
    @field_list(2)
    bit<48> report_metric_value;

    // tipo da métrica: 0=latência, 1=throughput, 2=dispersão
    @field_list(2)
    bit<8> report_metric_type;

    // porta/índice do enlace medido
    @field_list(2)
    bit<16> report_port_id;

    // sessão de clone usada para diferenciar report de sonda
    @field_list(2)
    bit<32> report_clone_session;
}

// agrupa todos os cabeçalhos manipulados no pipeline
struct headers {
    ethernet_t ethernet;
    ipv4_t ipv4;
    udp_t udp;
    telemetry_report_t telemetry_report;
    telemetry_t telemetry;
}

// parser principal: identifica o tipo do quadro e extrai ipv4, udp, report ou telemetria
parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {
    state start {
        // inicia pela extração do cabeçalho ethernet
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);
        // seleciona o próximo estado com base no etherType
        transition select(hdr.ethernet.etherType) {
            ETHERTYPE_IPV4: parse_ipv4;
            ETHERTYPE_TELEMETRY: parse_telemetry;
            default: accept;
        }
    }

    state parse_ipv4 {
        // extrai o cabeçalho ipv4 para fluxo de dados normal
        packet.extract(hdr.ipv4);
        // verifica se o protocolo é UDP para extrair cabeçalhos adicionais
        transition select(hdr.ipv4.protocol) {
            17: parse_udp;
            default: accept;
        }
    }

    // estado para extrair o cabeçalho UDP
    state parse_udp {
        packet.extract(hdr.udp);
        // tenta extrair o cabeçalho de relatório de telemetria após o UDP
        transition parse_telemetry_report;
    }

    // estado para extrair o cabeçalho de relatório de telemetria encapsulado em UDP
    state parse_telemetry_report {
        packet.extract(hdr.telemetry_report);
        transition accept;
    }

    state parse_telemetry {
        // extrai o cabeçalho de telemetria para fluxo de sonda
        packet.extract(hdr.telemetry);
        transition accept;
    }
}

// bloco de verificação de checksum: mantido vazio pois o foco é telemetria
control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

// registrador stateful que armazena latência por índice de vizinho
register<bit<48>>(1024) latency_reg;

// intervalo mínimo entre sondas por índice (em ticks do timestamp global)
register<bit<48>>(1024) probe_interval_reg;

// último timestamp de envio de sonda por índice
register<bit<48>>(1024) last_probe_ts_reg;

// registrador stateful que acumula bytes encaminhados por índice (throughput)
register<bit<64>>(1024) throughput_reg;

// registrador stateful que guarda o tamanho do último pacote observado por índice
register<bit<32>>(1024) packet_length_reg;

// --- novos registradores para exportação de relatórios UDP ---

// identificador único do switch, configurável via Thrift no control plane
register<bit<8>>(1) switch_id_reg;

// endereço IP de destino do controlador, configurável via Thrift
register<bit<32>>(1) controller_ip_reg;

// endereço IP de origem do switch (srcAddr do IPv4 do report), configurável via Thrift
register<bit<32>>(1) switch_ip_reg;

// intervalo mínimo entre reports de throughput por porta (em microssegundos)
register<bit<48>>(1024) report_interval_reg;

// último timestamp de envio de report de throughput por porta
register<bit<48>>(1024) last_report_ts_reg;

// ingress: encaminha ipv4, cria sondas por clone, reflete telemetria e calcula latência final
control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    // descarta pacote no pipeline
    action drop() {
        mark_to_drop(standard_metadata);
    }

    // encaminha ipv4 com reescrita de mac e decremento de ttl
    action ipv4_forward(macAddr_t dst_mac, macAddr_t src_mac, bit<9> port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.dstAddr = dst_mac;
        hdr.ethernet.srcAddr = src_mac;

        // evita underflow do ttl em pacotes já expirados
        if (hdr.ipv4.ttl > 0) {
            hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        }
    }

    // encaminha quadros de telemetria de packet-pair em camada 2 pura
    action pair_forward(macAddr_t dst_mac, macAddr_t src_mac, bit<9> port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.dstAddr = dst_mac;
        hdr.ethernet.srcAddr = src_mac;
    }

    // habilita a geração de sonda e define sessão/índices preservados no clone
    action enable_probe(bit<8> register_index, bit<8> remote_index, bit<32> clone_session_id) {
        meta.clone_enable = 1;
        meta.probe_index = register_index;
        meta.report_index = remote_index;
        meta.clone_session_id = clone_session_id;
    }

    // desabilita geração de sonda quando o perfil não exigir medição
    action no_probe() {
        meta.clone_enable = 0;
        meta.probe_index = 0;
        meta.report_index = 0;
        meta.clone_session_id = 0;
    }

    // tabela de encaminhamento ipv4 por prefixo
    table ipv4_lpm {
        key = {
            hdr.ipv4.dstAddr: lpm;
        }
        actions = {
            ipv4_forward;
            drop;
        }
        size = 1024;
        default_action = drop();
    }

    // tabela que escolhe se o tráfego daquela porta deve gerar sonda
    table probe_profile {
        key = {
            standard_metadata.egress_spec: exact;
        }
        actions = {
            enable_probe;
            no_probe;
        }
        size = 32;
        default_action = no_probe();
    }

    // encaminhamento dedicado para as sondas de packet-pair fora de banda
    table pair_l2_forward {
        key = {
            hdr.ethernet.dstAddr: exact;
        }
        actions = {
            pair_forward;
            drop;
        }
        size = 32;
        default_action = drop();
    }

    apply {
        // inicializa metadados para um estado previsível a cada pacote
        meta.clone_enable = 0;
        meta.probe_index = 0;
        meta.report_index = 0;
        meta.clone_session_id = CLONE_SESSION_DEFAULT;
        meta.now_ts = 0;
        meta.last_probe_ts = 0;
        meta.probe_interval = 0;

        // inicializa metadados de report UDP
        meta.report_metric_value = 0;
        meta.report_metric_type = 0;
        meta.report_port_id = 0;
        meta.report_clone_session = 0;

        // fluxo de dados: pacote ipv4 normal sem cabeçalho de telemetria
        if (hdr.ipv4.isValid() && !hdr.telemetry.isValid()) {
            ipv4_lpm.apply();

            // aplica o perfil para decidir se deve clonar este pacote
            probe_profile.apply();

            // contabilização de throughput por porta/índice de egress
            // usa o egress_spec como índice simples por porta/rota
            bit<32> th_idx = (bit<32>)standard_metadata.egress_spec;
            bit<64> prev_bytes = 0;
            // lê, incrementa pelo tamanho total do pacote e grava de volta
            throughput_reg.read(prev_bytes, th_idx);
            prev_bytes = prev_bytes + (bit<64>)standard_metadata.packet_length;
            throughput_reg.write(th_idx, prev_bytes);

            // preserva o tamanho do pacote para cálculo de atraso de transmissão
            packet_length_reg.write(th_idx, standard_metadata.packet_length);

            // --- exportação periódica de throughput via report UDP ---
            {
                bit<48> rpt_interval = 0;
                bit<48> rpt_last_ts = 0;
                bit<48> rpt_now = standard_metadata.ingress_global_timestamp;
                report_interval_reg.read(rpt_interval, th_idx);
                last_report_ts_reg.read(rpt_last_ts, th_idx);

                // envia report de throughput quando o intervalo configurado expirar
                if ((rpt_interval != 0) &&
                    (rpt_now >= (rpt_last_ts + rpt_interval))) {
                    last_report_ts_reg.write(th_idx, rpt_now);

                    // preenche metadados de report para o clone
                    meta.report_metric_type = 1;    // 1 = throughput
                    meta.report_metric_value = (bit<48>)prev_bytes;
                    meta.report_port_id = (bit<16>)th_idx;
                    meta.report_clone_session = CLONE_SESSION_REPORT;

                    // cria clone ingress->egress preservando campos marcados com field_list 2
                    clone_preserving_field_list(CloneType.I2E,
                                                CLONE_SESSION_REPORT,
                                                2);
                }
            }

            if (meta.clone_enable == 1) {
                bit<32> interval_idx = (bit<32>)meta.probe_index;
                meta.now_ts = standard_metadata.ingress_global_timestamp;
                probe_interval_reg.read(meta.probe_interval, interval_idx);
                last_probe_ts_reg.read(meta.last_probe_ts, interval_idx);

                // emite sonda apenas quando o intervalo configurado expira
                if ((meta.probe_interval == 0) ||
                    (meta.now_ts >= (meta.last_probe_ts + meta.probe_interval))) {
                    last_probe_ts_reg.write(interval_idx, meta.now_ts);

                    // cria clone ingress->egress preservando campos marcados com field_list 1
                    clone_preserving_field_list(CloneType.I2E,
                                                meta.clone_session_id,
                                                1);
                }
            }
        } else if (hdr.telemetry.isValid()) {
            if (hdr.telemetry.msg_type == TELEMETRY_MSG_PAIR) {
                pair_l2_forward.apply();
            } else if (hdr.telemetry.msg_type == TELEMETRY_MSG_PROBE) {
                // fluxo de telemetria de ida no switch refless
                if (hdr.telemetry.is_returning == 0) {
                    // registra tempo de entrada para cálculo de processamento no egress
                    meta.s2_ingress_time = standard_metadata.ingress_global_timestamp;

                    // inverte a direção e retorna pela mesma porta de entrada
                    hdr.telemetry.is_returning = 1;
                    standard_metadata.egress_spec = standard_metadata.ingress_port;
                } else if (hdr.telemetry.is_returning == 1) {
                    // fluxo de telemetria de volta na origem para cálculo final
                    bit<48> t_recv = standard_metadata.ingress_global_timestamp;
                    bit<48> t_send = hdr.telemetry.t_send;
                    bit<48> t_proc = hdr.telemetry.t_proc;

                    // calcula rtt total e remove custo interno de processamento do refletor
                    bit<48> total_rtt = t_recv - t_send;
                    bit<48> prop_rtt = 0;
                    if (total_rtt > t_proc) {
                        prop_rtt = total_rtt - t_proc;
                    }

                    // divide por 2 via shift para obter latência unidirecional estimada
                    bit<48> final_latency = prop_rtt >> 1;

                    // grava localmente a latência do vizinho monitorado no índice configurado 
                    bit<32> reg_index = (bit<32>)hdr.telemetry.probe_index;
                    latency_reg.write(reg_index, final_latency);

                    // --- exportação de latência via report UDP ---
                    // preenche metadados de report antes do clone
                    meta.report_metric_value = final_latency;
                    meta.report_port_id = (bit<16>)hdr.telemetry.probe_index;
                    meta.report_metric_type = 0;    // 0 = latência
                    meta.report_clone_session = CLONE_SESSION_REPORT;

                    // cria clone ingress->egress para montar pacote report UDP
                    clone_preserving_field_list(CloneType.I2E,
                                                CLONE_SESSION_REPORT,
                                                2);

                    // converte a sonda em relatório para sincronizar a latência no vizinho
                    hdr.telemetry.msg_type = TELEMETRY_MSG_REPORT;
                    hdr.telemetry.is_returning = 0;
                    hdr.telemetry.latency_value = final_latency;
                    standard_metadata.egress_spec = standard_metadata.ingress_port;
                }
            } else if (hdr.telemetry.msg_type == TELEMETRY_MSG_REPORT) {
                // no vizinho, persiste o valor recebido no índice remoto pré-configurado
                bit<32> remote_reg_index = (bit<32>)hdr.telemetry.report_index;
                latency_reg.write(remote_reg_index, hdr.telemetry.latency_value);
                drop();
            } else {
                drop();
            }
        }
    }
}

// egress: monta a sonda clonada no emissor e registra t_proc no refletor
control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {
        // identifica pacote clonado no egress para conversão em sonda enxuta
        if (standard_metadata.instance_type == INSTANCE_TYPE_INGRESS_CLONE) {

            // verifica se é clone de report UDP ou clone de sonda
            if (meta.report_clone_session == CLONE_SESSION_REPORT) {
                // --- montagem do pacote de report UDP para o controlador ---

                // lê configurações do switch a partir dos registradores
                bit<8> sw_id = 0;
                bit<32> ctrl_ip = 0;
                bit<32> sw_ip = 0;
                switch_id_reg.read(sw_id, 0);
                controller_ip_reg.read(ctrl_ip, 0);
                switch_ip_reg.read(sw_ip, 0);

                // invalida cabeçalhos originais que não fazem parte do report
                if (hdr.telemetry.isValid()) {
                    hdr.telemetry.setInvalid();
                }
                if (hdr.ipv4.isValid()) {
                    hdr.ipv4.setInvalid();
                }
                if (hdr.udp.isValid()) {
                    hdr.udp.setInvalid();
                }
                if (hdr.telemetry_report.isValid()) {
                    hdr.telemetry_report.setInvalid();
                }

                // monta o cabeçalho Ethernet do report
                hdr.ethernet.etherType = ETHERTYPE_IPV4;

                // monta o cabeçalho IPv4 do report
                // totalLen = 20 (ipv4) + 8 (udp) + 16 (telemetry_report_t) = 44
                hdr.ipv4.setValid();
                hdr.ipv4.version = 4;
                hdr.ipv4.ihl = 5;
                hdr.ipv4.diffserv = 0;
                hdr.ipv4.totalLen = 44;
                hdr.ipv4.identification = 0;
                hdr.ipv4.flags = 0;
                hdr.ipv4.fragOffset = 0;
                hdr.ipv4.ttl = 64;
                hdr.ipv4.protocol = 17;  // UDP
                hdr.ipv4.hdrChecksum = 0;
                hdr.ipv4.srcAddr = sw_ip;
                hdr.ipv4.dstAddr = ctrl_ip;

                // monta o cabeçalho UDP do report
                // length = 8 (udp) + 16 (telemetry_report_t) = 24
                hdr.udp.setValid();
                hdr.udp.srcPort = 9999;
                hdr.udp.dstPort = 9999;
                hdr.udp.length = 24;
                hdr.udp.checksum = 0;

                // monta o cabeçalho de relatório de telemetria
                hdr.telemetry_report.setValid();
                hdr.telemetry_report.switch_id = sw_id;
                hdr.telemetry_report.port_id = meta.report_port_id;
                hdr.telemetry_report.metric_type = meta.report_metric_type;
                hdr.telemetry_report.metric_value = meta.report_metric_value;
                hdr.telemetry_report.timestamp = standard_metadata.egress_global_timestamp;

            } else {
                // --- clone de sonda existente (fluxo original inalterado) ---
                // remove ipv4/payload do clone para reduzir overhead de banda
                hdr.ipv4.setInvalid();

                // preenche o cabeçalho de telemetria com dados de saída do emissor
                hdr.telemetry.setValid();
                hdr.telemetry.msg_type = TELEMETRY_MSG_PROBE;
                hdr.telemetry.probe_index = meta.probe_index;
                hdr.telemetry.report_index = meta.report_index;
                hdr.telemetry.is_returning = 0;
                hdr.telemetry.t_send = standard_metadata.egress_global_timestamp;
                hdr.telemetry.t_proc = 0;
                hdr.telemetry.latency_value = 0;
                hdr.ethernet.etherType = ETHERTYPE_TELEMETRY;
            }

        } else if (hdr.telemetry.isValid() &&
                   hdr.telemetry.msg_type == TELEMETRY_MSG_PROBE &&
                   hdr.telemetry.is_returning == 1) {
            // no refletor, calcula o tempo de processamento local da sonda.
            bit<48> t_egress = standard_metadata.egress_global_timestamp;
            hdr.telemetry.t_proc = t_egress - meta.s2_ingress_time;
        }
    }
}

// compute checksum: atualiza checksum ipv4 somente quando o cabeçalho estiver válido.
control MyComputeChecksum(inout headers hdr, inout metadata meta) {
    apply {
        update_checksum(
            hdr.ipv4.isValid(),
            {
                hdr.ipv4.version,
                hdr.ipv4.ihl,
                hdr.ipv4.diffserv,
                hdr.ipv4.totalLen,
                hdr.ipv4.identification,
                hdr.ipv4.flags,
                hdr.ipv4.fragOffset,
                hdr.ipv4.ttl,
                hdr.ipv4.protocol,
                hdr.ipv4.srcAddr,
                hdr.ipv4.dstAddr
            },
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16
        );
    }
}

// deparser: emite cabeçalhos válidos na ordem do wire format.
// ordem: ethernet → ipv4 → udp → telemetry_report → telemetry
control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.udp);
        packet.emit(hdr.telemetry_report);
        packet.emit(hdr.telemetry);
    }
}

// instancia o pipeline completo do v1model para o bm2.
V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
