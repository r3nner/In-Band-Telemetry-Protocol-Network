import os
with open('control_plane/program_linear.sh', 'r') as f:
    text = f.read()

veth_logic = '''
# Configuração da interface do controlador na root namespace
if ! ip link show ctrl-eth0 >/dev/null 2>&1; then
    echo "[INFO] Criando veth pair para o controlador..."
    ip link add name ctrl-eth0 type veth peer name ctrl-eth1
    ip link set ctrl-eth0 up
    ip addr add 10.0.0.254/24 dev ctrl-eth1 || true
    ip link set ctrl-eth1 up
fi

'''

if 'ctrl-eth0' not in text:
    text = text.replace('CONTROLLER_IP_INT=', veth_logic + 'CONTROLLER_IP_INT=')
    text = text.replace('mirroring_add 250 2', 'port_add ctrl-eth0 3\nmirroring_add 250 2')
    text = text.replace('mirroring_add 250 1', 'port_add ctrl-eth0 3\nmirroring_add 250 1')
    text = text.replace('mirroring_add 252 0', 'mirroring_add 252 3')
    text = text.replace('mirroring_add 252 1', 'mirroring_add 252 3')
    text = text.replace('mirroring_add 252 2', 'mirroring_add 252 3')
    
    with open('control_plane/program_linear.sh', 'w') as f:
        f.write(text)
    print('Patched program_linear.sh')
else:
    print('Already patched')
