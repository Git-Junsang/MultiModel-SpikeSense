"""analysis/develop 공용: 경로, 결과 읽기, 그림 저장, 그림 서식.

그림 하나 = 스크립트 하나. analysis/develop/<주제>/<그림 이름>.py → analysis/figure/<주제>/<그림 이름>.png
  주제      그 실험으로 보려던 것 (scheduler, jitter, entry …)
  그림 이름 fig<번호>_x-<x축>_y-<y축>[_c-<색 값>]. 번호는 주제 안에서 1부터, 값이 여러 단어면 '-'로 잇는다
simulation 그림은 simulation/result/<환경 이름>.csv(점별)·_runs.csv.gz(실행별)를, 모델 그림은 software/train_result를 읽는다.

    python3 analysis/develop/<주제>/<그림 이름>.py
"""
import csv
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
TRAIN = os.path.join(ROOT, 'software', 'train_result')
RESULT = os.path.join(ROOT, 'simulation', 'result')
sys.path.insert(0, os.path.join(ROOT, 'simulation', 'engine'))
import engine  # noqa: E402

# Simulation 그림 색 (옛 plot_target·plot_p311과 같다. 범주 4색은 인접 CVD ΔE ≥ 9.1로 검증)
INK, MUTED, GRAY, SURF = '#0b0b0b', '#52514e', '#b4b2a9', '#fcfcfb'
SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']
BLUE = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']   # 순차 ramp 100–700


# 방법 비교(compare) 그림의 행 순서: 비교군 → ablation(Offset Assignment 없음 → HW만 → SW만 → SW+HW)
METHOD_ORDER = ['Dysta Method', 'DeepRT Method', 'Grouping(offset 배정 없음)', 'HW만: offset-order cache', 'SW만: Host offset 배정', 'SW+HW: 제안']


TYPES = ['fan', 'pump', 'slider', 'valve', 'ToyCar', 'ToyConveyor']
TYPE_COLOR = dict(zip(TYPES, ['#3b6ea5', '#c0623b', '#4f9a55', '#9a4f8f', '#c9a227', '#5b5b5b']))


def mtype(unit):
    return unit.rsplit('_id', 1)[0]


def model_results(name='L_normal_noaug'):
    """train_result/<학습 이름>/results.csv, 장비 종류 순서로"""
    with open(os.path.join(TRAIN, name, 'results.csv')) as f:
        rows = list(csv.DictReader(f))
    return sorted(rows, key=lambda r: (TYPES.index(mtype(r['unit'])), r['unit']))


def points(env):
    """simulation/result/<env>.csv: 점마다 한 줄(환경 값 + 요약)"""
    return engine.read_csv(os.path.join(RESULT, f'{env}.csv'))


def runs(env):
    """simulation/result/<env>_runs.csv.gz: 실행마다 한 줄"""
    return engine.read_csv(os.path.join(RESULT, f'{env}_runs.csv.gz'))


def seq_cmap():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list('blue', BLUE)


def agg(rows):
    """_runs.csv 실행 여러 개를 합산(engine.summarize). 시나리오만 고를 때 쓴다"""
    return engine.summarize(rows)


def by_point(rows):
    """_runs.csv 행을 점 번호별로"""
    d = {}
    for r in rows:
        d.setdefault(r['point'], []).append(r)
    return d


def header(fig, title, sub, legend=None, top=0.86):
    """제목·부제·범례를 그림 위에 겹치지 않게 놓는다. 그림 높이에 맞춰 간격을 inch로 잡는다"""
    h = fig.get_size_inches()[1]
    fig.suptitle(title, fontsize=10, x=0.01, y=0.995, ha='left', va='top')
    fig.text(0.01, 0.995 - 0.22 / h, sub, fontsize=8, color=MUTED, va='top')
    if legend:
        fig.legend(handles=legend, loc='upper right', ncol=len(legend), frameon=False, fontsize=8,
                   bbox_to_anchor=(0.99, 0.995 - 0.40 / h), borderaxespad=0)
    fig.tight_layout(rect=(0, 0, 1, top))


def clean(ax):
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)


def sim_style():
    plt.rcParams.update({'font.family': 'Pretendard', 'axes.unicode_minus': False, 'font.size': 9,
                         'axes.edgecolor': '#c3c2b7', 'axes.linewidth': 0.8, 'axes.grid': True,
                         'grid.color': '#e6e5e0', 'grid.linewidth': 0.8, 'axes.axisbelow': True,
                         'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.labelcolor': MUTED,
                         'axes.titleweight': 'bold', 'axes.titlesize': 10, 'figure.facecolor': SURF,
                         'axes.facecolor': SURF})


def paper_style():
    """논문 그림: 영문 세리프(Times 호환) 7 pt, 흰 배경, PDF에 TrueType 글꼴을 넣는다. offset/fig5와 같은 서식"""
    sim_style()
    plt.rcParams.update({'font.family': 'serif', 'font.serif': ['Liberation Serif'], 'mathtext.fontset': 'stix',
                         'font.size': 7, 'axes.titlesize': 7.5, 'axes.labelsize': 7, 'xtick.labelsize': 7,
                         'ytick.labelsize': 7, 'legend.fontsize': 7, 'pdf.fonttype': 42,
                         'figure.facecolor': 'white', 'axes.facecolor': 'white'})


# 논문 그림의 방법 이름·색·marker. 그림끼리 같게 둔다
PAPER_METHOD = {'Dysta Method': ('Dysta Method', SERIES[1], 's'), 'DeepRT Method': ('DeepRT Method', SERIES[2], '^'),
                'SW+HW: 제안': ('Proposed', SERIES[0], 'o')}


def model_style():
    """모델 그림은 영문 라벨(학회 서식·폰트 호환)"""
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
                         'axes.labelsize': 9, 'axes.titlesize': 9.5, 'legend.fontsize': 8,
                         'xtick.labelsize': 8, 'ytick.labelsize': 8,
                         'axes.grid': True, 'grid.alpha': 0.25, 'grid.linewidth': 0.5,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'figure.dpi': 150, 'savefig.bbox': 'tight', 'savefig.pad_inches': 0.02})


def save(fig, script, exts=('png',), **kw):
    """script(__file__)와 같은 주제·이름으로 analysis/figure/<주제>/<이름>.<ext>에 저장한다"""
    topic = os.path.basename(os.path.dirname(os.path.abspath(script)))
    name = os.path.splitext(os.path.basename(script))[0]
    out = os.path.join(ROOT, 'analysis', 'figure', topic)
    os.makedirs(out, exist_ok=True)
    for ext in exts:
        p = os.path.join(out, f'{name}.{ext}')
        fig.savefig(p, **kw)
        print(os.path.relpath(p, ROOT))
    plt.close(fig)
