#!/usr/bin/env python3
"""p325_udp_lat.py — M4 Ethernet 지연 (P3.25)

Host가 추론 요청(64 B, 06_HOST_INTERFACE.md §4.1)을 offset 순서로 보내고 결과(32 B, §4.2)를 받아 시각을 남긴다.
epoch k에 모델 m의 트랙(track % 40 = m)은 offset 시각 T0 + k × 32 ms + m × 0.8 ms에 이어서 보낸다(즉시 보내기).
받는 쪽은 1단계에서 두 번째 PC의 echo(이 script), 2단계에서 FPGA Ethernet RTL이다. 둘 다 결과의 t_in_us(도착)와
t_done_us(완료)를 자기 µs clock(32 bit)으로 채운다. 편도 지연은 analyze_p325.py가 1초 창마다 왕복이 가장 짧은 표본으로
두 clock의 차이를 구해 나눈다(06 §5와 같은 생각, 양방향 대칭 가정).

    python3 hardware/board_test/host/p325_udp_lat.py echo --bind 0.0.0.0:50250                         # 두 번째 PC
    python3 hardware/board_test/host/p325_udp_lat.py send --target 10.0.0.2:50250 --seconds 300 [--pin 3] [--load 8]
    python3 hardware/board_test/host/p325_udp_lat.py send --target <FPGA IP>:<port> ...                 # Ethernet RTL 뒤
    python3 hardware/board_test/host/p325_udp_lat.py loopback --seconds 5 --out <파일>                   # 코드 확인만
loopback은 같은 PC의 127.0.0.1이다. Ethernet 측정이 아니고 코드 확인용이다. 화면과 <out>.json에 그렇게 남긴다.
출력 열(send 순서, −1 = 값 없음):
  seq, track_id, model_id, epoch, t_send_host_ns, t_arr_fpga_ns, t_done_fpga_ns, t_recv_host_ns, lost, reordered,
  retransmitted, t_sched_host_ns(보내기로 한 offset 시각)
  t_arr_fpga_ns·t_done_fpga_ns는 받는 쪽 clock이다(µs 값의 32 bit 되감기를 풀고 × 1,000). retransmitted는 늘 0이다
  (재전송 없음, 06 §8 미정). lost = 보낸 뒤 drain 시간(기본 1 s) 안에 결과 없음, reordered = 나중에 보낸 추론 요청의 결과가 먼저 옴.
Python의 송수신 지연(GIL, socket 호출)이 들어간다. Host runtime이 Python이면 그것도 Host가 겪는 지연이다.
1,024트랙 300 s는 960만 줄이다(gzip 줄당 약 22 B, 약 220 MB). 기록은 메모리에 두었다가 끝나고 쓴다(약 1.2 GB).
"""
import argparse
import multiprocessing as mp
import os
import socket
import struct
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p325_common import M, OFF_NS, P_NS, RESULT, SEG, CpuLoad, open_out, parse_cpus, write_meta  # noqa: E402

REQ = struct.Struct('<BBHHBxI4x40s8x')      # magic, flags, track_id, seq, model_id, t_gen_us, x[40]
RES = struct.Struct('<HHBBHIIIIhh4x')       # track_id, seq, model_id, flags, batch_n, t_gen_us, t_in_us, t_start_us, t_done_us, out0, out1
assert REQ.size == 64 and RES.size == 32
COLS = ('seq,track_id,model_id,epoch,t_send_host_ns,t_arr_fpga_ns,t_done_fpga_ns,t_recv_host_ns,lost,reordered,'
        'retransmitted,t_sched_host_ns')
LOOPBACK = 'loopback code-check (127.0.0.1, Ethernet 측정 아님)'


