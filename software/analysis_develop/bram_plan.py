#!/usr/bin/env python3
"""bram_plan.py — P3.4 32레인 온칩 메모리 구성의 BRAM 타일 수 계산

XC7A200T의 BRAM은 RAMB36 타일 365개(각각 RAMB18 2개로 나눌 수 있음)다. 타일 하나는
36 Kibit이고, 폭이 9의 배수인 구성(4K×9, 2K×18, 1K×36, 512×72)에서는 그중 4 Kibit
"패리티" 비트도 데이터로 쓸 수 있다.

  - 넓은 word(가중치 256 bit, 큐 512 bit)는 9 bit 열로 쪼개면 비트를 가리지 않으므로
    타일당 36 Kibit를 모두 쓴다. 예: 4,096 × 256 bit = RAMB36(4K×9) 28개 + RAMB18(4K×4) 1개
    = 28.5 타일. P3.2 fit 실험에서 Vivado가 실제로 이렇게 배치했다.
  - 좁은 word(막전위·β·vth 16 bit)는 18 bit 폭에서 2 bit가 남아 타일당 32 Kibit만 쓴다.

계산 규칙: (깊이 d, 폭 w)인 RAMB36 구성마다 열 수 = 폭 ÷ w(내림), 남는 비트는
RAMB18(같은 깊이, 폭 w/2)로 덮을 수 있으면 0.5 타일, 아니면 1 타일. 깊이 방향은
ceil(D/d)단. 모든 구성 중 최소를 택한다. Vivado 추론이 이보다 많이 쓰는 경우가 있다
(예: 28,240 × 16 bit β·vth를 32K×1 × 16 = 16 타일로 추론; 2K×18 지정 시 14).

    python3 software/analysis_develop/bram_plan.py --xdma 20.5
"""
import argparse
import math

TILES = 365
KIB_PER_TILE = 4.5            # 36 Kibit (패리티 포함 물리 용량)
CFG36 = [(512, 72), (1024, 36), (2048, 18), (4096, 9), (8192, 4), (16384, 2), (32768, 1)]


