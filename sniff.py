import socket
import binascii

s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
s.bind(('ctrl-eth1', 0))
s.settimeout(5.0)
print('Listening on ctrl-eth1...')
try:
    while True:
        data, addr = s.recvfrom(65535)
        # Assuming Ethernet (14) + IPv4 (20) = 34 bytes offset for UDP
        if len(data) > 36 and data[12:14] == b'\x08\x00' and data[23] == 17:
            src_port = (data[34] << 8) + data[35]
            dst_port = (data[36] << 8) + data[37]
            if dst_port == 9999:
                print('Found UDP packet to 9999 on ctrl-eth1:', binascii.hexlify(data))
                break
            else:
                print('Found other UDP packet on ctrl-eth1:', binascii.hexlify(data))
        elif len(data) > 14 and data[12:14] == b'\x08\x00':
            print('Found IPv4 packet on ctrl-eth1:', binascii.hexlify(data))
        else:
            print('Found other packet on ctrl-eth1:', binascii.hexlify(data))
except socket.timeout:
    print('Timeout')
