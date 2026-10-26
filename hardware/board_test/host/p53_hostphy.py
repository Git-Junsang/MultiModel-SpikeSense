#!/usr/bin/env python3
# p53_hostphy.py — Host NIC PHY register 읽기(SIOCGMIIREG, P5.3 결과 손실 조사). reg 10 = 1000BASE-T status: bit15 M/S 오류,
# bit14 1=master, bit13 local rx OK, bit12 remote rx OK, bit7:0 idle error count(읽으면 0). sudo로 실행.  p53_hostphy.py eno1 [초 간격 기간_s 출력파일]
import fcntl, socket, struct, sys, time
dev = sys.argv[1]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
def rd(phy, reg):
    req = struct.pack('16sHHHH', dev.encode(), phy, reg, 0, 0) + b'\0' * 8
    r = fcntl.ioctl(s.fileno(), 0x8948, req)
    return struct.unpack_from('16sHHHH', r)[4]
phy = struct.unpack_from('16sHHHH', fcntl.ioctl(s.fileno(), 0x8947, struct.pack('16sHHHH', dev.encode(), 0, 0, 0, 0) + b'\0' * 8))[1]
if len(sys.argv) < 3:
    for reg in (0, 1, 9, 10, 15):
        print(f'phy {phy} reg {reg:2d} = 0x{rd(phy, reg):04x}')
    sys.exit()
dt, T, out = float(sys.argv[2]), float(sys.argv[3]), open(sys.argv[4], 'w')
t_end = time.time() + T
while time.time() < t_end:
    v = rd(phy, 10)
    out.write(f'{time.time():.6f},{v}\n')
    out.flush()
    time.sleep(dt)