def now_us():
    return (time.monotonic_ns() // 1000) & 0xFFFFFFFF


def unwrap_us(ti, td):
    """받는 쪽 32 bit µs(send 순서) → 되감기를 푼 ns. done은 arr 기준으로 풀어 둘이 다른 바퀴에 서지 않게 한다"""
    u = np.unwrap(ti.astype(np.float64), period=2.0 ** 32).astype(np.int64)
    return u * 1000, (u + (td - ti) % 2 ** 32) * 1000


def addr(s):
    h, p = s.rsplit(':', 1)
    return h, int(p)


def echo_loop(s):
    """FPGA 대신 결과를 돌려준다. t_in = 받은 직후, t_done = 보내기 직전(µs). 잘못된 추론 요청은 버린다(06 §4.3처럼)"""
    while True:
        b, peer = s.recvfrom(2048)
        ti = now_us()
        if len(b) != REQ.size or b[0] != 0xA5:
            continue
        _, _, tid, seq, mid, tg, _ = REQ.unpack(b)
        s.sendto(RES.pack(tid, seq, mid, 0, 1, tg, ti, ti, now_us(), 0, 0), peer)


def udp(bind=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 22)
    if bind:
        s.bind(bind)
    return s


def send(target, tracks, seconds, pin, drain=1.0):
    """추론 요청을 보내고 결과를 받는다. 반환: 열 이름 → 배열(send 순서), 시작 시각 T0, {중복, 잘못된 packet 수}"""
    T, E = tracks, int(round(seconds * 1e9 / P_NS))
    groups = [[t for t in range(T) if t % M == m] for m in range(M)]
    pos = [0] * T                                                   # 트랙의 epoch 안 send 순서
    for i, t in enumerate(t for g in groups for t in g):
        pos[t] = i
    N = E * T
    t_send, t_recv, t_in, t_done, rord = (np.full(N, -1, np.int64) for _ in range(5))
    s = udp()
    s.connect(target)
    s.settimeout(0.2)
    stop, kcur, extra = threading.Event(), [0], {'dup': 0, 'bad': 0}

    def rx():
        if pin:
            os.sched_setaffinity(0, {pin[-1]})
        c = 0
        while not stop.is_set():
            try:
                b = s.recv(64)
            except socket.timeout:
                continue
            except ConnectionRefusedError:                          # 받는 쪽이 아직 없음(ICMP)
                extra['bad'] += 1
                continue
            t = time.monotonic_ns()
            if len(b) != RES.size:
                extra['bad'] += 1
                continue
            tid, seq, _, _, _, _, ti, _, td, _, _ = RES.unpack(b)
            k = kcur[0] - ((kcur[0] - seq) & 0xFFFF)                # 16 bit seq 되감기
            if not (0 <= k < E and tid < T):
                extra['bad'] += 1
                continue
            n = k * T + pos[tid]
            if t_recv[n] >= 0:
                extra['dup'] += 1
                continue
            t_recv[n], t_in[n], t_done[n], rord[n] = t, ti, td, c
            c += 1

    th = threading.Thread(target=rx, daemon=True)
    th.start()
    if pin:
        os.sched_setaffinity(0, {pin[0]})
    x = bytes(range(40))                                            # mel 자리(0~39 ≤ 127)
    t0 = time.monotonic_ns() + 200_000_000
    for k in range(E):
        kcur[0] = k
        for m in range(M):
            ts = t0 + k * P_NS + m * OFF_NS
            d = ts - time.monotonic_ns()
            if d > 0:
                time.sleep(d / 1e9)
            tg = (ts // 1000) & 0xFFFFFFFF                          # Host 시각 µs(FPGA 시각 보정 전, 06 §5)
            for t in groups[m]:
                pkt = REQ.pack(0xA5, int(k % SEG == 0), t, k & 0xFFFF, m, tg, x)
                n = k * T + pos[t]
                t_send[n] = time.monotonic_ns()
                try:
                    s.send(pkt)
                except ConnectionRefusedError:                      # 앞 packet의 ICMP. 이 packet은 lost로 남는다
                    pass
    time.sleep(drain)
    stop.set()
    th.join()
    s.close()

    order = [t for g in groups for t in g]
    track = np.tile(order, E)
    epoch = np.repeat(np.arange(E), T)
    got = t_recv >= 0
    arr = np.full(N, -1, np.int64)
    done = np.full(N, -1, np.int64)
    if got.any():
        arr[got], done[got] = unwrap_us(t_in[got], t_done[got])
    reo = np.zeros(N, np.int64)
    c = rord[got]
    later_min = np.r_[np.minimum.accumulate(c[::-1])[::-1][1:], np.iinfo(np.int64).max]
    reo[np.flatnonzero(got)] = c > later_min                        # 나중에 보낸 추론 요청의 결과가 먼저 왔다
    cols = dict(seq=epoch & 0xFFFF, track_id=track, model_id=track % M, epoch=epoch, t_send_host_ns=t_send,
                t_arr_fpga_ns=arr, t_done_fpga_ns=done, t_recv_host_ns=t_recv, lost=(~got).astype(np.int64),
                reordered=reo, retransmitted=np.zeros(N, np.int64),
                t_sched_host_ns=t0 + epoch * P_NS + (track % M) * OFF_NS)
    return cols, t0, extra


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('mode', choices=('echo', 'send', 'loopback'))
    ap.add_argument('--bind', default='0.0.0.0:50250', help='echo가 받을 주소')
    ap.add_argument('--target', default='', help='send의 받는 쪽 주소 host:port')
    ap.add_argument('--tracks', type=int, default=1024)
    ap.add_argument('--seconds', type=float, default=300.0)
    ap.add_argument('--pin', default='', help='보내기 thread, 받기 thread를 고정할 CPU(쉼표로 1~2개)')
    ap.add_argument('--load', type=int, default=0, help='CPU 부하 process 수')
    ap.add_argument('--note', default='')
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    if a.mode == 'echo':
        print(f'echo {a.bind} (Ctrl-C로 끝)')
        try:
            echo_loop(udp(addr(a.bind)))
        except KeyboardInterrupt:
            return
    pin, lc = parse_cpus(a.pin), f'load{a.load}'
    if a.mode == 'send' and not a.target:
        sys.exit('send는 --target host:port가 필요하다')
    out = a.out or os.path.join(RESULT, f"m4_{'loopback_check' if a.mode == 'loopback' else 'udp'}_t{a.tracks}_{lc}.csv.gz")
    f = open_out(out)
    child = None
    target = addr(a.target) if a.target else None
    if a.mode == 'loopback':
        print(f'주의: {LOOPBACK}')
        es = udp(('127.0.0.1', 0))
        target = es.getsockname()
        child = mp.get_context('fork').Process(target=echo_loop, args=(es,), daemon=True)
        child.start()
        es.close()
    with CpuLoad(a.load, pin):
        cols, t0, extra = send(target, a.tracks, a.seconds, pin)
    if child:
        child.terminate()
    write_meta(out, test='M4', mode=a.mode, label=LOOPBACK if a.mode == 'loopback' else f'{a.mode} → {target[0]}',
               target=target, tracks=a.tracks, seconds=a.seconds, pin=pin, load=a.load, T0_ns=t0, **extra, note=a.note)
    with f:
        f.write(COLS + '\n')
        for i in range(0, cols['epoch'].size, 1 << 20):                 # 나눠 써서 메모리를 아낀다
            np.savetxt(f, np.column_stack([cols[c][i:i + (1 << 20)] for c in COLS.split(',')]), fmt='%d', delimiter=',')
    got = cols['lost'] == 0
    rtt = (cols['t_recv_host_ns'] - cols['t_send_host_ns'])[got] / 1e3
    p = np.percentile(rtt, [50, 99, 99.9]) if got.any() else [np.nan] * 3
    print(f"{'[loopback code-check] ' if child else ''}추론 요청 {got.size}개, 결과 없음 {(~got).sum()}, 순서 바뀜 {cols['reordered'].sum()}, "
          f"중복 {extra['dup']}, 왕복 p50 {p[0]:.1f} µs p99 {p[1]:.1f} µs p99.9 {p[2]:.1f} µs → {out}")


if __name__ == '__main__':
    main()
