# A03: SpikeX

원문: `A03_SpikeX_2025.pdf`
Xu, Boone, Li, 2025

## 1. 문제

SNN은 multiply가 단순해도 weight 이동 비용이 크다. SpikeX는 weight reuse, zero-spike skip, hardware-aware training으로 이 비용을 줄인다.

## 2. 방법

- DRAM → global buffer → local double buffer의 3단 메모리 hierarchy
- 여러 timestep을 time window로 묶어 weight reuse
- activation tag가 0이면 관련 weight read 생략
- layer별 time-window 크기 탐색
- training loss에 EDP 근사값 반영

평가 구조는 8×8 PE, global buffer 54 KB, local buffer 2 KB다.

## 3. 결과

| 항목 | 논문 결과 |
|---|---:|
| FC layer energy 중 메모리 | 62% |
| 전체 energy 중 weight access | 40.1% |
| 전체 energy 중 DRAM | 1.7% |
| 매우 낮은 spike rate latency | 최대 7.11배 개선 |
| PTB 대비 EDP | 15.1–150.87배 개선 |

Weight access와 DRAM access는 같은 항목이 아니다. 위 수치를 우리 시스템에 그대로 적용하면 안 된다.

## 4. 우리 연구에 쓰는 범위

SpikeX는 미래 timestep을 함께 계산한다. 우리 추론 요청은 32 ms마다 도착하므로 미래 입력을 미리 묶을 수 없다. 대신 현재 준비된 같은 모델의 여러 트랙을 묶는다.

참고할 부분:

- hierarchical buffer
- double buffering
- weight reuse
- zero-spike read skip

차이:

- SpikeX는 단일 모델이다.
- 모델 cache 경쟁과 추론 요청별 deadline이 없다.
- 우리 Channel Window는 트랙 batching이다.

따라서 buffer, prefetch, timestep reuse 자체를 신규 기법으로 주장하지 않는다.

원문 확인: 문제 §II-B, scheduling §VI-A, energy §VI-B.
