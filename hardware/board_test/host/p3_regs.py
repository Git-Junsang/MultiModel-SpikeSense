#!/usr/bin/env python3
"""p3_regs.py — P3 측정 설계(p3_top)의 레지스터 접근 (FPGA Host, root 권한)

BAR0(XDMA AXI-Lite 마스터, 64 KiB)를 mmap해 32 bit 단위로 읽고 쓴다.
XDMA 드라이버가 적재되어 있으면 /dev/xdma0_user를, 없으면
/sys/bus/pci/devices/<BDF>/resource0을 연다. 레지스터 지도는 p3_core.v 머리말과 같다.

    sudo python3 p3_regs.py            # ID·상태·시각 출력
    sudo python3 p3_regs.py rd 0x8     # 한 레지스터 읽기
    sudo python3 p3_regs.py wr 0x44 1  # 쓰기
"""
import glob
import mmap
import os
import sys
import time

ID_MAGIC = 0x4D4D5033

REG = {
    'ID': 0x0000, 'VERSION': 0x0004, 'STATUS': 0x0008, 'SCRATCH': 0x000C,
    'TS_LO': 0x0010, 'TS_HI': 0x0014, 'MARK': 0x0018,
    'MARK_TS_LO': 0x001C, 'MARK_TS_HI': 0x0020, 'MARK_VAL': 0x0024,
    'CTRL': 0x0040, 'DDR_SEL': 0x0044, 'OPMODE': 0x0048, 'BASE': 0x004C,
    'XFER_BEATS': 0x0050, 'BURST_MAX': 0x0054, 'N_XFERS': 0x0058, 'MAX_OUTST': 0x005C,
    'STRIDE': 0x0060, 'SLOT_CNT': 0x0064, 'SLOT_MASK': 0x0068, 'ADDR_MASK': 0x006C,
    'WRAP': 0x0070, 'SEED': 0x0074, 'GAP': 0x0078, 'LOG_MASK': 0x007C,
    'CYCLES_LO': 0x0100, 'CYCLES_HI': 0x0104, 'BEATS_LO': 0x0108, 'BEATS_HI': 0x010C,
    'XFERS': 0x0110, 'LAT_MIN': 0x0114, 'LAT_MAX': 0x0118, 'LAT_SUM_LO': 0x011C,
    'LAT_SUM_HI': 0x0120, 'FST_MIN': 0x0124, 'FST_MAX': 0x0128, 'FST_SUM_LO': 0x012C,
    'FST_SUM_HI': 0x0130, 'ERR_CNT': 0x0134, 'ERR_ADDR': 0x0138, 'PROTO_ERR': 0x013C,
    'AX_STALL': 0x0140, 'W_STALL': 0x0144, 'LOG_N': 0x0148,
}
LOG_BASE = 0x8000
UI_HZ = 100e6

AMODE = {'seq': 0, 'slot_rand': 1, 'rand_beat': 2, 'slot_rr': 3}


def find_bdf():
    for d in glob.glob('/sys/bus/pci/devices/*'):
        try:
            v = open(f'{d}/vendor').read().strip()
            p = open(f'{d}/device').read().strip()
        except OSError:
            continue
        if v == '0x10ee' and p == '0x7022':
            return d
    raise SystemExit('10ee:7022 장치가 없다 (PCIe 재스캔·비트스트림 확인)')


