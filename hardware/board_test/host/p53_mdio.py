#!/usr/bin/env python3
"""p53_mdio.py — FPGA의 MDIO master(regs 0x0108)로 보드 PHY register를 읽고 쓴다 (FPGA Host, P5.3)

보드 설명서는 KSZ9031(주소 011)이라 하지만 이 보드의 PHY는 주소 1에서 ID 0x937C·0x4032(JLSemi JL2101 계열)로 응답한다.
주소 0은 broadcast로 같이 응답한다. reg 0x10 이상은 제조사 register라 이름을 붙이지 않는다.

    python3 p53_mdio.py dump                 # 주요 register
    python3 p53_mdio.py rd <reg>             # 16진 reg
    python3 p53_mdio.py wr <reg> <값>        # 16진
    python3 p53_mdio.py master               # 1000BASE-T master로 고정(reg 9 bit 12·11)하고 auto-negotiation 다시 시작
    python3 p53_mdio.py auto                 # master/slave 자동으로 되돌리고 다시 시작
"""
import sys
import time

import p52_sys as p

PHY = 1
NAMES = {0x00: 'BMCR', 0x01: 'BMSR', 0x02: 'PHYID1', 0x03: 'PHYID2', 0x04: 'AN advertisement', 0x05: 'AN partner',
         0x09: '1000BASE-T control', 0x0A: '1000BASE-T status', 0x0F: 'extended status'}


def cmd(ctl, op, reg, data=0):
    ctl.wr(0x0108, (op << 30) | (PHY << 21) | (reg << 16) | data, 'MDIO')
    for _ in range(100):
        v = ctl.rd(0x0108, 1, 'MDIO')[0]
        if not v >> 31:
            return v & 0xFFFF
        time.sleep(0.001)
    raise SystemExit('MDIO busy')


def rd(ctl, reg):
    return cmd(ctl, 2, reg)


def wr(ctl, reg, v):
    cmd(ctl, 1, reg, v)


def dump(ctl):
    for r, n in NAMES.items():
        v = rd(ctl, r)
        x = ''
        if r == 0x0A:
            x = (f"  M/S 오류 {v >> 15 & 1}, master {v >> 14 & 1}, local rx OK {v >> 13 & 1}, "
                 f"remote rx OK {v >> 12 & 1}, idle 오류 {v & 0xFF}")
        print(f'reg 0x{r:02X} {n:20s} 0x{v:04X}{x}')


def main():
    ctl = p.Ctl(0.2)
    a = sys.argv[1:]
    if not a or a[0] == 'dump':
        dump(ctl)
    elif a[0] == 'rd':
        print(f'0x{rd(ctl, int(a[1], 16)):04X}')
    elif a[0] == 'wr':
        wr(ctl, int(a[1], 16), int(a[2], 16))
    elif a[0] in ('master', 'auto'):
        v = rd(ctl, 0x09)
        v = (v | 0x1800) if a[0] == 'master' else (v & ~0x1800)
        wr(ctl, 0x09, v)
        b = rd(ctl, 0x00) | 0x0200                     # auto-negotiation 다시 시작. 곧 링크가 끊기므로 busy를 기다리지 않는다
        ctl.wr(0x0108, (1 << 30) | (PHY << 21) | b, 'MDIO restart')
        print(f'reg 9 ← 0x{v:04X}, auto-negotiation 다시 시작', flush=True)
        time.sleep(6)
        dump(ctl)


if __name__ == '__main__':
    main()
