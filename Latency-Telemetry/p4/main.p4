#include <core.p4>
#include <v1model.p4>

// define tipos base usados nos cabeçalhos e nos cálculos de tempo.
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;
typedef bit<48> timestamp_t;

// define constantes de etherType e metadados de clone para o protocolo.
const bit<16> ETHERTYPE_IPV4 = 16w0x0800;
const bit<16> ETHERTYPE_TELEMETRY = 16w0x88B5;
const bit<32> CLONE_SESSION_DEFAULT = 32w250;
const bit<32> INSTANCE_TYPE_INGRESS_CLONE = 32w1;
const bit<8> TELEMETRY_MSG_PROBE = 8w0;
const bit<8> TELEMETRY_MSG_REPORT = 8w1;

// descreve o cabeçalho ethernet padrão de camada 2.
header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16> etherType;
}

// descreve o cabeçalho ipv4 mínimo necessário para encaminhamento l3.
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

// descreve o cabeçalho customizado de telemetria ativa.
// msg_type: 0 para sonda ativa, 1 para sincronização de latência ao vizinho.
// probe_index: índice local do emissor para gravar a latência daquele enlace.
// report_index: índice remoto usado pelo vizinho para gravar a latência recebida.
// is_returning: 0 indica ida para o vizinho, 1 indica retorno para origem.
// t_send e t_proc carregam os tempos para cálculo final de latência.
header telemetry_t {
    bit<8> msg_type;
    bit<8> probe_index;
    bit<8> report_index;
    bit<8> is_returning;
    timestamp_t t_send;
    timestamp_t t_proc;
    timestamp_t latency_value;
}

// define metadados internos usados para controlar clone e medir processamento.
struct metadata {
    // preserva a sessão de clone entre ingress e egress do pacote clonado.
    @field_list(1)
    bit<32> clone_session_id;

    // preserva o índice do registrador para gravação da latência.
    @field_list(1)
    bit<8> probe_index;

    // preserva o índice remoto para sincronizar a latência no vizinho.
    @field_list(1)
    bit<8> report_index;

    // habilita ou desabilita geração de sonda por pacote.
    bit<1> clone_enable;

    // guarda o tempo de entrada da sonda no switch refletor.
    timestamp_t s2_ingress_time;

    // snapshot de tempo para decidir se a sonda pode ser emitida no intervalo configurado.
    timestamp_t now_ts;

    // último instante em que uma sonda foi emitida para o índice monitorado.
    timestamp_t last_probe_ts;

    // intervalo mínimo entre sondas para o índice monitorado.
    timestamp_t probe_interval;
}

// agrupa todos os cabeçalhos manipulados no pipeline.
struct headers {
    ethernet_t ethernet;
    ipv4_t ipv4;
    telemetry_t telemetry;
}

// parser principal: identifica o tipo do quadro e extrai ipv4 ou telemetria.
parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {
    state start {
        // inicia pela extração do cabeçalho ethernet.
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);
        // seleciona o próximo estado com base no etherType.
        transition select(hdr.ethernet.etherType) {
            ETHERTYPE_IPV4: parse_ipv4;
            ETHERTYPE_TELEMETRY: parse_telemetry;
            default: accept;
        }
    }

    state parse_ipv4 {
        // extrai o cabeçalho ipv4 para fluxo de dados normal.
        packet.extract(hdr.ipv4);
        transition accept;
    }

    state parse_telemetry {
        // extrai o cabeçalho de telemetria para fluxo de sonda.
        packet.extract(hdr.telemetry);
        transition accept;
    }
}

// bloco de verificação de checksum: mantido vazio pois o foco é telemetria.
control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

// registrador stateful que armazena latência por índice de vizinho.
register<bit<48>>(1024) latency_reg;

// intervalo mínimo entre sondas por índice (em ticks do timestamp global).
register<bit<48>>(1024) probe_interval_reg;

// último timestamp de envio de sonda por índice.
register<bit<48>>(1024) last_probe_ts_reg;