def tiles(depth, width):
    """depth × width bit 메모리의 최소 RAMB36 환산 타일 수 (RAMB18 = 0.5)"""
    best = math.inf
    for d, w in CFG36:
        cols, rem = divmod(width, w)
        if rem:
            cols += 0.5 if (d <= 16384 and rem <= w // 2) else 1
        best = min(best, cols * math.ceil(depth / d))
        # 깊이가 RAMB18 하나로 충분하면 RAMB18만으로 (폭 w/2) 구성
        if d <= 16384 and depth <= d and w >= 2:
            best = min(best, 0.5 * math.ceil(width / (w // 2)))
    return best


W_WORDS = 480 + 3072 + 512 + 4          # 층 1~4 (층 4는 2뉴런 × 64입력 = 128 B를 4 word에 묶음)
ENTRY = tiles(4096, 256)                 # 깊이 2^12 (4,068 word 사용)
SLICE = tiles(1024, 256)                 # 512 word × 2 (이중 버퍼)
MEM = {'L1': tiles(512 * 384, 16), 'L2': tiles(512 * 256, 16),
       'L3': tiles(512 * 64, 16), 'L4': tiles(512 * 2, 16)}
MEM_T = sum(MEM.values())
BV40 = tiles(40 * 706, 16)
BV1 = tiles(706, 16)
QUEUE = tiles(512, 512)
META = tiles(512, 64)
L1ALL = tiles(40 * 480, 256)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xdma', type=float, required=True, help='XDMA BRAM 타일 실측값(P3.2)')
    ap.add_argument('--other', type=float, default=0.0, help='기타 실측 타일(MIG 등)')
    a = ap.parse_args()

    print('## 구성 요소별 타일 수 (RAMB36 환산)\n')
    print('| 구성 요소 | 깊이 × 폭 | 데이터 | 타일 |')
    print('|---|---|---:|---:|')
    rows = [
        ('가중치 캐시 엔트리 1개', '4,096 × 256 bit (4,068 사용)', W_WORDS * 32, ENTRY),
        ('슬라이스 이중 버퍼', '2 × 512 × 256 bit', 2 * 512 * 32, SLICE),
        ('막전위 L1', '196,608 × 16 bit', 512 * 384 * 2, MEM['L1']),
        ('막전위 L2', '131,072 × 16 bit', 512 * 256 * 2, MEM['L2']),
        ('막전위 L3', '32,768 × 16 bit', 512 * 64 * 2, MEM['L3']),
        ('막전위 L4', '1,024 × 16 bit', 512 * 2 * 2, MEM['L4']),
        ('β·vth 40모델 상주', '28,240 × 16 bit', 40 * 706 * 2, BV40),
        ('β·vth 엔트리 1개분', '706 × 16 bit', 706 * 2, BV1),
        ('요청 큐', '512 × 512 bit', 512 * 64, QUEUE),
        ('트랙 메타', '512 × 64 bit', 512 * 8, META),
        ('부분 상주: 40모델 L1', '19,200 × 256 bit', 40 * 15360, L1ALL),
    ]
    for n, s, b, t in rows:
        print(f'| {n} | {s} | {b:,} B | {t:g} |')
    print(f'\n막전위 합계 {MEM_T:g} 타일 = {MEM_T / TILES * 100:.1f}% '
          f'(데이터 722,944 B, 물리 {MEM_T * KIB_PER_TILE:.2f} KiB)\n')

    fixed = a.xdma + a.other
    print(f'## 저장 정책별 예산 (XDMA {a.xdma:g} + 기타 {a.other:g} 타일 실측 반영)\n')
    print('| 시나리오 | 고정 사용 | 가중치에 남는 타일 | 전체 모델 엔트리 | 잔여 타일 |')
    print('|---|---:|---:|---:|---:|')
    scen = [
        ('A. 제안서 배분: 모델 1벌 프리페치 버퍼, β·vth 40모델, 큐·메타 BRAM',
         fixed + MEM_T + ENTRY + BV40 + QUEUE + META, ENTRY),
        ('B. 슬라이스 이중 버퍼, β·vth 40모델, 큐·메타 BRAM',
         fixed + MEM_T + SLICE + BV40 + QUEUE + META, ENTRY),
        ('C. 별도 버퍼 없음(빈 엔트리에 직접 채움), β·vth 40모델, 큐·메타 BRAM',
         fixed + MEM_T + BV40 + QUEUE + META, ENTRY),
        ('D. 슬라이스 이중 버퍼, β·vth 엔트리별(+버퍼 1벌), 큐·메타 분산 RAM',
         fixed + MEM_T + SLICE + BV1, ENTRY + BV1),
        ('E. 별도 버퍼 없음, β·vth 엔트리별, 큐·메타 분산 RAM',
         fixed + MEM_T, ENTRY + BV1),
    ]
    for n, used, per in scen:
        left = TILES - used
        k = int(left // per)
        print(f'| {n} | {used:g} | {left:g} | {k} | {left - k * per:g} |')

    base = TILES - (fixed + MEM_T + ENTRY)
    print(f'\n제안서 709.375 KiB 갱신: 365 − XDMA {fixed:g} − 막전위 {MEM_T:g} − 프리페치 1벌 {ENTRY:g} '
          f'= {base:g} 타일 = {base * KIB_PER_TILE:.2f} KiB (물리), '
          f'β·vth·큐·메타까지 빼면 {base - BV40 - QUEUE - META:g} 타일 = '
          f'{(base - BV40 - QUEUE - META) * KIB_PER_TILE:.2f} KiB')
    left_b = TILES - (fixed + MEM_T + SLICE + BV40 + QUEUE + META)
    print(f'부분 상주(40모델 L1 전체 {L1ALL:g} 타일)는 시나리오 B 잔여 {left_b:g} 타일에 '
          f'{"들어간다" if L1ALL <= left_b else "들어가지 않는다"} (차이 {left_b - L1ALL:g}).')
    off = TILES - (fixed + SLICE + BV40 + QUEUE + META)
    print(f'막전위를 전부 DDR3에 두면(시나리오 B 기준) 가중치에 {off:g} 타일 → '
          f'엔트리 {int(off // ENTRY)}개. 막전위 이동량은 요청당 읽기·쓰기 2 × 1,412 B.')


if __name__ == '__main__':
    main()
