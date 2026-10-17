#!/usr/bin/env python3
"""p3_ddr_bench.py — P3.1 DDR3 실효 대역폭·지연 측정 매트릭스 (FPGA Host, root 권한)

p3_top의 트래픽 생성기(ddr_tgen)를 레지스터로 설정·실행하고, 실행마다 설정·결과·
전송별 지연 기록(최대 2,048개)을 JSON 한 줄로 남긴다. 분석은 개발 서버의
hardware/board_test/host/analyze_p3.py가 한다.

    sudo python3 p3_ddr_bench.py --tag brc --out ~/fpga_work/p3/ddr_brc.jsonl [--quick]

그룹 (cycle은 ui_clk 100 MHz = 10 ns, 1 beat = 32 B):
  full     1 GiB 전 범위 쓰기 → 읽기 검증, seed와 그 보수로 두 번 (P1.6의 16 MiB 한계 보완)
  burst    순차 접근, 버스트 길이 1~128 beat × 쓰기/읽기, 64 MiB, pipelined, outst 16
  outst    순차 읽기, 버스트 16/128에서 동시 버스트 수 1~16
  slice    슬라이스 크기별 읽기: 모델 전환(SLOT_RAND 40슬롯)과 같은 모델 연속(SEQ),
           blocking(한 번에 하나)과 pipelined(연속 요청)
  model    모델 단위·layer 단위 가져오기: 전체 weight 130,176 B, 슬롯 135,168 B, L1/L2/L3,
           β·threshold 포함 구간, SLOT_RAND / SLOT_RR
  single   단일 beat 지연: 임의 주소(1 GiB) blocking, 순차 blocking
  random   임의 주소 소단위(32 B~4 KiB) pipelined 처리량
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p3_regs import P3  # noqa: E402

GiB = 1 << 30
MiB = 1 << 20
SLOT = 0x21000            # 모델 슬롯 132 KiB (MODEL_MEMORY_LAYOUT.md)
MODEL_W = 130176          # weight 4,068 beat


def beats(nbytes):
    assert nbytes % 32 == 0, nbytes
    return nbytes // 32


def plan(quick):
    """(group, label, kwargs) 목록."""
    P = []
    # ---- full: 1 GiB 쓰기·검증 ----
    for seed in (0x5A5A1234, 0xA5A5EDCB):
        P.append(('full', f'write_1GiB_s{seed:08x}',
                  dict(write=True, amode='seq', pipe=True, base=0, xfer_beats=beats(MiB),
                       burst_max=128, n=1024, max_outst=16, seed=seed, log_mask=0)))
        P.append(('full', f'verify_1GiB_s{seed:08x}',
                  dict(write=False, verify=True, amode='seq', pipe=True, base=0,
                       xfer_beats=beats(MiB), burst_max=128, n=1024, max_outst=16, seed=seed)))
    # ---- burst: 순차, 버스트 길이 ----
    nseq = 16 if quick else 64          # × 1 MiB
    for wr in (False, True):
        for bl in (1, 2, 4, 8, 16, 32, 64, 128):
            P.append(('burst', f'{"wr" if wr else "rd"}_bl{bl}',
                      dict(write=wr, amode='seq', pipe=True, base=0x1000_0000,
                           xfer_beats=beats(MiB), burst_max=bl, n=nseq, max_outst=16)))
    # ---- outst: 동시 버스트 수 ----
    for bl in (16, 128):
        for mo in (1, 2, 4, 8, 16):
            P.append(('outst', f'rd_bl{bl}_mo{mo}',
                      dict(write=False, amode='seq', pipe=True, base=0x1000_0000,
                           xfer_beats=beats(MiB), burst_max=bl, n=nseq, max_outst=mo)))
    # ---- slice: 슬라이스 크기 ----
    sizes = [512, 1024, 2048, 4096, 8192, 15360, 16384, 32768, 65536, 98304, MODEL_W]
    for sz in sizes:
        n = 2048 if sz <= 16384 else (1024 if sz <= 65536 else 512)
        if quick:
            n = min(n, 256)
        for amode, base in (('slot_rand', 0), ('seq', 0x2000_0000)):
            for pipe in (False, True):
                kw = dict(write=False, amode=amode, pipe=pipe, base=base, xfer_beats=beats(sz),
                          burst_max=128, n=n, max_outst=16, stride=SLOT, slot_cnt=40, slot_mask=63)
                if amode == 'seq':
                    kw['wrap'] = 64 * MiB
                P.append(('slice', f'{amode}_{"pipe" if pipe else "blk"}_{sz}', kw))
    # ---- model: 모델·layer 단위 ----
    secs = [('weights', 0x00000, MODEL_W), ('slot', 0x00000, SLOT),
            ('L1', 0x00000, 15360), ('L2', 0x03C00, 98304), ('L3', 0x1BC00, 16384),
            ('L1toParams', 0x00000, 0x20260)]   # 0x20242 → 32 B 올림(β·threshold 포함 연속 구간)
    for name, off, sz in secs:
        for amode in ('slot_rand', 'slot_rr'):
            P.append(('model', f'{name}_{amode}',
                      dict(write=False, amode=amode, pipe=False, base=off,
                           xfer_beats=beats(sz), burst_max=128, n=256 if quick else 1024,
                           max_outst=16, stride=SLOT, slot_cnt=40, slot_mask=63)))
    # ---- single: 단일 beat 지연 ----
    P.append(('single', 'rand_1GiB_blk',
              dict(write=False, amode='rand_beat', pipe=False, base=0, xfer_beats=1,
                   burst_max=1, n=2048, max_outst=1, addr_mask=(1 << 25) - 1)))
    P.append(('single', 'seq_blk',
              dict(write=False, amode='seq', pipe=False, base=0x3000_0000, xfer_beats=1,
                   burst_max=1, n=2048, max_outst=1)))
    P.append(('single', 'rand_1GiB_blk_wr',
              dict(write=True, amode='rand_beat', pipe=False, base=0, xfer_beats=1,
                   burst_max=1, n=2048, max_outst=1, addr_mask=(1 << 25) - 1)))
    # ---- random: 임의 주소 소단위 처리량 ----
    for sz in (32, 64, 128, 256, 512, 1024, 2048, 4096):
        P.append(('random', f'rand_pipe_{sz}',
                  dict(write=False, amode='rand_beat', pipe=True, base=0,
                       xfer_beats=beats(sz), burst_max=128, n=16384 if not quick else 2048,
                       max_outst=16, addr_mask=((1 << 25) - 1) & ~(beats(sz) - 1),
                       log_mask=7)))
    return P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True, help='비트스트림 구분(brc / rbc)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--groups', default='full,burst,outst,slice,model,single,random')
    a = ap.parse_args()

    p = P3()
    st = p.status()
    print(f'path={p.path} STATUS={st}', flush=True)
    if not st['calib']:
        raise SystemExit('DDR3 캘리브레이션 미완료')
    p.w('DDR_SEL', 0)
    groups = set(a.groups.split(','))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'a') as f:
        for grp, label, kw in plan(a.quick):
            if grp not in groups:
                continue
            cfg, res = p.run(**kw)
            rec = {'tag': a.tag, 'group': grp, 'label': label, 'time': time.time(),
                   'cfg': cfg, 'res': res}
            f.write(json.dumps(rec) + '\n')
            f.flush()
            avg = res['lat_sum'] / res['xfers'] if res['xfers'] else 0
            print(f'{grp:6s} {label:28s} {res["GBps"]:6.3f} GB/s  xfers={res["xfers"]:5d} '
                  f'lat[min={res["lat_min"]} avg={avg:.1f} max={res["lat_max"]}] '
                  f'fst_min={res["fst_min"]} err={res["err_cnt"]} proto={res["proto_err"]}',
                  flush=True)


if __name__ == '__main__':
    main()