// ingress: encaminha ipv4, cria sondas por clone, reflete telemetria e calcula latência final.
control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    // descarta pacote no pipeline.
    action drop() {
        mark_to_drop(standard_metadata);
    }

    // encaminha ipv4 com reescrita de mac e decremento de ttl.
    action ipv4_forward(macAddr_t dst_mac, macAddr_t src_mac, bit<9> port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.dstAddr = dst_mac;
        hdr.ethernet.srcAddr = src_mac;

        // evita underflow do ttl em pacotes já expirados.
        if (hdr.ipv4.ttl > 0) {
            hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        }
    }

    // habilita a geração de sonda e define sessão/índices preservados no clone.
    action enable_probe(bit<8> register_index, bit<8> remote_index, bit<32> clone_session_id) {
        meta.clone_enable = 1;
        meta.probe_index = register_index;
        meta.report_index = remote_index;
        meta.clone_session_id = clone_session_id;
    }

    // desabilita geração de sonda quando o perfil não exigir medição.
    action no_probe() {
        meta.clone_enable = 0;
        meta.probe_index = 0;
        meta.report_index = 0;
        meta.clone_session_id = 0;
    }

    // tabela de encaminhamento ipv4 por prefixo.
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

    // tabela que escolhe se o tráfego daquela porta deve gerar sonda.
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

    apply {
        // inicializa metadados para um estado previsível a cada pacote.
        meta.clone_enable = 0;
        meta.probe_index = 0;
        meta.report_index = 0;
        meta.clone_session_id = CLONE_SESSION_DEFAULT;
        meta.now_ts = 0;
        meta.last_probe_ts = 0;
        meta.probe_interval = 0;

        // fluxo de dados: pacote ipv4 normal sem cabeçalho de telemetria.
        if (hdr.ipv4.isValid() && !hdr.telemetry.isValid()) {
            ipv4_lpm.apply();

            // aplica o perfil para decidir se deve clonar este pacote.
            probe_profile.apply();
            if (meta.clone_enable == 1) {
                bit<32> interval_idx = (bit<32>)meta.probe_index;
                meta.now_ts = standard_metadata.ingress_global_timestamp;
                probe_interval_reg.read(meta.probe_interval, interval_idx);
                last_probe_ts_reg.read(meta.last_probe_ts, interval_idx);

                // emite sonda apenas quando o intervalo configurado expira.
                if ((meta.probe_interval == 0) ||
                    (meta.now_ts >= (meta.last_probe_ts + meta.probe_interval))) {
                    last_probe_ts_reg.write(interval_idx, meta.now_ts);

                    // cria clone ingress->egress preservando campos marcados com field_list 1.
                    clone_preserving_field_list(CloneType.I2E,
                                                meta.clone_session_id,
                                                1);
                }
            }
        } else if (hdr.telemetry.isValid()) {
            if (hdr.telemetry.msg_type == TELEMETRY_MSG_PROBE) {
                // fluxo de telemetria de ida no switch refletor.
                if (hdr.telemetry.is_returning == 0) {
                    // registra tempo de entrada para cálculo de processamento no egress.
                    meta.s2_ingress_time = standard_metadata.ingress_global_timestamp;

                    // inverte a direção e retorna pela mesma porta de entrada.
                    hdr.telemetry.is_returning = 1;
                    standard_metadata.egress_spec = standard_metadata.ingress_port;
                } else if (hdr.telemetry.is_returning == 1) {
                    // fluxo de telemetria de volta na origem para cálculo final.
                    bit<48> t_recv = standard_metadata.ingress_global_timestamp;
                    bit<48> t_send = hdr.telemetry.t_send;
                    bit<48> t_proc = hdr.telemetry.t_proc;

                    // calcula rtt total e remove custo interno de processamento do refletor.
                    bit<48> total_rtt = t_recv - t_send;
                    bit<48> prop_rtt = 0;
                    if (total_rtt > t_proc) {
                        prop_rtt = total_rtt - t_proc;
                    }

                    // divide por 2 via shift para obter latência unidirecional estimada.
                    bit<48> final_latency = prop_rtt >> 1;

                    // grava localmente a latência do vizinho monitorado.
                    bit<32> reg_index = (bit<32>)hdr.telemetry.probe_index;
                    latency_reg.write(reg_index, final_latency);

                    // converte a sonda em relatório para sincronizar a latência no vizinho.
                    hdr.telemetry.msg_type = TELEMETRY_MSG_REPORT;
                    hdr.telemetry.is_returning = 0;
                    hdr.telemetry.latency_value = final_latency;
                    standard_metadata.egress_spec = standard_metadata.ingress_port;
                }
            } else if (hdr.telemetry.msg_type == TELEMETRY_MSG_REPORT) {
                // no vizinho, persiste o valor recebido no índice remoto pré-configurado.
                bit<32> remote_reg_index = (bit<32>)hdr.telemetry.report_index;
                latency_reg.write(remote_reg_index, hdr.telemetry.latency_value);
                drop();
            } else {
                drop();
            }
        }
    }
}

// egress: monta a sonda clonada no emissor e registra t_proc no refletor.
control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {
        // identifica pacote clonado no egress para conversão em sonda enxuta.
        if (standard_metadata.instance_type == INSTANCE_TYPE_INGRESS_CLONE) {
            // remove ipv4/payload do clone para reduzir overhead de banda.
            hdr.ipv4.setInvalid();

            // preenche o cabeçalho de telemetria com dados de saída do emissor.
            hdr.telemetry.setValid();
            hdr.telemetry.msg_type = TELEMETRY_MSG_PROBE;
            hdr.telemetry.probe_index = meta.probe_index;
            hdr.telemetry.report_index = meta.report_index;
            hdr.telemetry.is_returning = 0;
            hdr.telemetry.t_send = standard_metadata.egress_global_timestamp;
            hdr.telemetry.t_proc = 0;
            hdr.telemetry.latency_value = 0;
            hdr.ethernet.etherType = ETHERTYPE_TELEMETRY;
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
control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.telemetry);
        packet.emit(hdr.ipv4);
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
