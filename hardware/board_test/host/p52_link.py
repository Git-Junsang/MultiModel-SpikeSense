#!/usr/bin/env python3
"""p52_link.py — RGMII 수신 IDELAY tap과 송신 clock 위상을 LINK_TUNE(0x0318)으로 바꿔 가며 frame 손실을 잰다 (FPGA Host, P5.2)

LINK_TUNE: bit[4:0] 수신 tap(1 tap ≈ 78 ps), bit[31:16] 송신 clock 위상(90°에서 옮길 MMCM 미세 단계, 1단계 ≈ 17.9 ps, 부호 있음).
손실은 방향별로 나눈다. Host NIC의 rx_crc_errors 증가분 = FPGA → Host에서 깨진 frame,
응답이 없는 요청 − 그 증가분 = Host → FPGA에서 FPGA가 버린 frame(추정).
수신 tap이 너무 나쁘면 FPGA가 다음 LINK_TUNE 쓰기도 받지 못한다. 그러면 --bit를 JTAG로 다시 써서 기본값으로 되돌린다.

    python3 p52_link.py rx  [--tx 0] [--bit accel_top.bit] [--out rx.json]       # 수신 tap 0~31
    python3 p52_link.py tx  --rx <tap> [--lo -224 --hi 224 --step 8] [--out tx.json]   # 송신 위상
    python3 p52_link.py check --rx <tap> --tx <단계> [--n 5000]                   # 한 조합을 오래
"""
import argparse
import json
import os
import subprocess
import sys
import time

import p52_sys as p

DDR_TEST = p.DDR + 0x0100_0000             # 모델 slot·트랙 상태와 겹치지 않는 DDR3 주소(16 MiB)


def crc_errors():
    o = subprocess.run(['ethtool', '-S', 'eno1'], capture_output=True, text=True).stdout
    return int(next(l for l in o.splitlines() if 'rx_crc_errors' in l).split()[-1])


def try_ctl(ctl, *a, **k):
    try:
        return ctl(*a, **k)
    except SystemExit:
        return None


def set_tune(ctl, rx, tx, tries=60):
    """LINK_TUNE을 쓰고 다시 읽어 확인한다. 읽기 응답은 송신 쪽을 지나므로 송신이 나쁘면 쓰기만 여러 번 한다"""
    v = ((tx & 0xFFFF) << 16) | rx
    for _ in range(tries):
        try_ctl(ctl, 2, 0x0318, 1, [v], name='LINK_TUNE')
        r = try_ctl(ctl, 1, 0x0318, 1, name='LINK_TUNE read')
        if r == [v]:
            time.sleep(0.01)                   # MMCM 위상 이동(단계당 수십 cycle)
            return True
    return False


def reprogram(bit):
    print(f'  JTAG로 다시 씀: {bit}', flush=True)
    here = os.path.dirname(os.path.abspath(__file__))
    viv = os.environ.get('VIVADO', '/tools/Xilinx/2026.1/Vivado/bin/vivado')
    subprocess.run([viv, '-mode', 'batch', '-nojournal', '-nolog', '-source', f'{here}/program_fpga.tcl',
                    '-tclargs', '-bit', bit], check=True, stdout=subprocess.DEVNULL)
    time.sleep(6)                              # PHY reset 11 ms, auto-negotiation 약 3 s, MIG 보정


def measure(ctl, n):
    """작은 읽기 n개, 1 KiB 읽기(FPGA → Host 큰 frame) n/4개, 1 KiB 쓰기(Host → FPGA 큰 frame) n/4개"""
    c0 = crc_errors()
    sent = ok = 0
    big = [0x5A5A_0000 + i for i in range(256)]
    for k in range(n):
        for a in ([(1, 0x0200, 1, ())] + ([(1, DDR_TEST, 256, ()), (2, DDR_TEST, 256, big)] if k % 4 == 0 else [])):
            sent += 1
            ok += try_ctl(ctl, a[0], a[1], a[2], a[3], name='m') is not None
    crc = crc_errors() - c0
    return dict(sent=sent, ok=ok, tx_err=crc, rx_err=sent - ok - crc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['rx', 'tx', 'check'])
    ap.add_argument('--rx', type=int, default=1)
    ap.add_argument('--tx', type=int, default=0)
    ap.add_argument('--lo', type=int, default=-224)
    ap.add_argument('--hi', type=int, default=224)
    ap.add_argument('--step', type=int, default=8)
    ap.add_argument('--n', type=int, default=200)
    ap.add_argument('--bit', default=os.path.expanduser('~/mmss_jobs/p410_top/accel_top.bit'))
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    ctl = p.Ctl(0.02)
    rows = []
    if a.mode == 'rx':
        taps = list(range(1, 32)) + [0]        # 기본 tap 1에서 위로 훑고, 막히면 다시 써서 0
        for t in taps:
            if not set_tune(ctl, t, a.tx):
                reprogram(a.bit)
                if not set_tune(ctl, t, a.tx):
                    print(f'tap {t:2d}: LINK_TUNE을 쓰지 못함', flush=True)
                    rows.append(dict(rx=t, tx=a.tx, set=False))
                    continue
            m = measure(ctl, a.n)
            rows.append(dict(rx=t, tx=a.tx, set=True, **m))
            print(f'tap {t:2d}: 보냄 {m["sent"]}, 응답 {m["ok"]}, FPGA→Host CRC 오류 {m["tx_err"]}, Host→FPGA 손실 {m["rx_err"]}', flush=True)
    elif a.mode == 'tx':
        for s in range(a.lo, a.hi + 1, a.step):
            ok = set_tune(ctl, a.rx, s)
            m = measure(ctl, a.n)
            rows.append(dict(rx=a.rx, tx=s, set=ok, **m))
            print(f'tx {s:+4d} ({s * 1000 / 56:+6.0f} ps): 확인 {int(ok)}, 보냄 {m["sent"]}, 응답 {m["ok"]}, '
                  f'FPGA→Host CRC 오류 {m["tx_err"]}, Host→FPGA 손실 {m["rx_err"]}', flush=True)
        set_tune(ctl, a.rx, 0)
    else:
        ok = set_tune(ctl, a.rx, a.tx)
        m = measure(ctl, a.n)
        rows.append(dict(rx=a.rx, tx=a.tx, set=ok, **m))
        print(f'rx {a.rx} tx {a.tx:+d}: 확인 {int(ok)}, 보냄 {m["sent"]}, 응답 {m["ok"]}, FPGA→Host CRC 오류 {m["tx_err"]}, '
              f'Host→FPGA 손실 {m["rx_err"]}', flush=True)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, 'w') as f:
            json.dump(rows, f, indent=1)


if __name__ == '__main__':
    sys.exit(main())
