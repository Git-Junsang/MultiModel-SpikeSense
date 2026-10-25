"""p325_common.py — P3.25 Host jitter 측정(M1~M4) 공통 값, CPU 부하, 출력 파일, 측정 조건 기록

시각은 모두 Host의 time.monotonic_ns()(CLOCK_MONOTONIC) ns다. 트랙 t의 모델은 t % 40, 모델 m의 offset은 m × 0.8 ms다
(01_OVERVIEW.md §3). 결과는 hardware/board_test/p325_meas/result/에 두고, 로그의 −1은 값 없음이다.
측정 조건(명령, 머신, 장치)은 로그 옆 <로그>.json에 남긴다. 이미 있는 출력 파일은 덮어쓰지 않는다.
"""
import gzip
import json
import multiprocessing as mp
import os
import platform
import socket
import sys
import time

SR, HOP, FRAME = 16000, 512, 1024          # Hz, 샘플. hop 32 ms, frame 64 ms
SEG = 31                                   # segment = 추론 요청 31개(992 ms). 첫 추론 요청에 RESET_STATE
P_NS = 32_000_000                          # 추론 요청 주기 = deadline, ns
M = 40                                     # 모델 수
OFF_NS = P_NS // M                         # offset 간격 0.8 ms
RESULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'p325_meas', 'result'))


def blocked(what, need):
    """장치·backend가 없어 측정할 수 없다. 값을 만들지 않고 종료 코드 2로 끝낸다"""
    print(f'BLOCKED_BY_HARDWARE: {what}\n  필요한 것: {need}', file=sys.stderr)
    sys.exit(2)


def open_out(path):
    """.gz면 gzip(level 1, 긴 측정도 빨리 쓴다), 아니면 그냥 연다. 있는 파일은 덮어쓰지 않는다(측정 원자료 보호)"""
    if os.path.exists(path):
        sys.exit(f'출력 파일이 이미 있다: {path} (다른 --out을 쓴다)')
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if path.endswith('.gz'):
        return gzip.open(path, 'wt', compresslevel=1, newline='')
    return open(path, 'w', newline='')


def open_in(path):
    return gzip.open(path, 'rt', newline='') if path.endswith('.gz') else open(path, newline='')


def write_meta(out, **info):
    """측정 조건을 <out>.json에 남긴다. 조건 없이 남은 로그는 해석할 수 없다. loadavg는 측정이 끝난 때의 값이다"""
    cpu = next((ln.split(':', 1)[1].strip() for ln in open('/proc/cpuinfo') if ln.startswith('model name')), '')
    info.update(host=socket.gethostname(), kernel=platform.release(), python=platform.python_version(), cpu=cpu,
                cpus=os.cpu_count(), loadavg=os.getloadavg(), argv=sys.argv, wall=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    with open(out + '.json', 'w') as f:
        json.dump(info, f, ensure_ascii=False, indent=1, default=str)


def read_meta(log):
    try:
        with open(log + '.json') as f:
            return json.load(f)
    except OSError:
        return {}


def _spin(avoid):
    cpus = os.sched_getaffinity(0) - set(avoid)
    if cpus:
        os.sched_setaffinity(0, cpus)
    while True:
        pass


class CpuLoad:
    """CPU 부하 process n개(순수 Python 무한 루프). avoid = 부하를 두지 않을 CPU(--pin으로 고정한 측정 thread의 CPU).
    shortcut: 계산 부하만 준다. 메모리 대역폭·interrupt 부하가 필요하면 stress-ng 등으로 바꾼다"""

    def __init__(self, n, avoid=()):
        self.ps = [mp.get_context('fork').Process(target=_spin, args=(tuple(avoid),), daemon=True) for _ in range(n)]

    def __enter__(self):
        for p in self.ps:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.ps:
            p.terminate()
        for p in self.ps:
            p.join()


def parse_cpus(s):
    """'3' 또는 '2,3' → [2, 3]. 이 process가 쓸 수 있는 CPU인지 확인한다"""
    cpus = [int(x) for x in s.split(',') if x.strip()] if s else []
    bad = set(cpus) - os.sched_getaffinity(0)
    if bad:
        sys.exit(f'--pin {sorted(bad)}: 쓸 수 없는 CPU (사용 가능 {sorted(os.sched_getaffinity(0))})')
    return cpus
