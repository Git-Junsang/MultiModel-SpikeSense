#!/usr/bin/env python3
"""compare_figs.py — 최대 트랙 실험 그림 7~13을 모델 L(왼쪽)과 XL(오른쪽)로 나란히 붙인다

입력: sim_result/figures/fig{7..13}_dse2_*.png (L), fig{7..13}_dse2_xl_*.png (XL) — plot_max_tracks.py 결과
출력: sim_result/figures/compare/cmp_fig{n}_*_L_vs_XL.png
    python3 software/sim_develop/compare_figs.py
"""
import glob
import os

import matplotlib.font_manager as fm
from PIL import Image, ImageDraw, ImageFont

FIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sim_result', 'figures')
OUT = os.path.join(FIG, 'compare')
FONT = fm.findfont('UnDotum')
TITLE = {7: '전수 탐색 히트맵', 8: '한 축만 바꾸기', 9: '레인 수에 따른 최대 트랙', 10: '트랙 수에 따른 응답',
         11: '저장 방식별 BRAM 사용', 12: '한 축씩 차례로 고르기', 13: '조건 민감도'}
SIDE = [('모델 L   40→384→256→64→2   가중치 13만 (현재)', (222, 235, 247)),
        ('모델 XL   40→768→512→128→2   가중치 49만 (은닉층 2배)', (253, 232, 214))]
HEAD, CAP, GAP = 64, 56, 8


def pair(n):
    xl = glob.glob(os.path.join(FIG, f'fig{n}_dse2_xl_*.png'))
    lo = [f for f in glob.glob(os.path.join(FIG, f'fig{n}_dse2_*.png')) if '_xl_' not in f]
    return (lo[0], xl[0]) if lo and xl else None


def main():
    os.makedirs(OUT, exist_ok=True)
    big, small = ImageFont.truetype(FONT, 34), ImageFont.truetype(FONT, 26)
    for n in TITLE:
        p = pair(n)
        if not p:
            continue
        ims = [Image.open(f).convert('RGB') for f in p]
        h = max(im.height for im in ims)
        ims = [im if im.height == h else im.resize((round(im.width * h / im.height), h)) for im in ims]
        w = sum(im.width for im in ims) + GAP
        canvas = Image.new('RGB', (w, CAP + HEAD + h), 'white')
        d = ImageDraw.Draw(canvas)
        d.text((20, 12), f'그림 {n} 비교 — {TITLE[n]}: 왼쪽 L, 오른쪽 XL (각 그래프의 y축 범위가 다름, 시뮬레이션 값)',
               font=small, fill='black')
        x = 0
        for im, (label, col) in zip(ims, SIDE):
            d.rectangle([x, CAP, x + im.width, CAP + HEAD], fill=col)
            d.text((x + 24, CAP + 13), label, font=big, fill='black')
            canvas.paste(im, (x, CAP + HEAD))
            x += im.width + GAP
        d.rectangle([ims[0].width, CAP, ims[0].width + GAP - 1, CAP + HEAD + h], fill=(120, 120, 120))
        stem = os.path.basename(p[0]).replace('.png', '').replace('_dse2', '')
        out = os.path.join(OUT, f'cmp_{stem}_L_vs_XL.png')
        canvas.save(out, optimize=True)
        print(out, canvas.size)


if __name__ == '__main__':
    main()