class P3:
    def __init__(self, path=None):
        if path is None:
            path = '/dev/xdma0_user' if os.path.exists('/dev/xdma0_user') else f'{find_bdf()}/resource0'
            if path.endswith('resource0'):
                en = path.replace('resource0', 'enable')
                if open(en).read().strip() == '0':
                    open(en, 'w').write('1')
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_SYNC)
        self.mm = mmap.mmap(self.fd, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        self.mv = memoryview(self.mm).cast('I')   # 32 bit 단위 접근

    def rd(self, off):
        return self.mv[off >> 2]

    def wr(self, off, val):
        self.mv[off >> 2] = val & 0xFFFFFFFF

    def r(self, name):
        return self.rd(REG[name])

    def w(self, name, val):
        self.wr(REG[name], val)

    def r64(self, name):
        lo = self.rd(REG[name + '_LO'])
        hi = self.rd(REG[name + '_HI'])
        return (hi << 32) | lo

    def ts(self):
        lo = self.rd(REG['TS_LO'])          # 상위는 이 읽기 시점에 보관된다
        return (self.rd(REG['TS_HI']) << 32) | lo

    def status(self):
        s = self.r('STATUS')
        return {'calib': s & 1, 'lnk_up': (s >> 1) & 1, 'busy': (s >> 2) & 1,
                'done': (s >> 3) & 1, 'ddr_sel': (s >> 4) & 1, 'narrow': (s >> 5) & 1}

    # ---------------- 트래픽 생성기 ----------------
    def run(self, write=False, verify=False, amode='seq', pipe=False, base=0, xfer_beats=128,
            burst_max=128, n=1, max_outst=16, stride=0x21000, slot_cnt=40, slot_mask=63,
            addr_mask=(1 << 25) - 1, wrap=0, seed=0x12345678, gap=0, log_mask=0,
            read_log=True, timeout=60.0):
        assert self.r('DDR_SEL') == 0, 'DDR_SEL=1(호스트)이면 트래픽 생성기를 쓰지 않는다'
        cfg = dict(write=int(write), verify=int(verify), amode=amode, pipe=int(pipe), base=base,
                   xfer_beats=xfer_beats, burst_max=burst_max, n=n, max_outst=max_outst,
                   stride=stride, slot_cnt=slot_cnt, slot_mask=slot_mask, addr_mask=addr_mask,
                   wrap=wrap, seed=seed, gap=gap, log_mask=log_mask)
        self.w('OPMODE', int(write) | (int(verify) << 1) | (AMODE[amode] << 2) | (int(pipe) << 4))
        for k, v in (('BASE', base), ('XFER_BEATS', xfer_beats), ('BURST_MAX', burst_max),
                     ('N_XFERS', n), ('MAX_OUTST', max_outst), ('STRIDE', stride),
                     ('SLOT_CNT', slot_cnt), ('SLOT_MASK', slot_mask), ('ADDR_MASK', addr_mask),
                     ('WRAP', wrap), ('SEED', seed), ('GAP', gap), ('LOG_MASK', log_mask)):
            self.w(k, v)
        t0 = time.monotonic()
        self.w('CTRL', 1)
        while True:
            st = self.r('STATUS')
            if not (st >> 2) & 1 and (st >> 3) & 1:
                break
            if time.monotonic() - t0 > timeout:
                self.w('CTRL', 2)
                time.sleep(0.1)
                raise RuntimeError(f'시간 초과: {cfg}')
            time.sleep(0.0005)
        res = {
            'cycles': self.r64('CYCLES'), 'beats': self.r64('BEATS'), 'xfers': self.r('XFERS'),
            'lat_min': self.r('LAT_MIN'), 'lat_max': self.r('LAT_MAX'), 'lat_sum': self.r64('LAT_SUM'),
            'fst_min': self.r('FST_MIN'), 'fst_max': self.r('FST_MAX'), 'fst_sum': self.r64('FST_SUM'),
            'err_cnt': self.r('ERR_CNT'), 'err_addr': self.r('ERR_ADDR'),
            'proto_err': self.r('PROTO_ERR'), 'ax_stall': self.r('AX_STALL'),
            'w_stall': self.r('W_STALL'), 'log_n': self.r('LOG_N'),
        }
        res['bytes'] = res['beats'] * 32
        res['sec'] = res['cycles'] / UI_HZ
        res['GBps'] = res['bytes'] / res['sec'] / 1e9 if res['cycles'] else 0.0
        if read_log:
            lat, fst = [], []
            for i in range(res['log_n']):
                fst.append(self.rd(LOG_BASE + 8 * i))
                lat.append(self.rd(LOG_BASE + 8 * i + 4))
            res['log_lat'] = lat
            res['log_fst'] = fst
        return cfg, res


def main():
    p = P3()
    if len(sys.argv) >= 3 and sys.argv[1] == 'rd':
        print(hex(p.rd(int(sys.argv[2], 0))))
        return
    if len(sys.argv) >= 4 and sys.argv[1] == 'wr':
        p.wr(int(sys.argv[2], 0), int(sys.argv[3], 0))
        return
    print(f'path={p.path}')
    print(f'ID=0x{p.r("ID"):08X} ({"OK" if p.r("ID") == ID_MAGIC else "불일치"}) '
          f'VERSION=0x{p.r("VERSION"):08X}')
    print('STATUS', p.status())
    t1 = p.ts()
    time.sleep(1.0)
    t2 = p.ts()
    print(f'TS 1초 간격 차 = {t2 - t1} (100 MHz면 약 1e8)')


if __name__ == '__main__':
    main()
