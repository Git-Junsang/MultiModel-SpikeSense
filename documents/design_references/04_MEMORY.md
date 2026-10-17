# 04. 메모리

## 1. 요약

BRAM은 weight cache entry와 membrane potential이 나눠 쓴다. offset 배정으로 weight 재사용이 높아지면 entry는 jitter가 요구하는 만큼만 두고 남는 BRAM에 membrane potential을 두는 쪽이 DDR3 전송량이 적다. 기본 구성은 entry 4개(116 tile)와 on-chip membrane potential 768트랙(12 bit, 199 tile)이다. 나머지 256트랙의 membrane potential과 weight 40벌은 DDR3에 둔다.

## 2. BRAM 배분

XC7A200T의 BRAM은 36 Kib tile 365개, 약 1.6 MiB다. 계산식은 [engine.py](../../simulation/engine/engine.py)의 `tiles()`다.

| 대상 | tile | 근거 |
|---|---:|---|
| Host 링크 IP | 20.5 | XDMA 실측값(P3.2)을 자리로 둔다. Ethernet MAC은 아직 재지 않았다 |
| 예약: request table, 송수신 buffer 등 | 25.5 | 계산 |
| membrane potential 준비 buffer | 4.0 | 계산 |
| weight cache entry | 29 × entry 수 | 2,034 × 512 bit + 누설 계수·threshold 706 × 16 bit |
| on-chip membrane potential | 나머지 | 남는 tile에 들어가는 트랙 수(16트랙 단위) |

| entry | entry tile | 남는 tile | on-chip 트랙 16 / 12 / 8 bit | DDR3 KiB/추론(12 bit), jitter 0.8 / 1.6 / 3.2 ms |
|---:|---:|---:|---|---|
| 2 | 58 | 257 | 736 / 976 / 1,024 | 6.27 / 7.77 / 52.5 |
| 3 | 87 | 228 | 656 / 864 / 1,024 | 6.33 / 6.50 / 23.8 |
| **4** | **116** | **199** | **576 / 768 / 1,024** | **6.36 / 6.51 / 7.08** |
| 5 | 145 | 170 | 480 / 640 / 976 | 6.45 / 6.58 / 6.94 |
| 6 | 174 | 141 | 400 / 528 / 816 | 6.51 / 6.63 / 6.92 |
| 8 | 232 | 83 | 240 / 320 / 480 | 6.61 / 6.70 / 6.97 |
| 10 | 290 | 25 | 64 / 80 / 128 | 6.77 / 6.84 / 7.11 |

DDR3 값은 simulation(seed 10)이다. entry 4는 jitter 0.8~3.2 ms에서 각 jitter의 최소값과 10% 안으로 차이 난다. 같은 entry 4라도 membrane potential을 전부 DDR3에 16 bit로 두면 8.6 KiB/추론이다. 12 bit로 일부를 on-chip에 두면 26% 적다.

## 3. weight cache

| 항목 | 값 |
|---|---|
| entry 구성 | 64 B word 2,034개 + params RAM(뉴런 706개 × `{β, vth}`) |
| word 주소 | layer 1 0~239, layer 2 240~1,775, layer 3 1,776~2,031, layer 4 2,032~2,033 |
| 적재 단위 | 모델 전체(유효 131,648 B). slice 단위 적재는 하지 않는다 |
| 적재 시간 | 0.244 µs + 131,648 B ÷ 3.015 GB/s = 43.9 µs (4,391 cycle) |
| 쓰기 | `dma`가 32 B beat 2개를 word 하나로 쓴다. word 주소 = beat 번호 ÷ 2 |
| 읽기 | `compute_array`가 cycle마다 word 2개까지(spike 2개/cycle) |

연산 중인 entry 하나를 빼고 나머지가 cache다. 다음 batch의 모델이 entry에 없으면 지금 batch를 연산하는 동안 빈 entry(또는 내보낼 entry)로 prefetch한다. 그래서 entry는 최소 2개가 필요하다.

### 3.1 offset-order 교체

cache miss가 나면 entry 가운데 다음 사용 시점이 가장 먼 모델을 내보낸다. offset 배정 뒤에는 모델이 매 주기 offset 순서(0 → 1 → … → 39 → 0)로 오므로, 다음 사용 순서는 offset 번호 순서와 같다.

```text
거리(e) = (offset_table[model(e)] − offset_now) mod 40
내보낼 entry = 연산 중이 아닌 entry 가운데 거리가 가장 큰 것
```

`offset_now`는 지금 적재하려는 모델의 offset 번호다. Host가 시작할 때 모델별 offset 번호 40개를 `offset_table`에 한 번 쓴다. 추론 요청마다 주고받는 정보는 없다. simulator는 트랙의 offset으로 다음 사용 시각을 계산하는데, offset 배정 상태에서는 이 표와 결과가 같다.

LRU는 순환 접근에서 효과가 낮다. 가장 오래 안 쓴 모델이 바로 다음에 쓸 모델이기 때문이다. jitter 0.8 ms, entry 4에서 offset-order는 6.36, LRU는 6.69 KiB/추론이다(5% 적음). jitter 10 ms, entry 10에서는 14.8과 27.0 KiB/추론으로 45% 적다.

## 4. entry 수 정하기

필요한 entry 수는 jitter J에 거의 비례한다. 늦은 요청이 아직 올 수 있는 모델은 지난 J 동안 offset이 지나간 모델들이고 offset은 0.8 ms마다 지나간다.

```text
entry ≈ max(2, ceil(J / 0.8 ms))
```

최소 2는 지금 연산할 모델과 다음에 prefetch할 모델 자리다. simulation에서 entry 4는 jitter 3.2 ms까지 DDR3 전송량 증가를 jitter 0.8 ms 대비 20% 안으로 막았다. entry 10은 jitter 6.4 ms까지 버텼다. entry가 모자라면 DDR3 전송량이 몇 배로 뛴다(entry 2, jitter 3.2 ms에서 52.5 KiB/추론).

| cache | 0.8 ms | 1.6 ms | 3.2 ms | 6.4 ms | 10 ms | 20 ms |
|---|---:|---:|---:|---:|---:|---:|
| offset-order, 2개 | 6.27 | 7.77 | 52.5 | 73.1 | 80.3 | 89.2 |
| offset-order, 4개 | 6.36 | 6.51 | 7.08 | 40.5 | 57.2 | 75.3 |
| offset-order, 10개 | 6.77 | 6.84 | 7.11 | 7.73 | 14.8 | 41.1 |
| LRU, 4개 | 6.69 | 6.69 | 9.87 | 55.2 | 71.9 | 85.9 |
| LRU, 10개 | 8.08 | 8.08 | 8.08 | 8.26 | 27.0 | 65.2 |

값은 DDR3 KiB/추론(simulation)이다. jitter가 약 8 ms를 넘으면 BRAM에 둘 수 있는 entry만으로는 흡수하기 어렵다. 이때 Host가 같은 모델의 그 주기 요청이 다 준비될 때까지 모았다가 한 번에 보내면, entry 2개로도 jitter와 관계없이 약 6.26 KiB/추론을 유지한다. 대신 먼저 준비된 요청이 기다리므로 응답 시간이 는다(jitter 20 ms에서 최대 21.8 ms).

정하는 순서:

1. Host 계산 jitter(M3)와 전송 jitter(M4)를 잰다. 장치 없이 할 수 있다.
2. USB 마이크 2개 이상으로 buffer 설정별 jitter(M1)와 clock drift(M2)를 잰다.
3. 즉시 보내기면 측정한 J로 위 식을 쓰고 한 단계 크게 잡는다. 모아 보내기면 entry 2로 두고 대기 시간을 오디오 buffer 주기 이상으로 정한다.
4. §2 표에서 남는 BRAM에 membrane potential을 12 bit로 둔다.

측정 방법과 추정 범위는 [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9에 있다.

## 5. membrane potential

| 항목 | 값 |
|---|---|
| 계산 | 16 bit 포화 연산(`sat16`) |
| 저장 | 12 bit, ±2,048로 포화. 다음 추론으로 넘길 때만 줄인다 |
| 트랙당 크기 | 706뉴런 × 12 bit = 1,059 B |
| on-chip 트랙 | 남는 BRAM에 들어가는 만큼. entry 4면 768트랙 |
| DDR3 트랙 | 나머지 256트랙. 추론마다 1,059 B 읽기 + 1,059 B 쓰기(약 1.2 µs) |
| 초기화 | 요청에 `RESET_STATE`가 있으면 읽지 않고 0에서 시작. 쓰기는 항상 한다 |

`dma` 우선순위는 membrane potential 읽기, membrane potential 쓰기, weight 적재 순서다. simulation은 DMA 하나를 순서대로 쓴다고 봤다.

미정:

- 어느 트랙을 on-chip에 둘지. simulation은 모든 트랙이 고르게 요청을 낸다고 보고 요청당 평균으로 넣었다. Host가 `track_id`가 작은 트랙부터 on-chip에 배정하는 방식이 가장 단순하다.
- 12 bit의 byte 포장(DDR3), `membrane_bank`의 layer별 bank 구성과 폭.
- layer마다 저장 bit를 따로 정하면 8 bit로도 손실이 없는지. 8 bit면 entry 4에서 1,024트랙이 모두 on-chip에 들어간다. 지금 8 bit(아래 2 bit 버림)는 4대가 0.01~0.02 떨어진다.
- DDR3 트랙의 membrane potential을 모델별로 이어 붙여 batch 하나를 DMA 한 번으로 읽고 쓰는 것. byte는 같고 DMA 횟수가 준다.

## 6. DDR3

| 영역 | 시작 (MIG byte 주소) | 크기 | 주소 |
|---|---|---:|---|
| 모델 slot | `MODEL_BASE` = `0x0000_0000` | 40 × 256 KiB = 10 MiB | `MODEL_BASE + model_id × 0x4_0000` |
| membrane potential | `STATE_BASE` = `0x0200_0000` | 1,024 × 2 KiB = 2 MiB | `STATE_BASE + track_id × 0x800` |
| 여유 | `0x1000_0000` | 768 MiB | 시험 data |

slot 형식은 [02_MODEL.md](02_MODEL.md) §6에 있다. 트랙마다 2 KiB를 잡고 앞 1,059 B만 전송한다.

| 측정 (P3.1 보드) | 값 |
|---|---|
| 순차 읽기 | 3.015 GB/s |
| read 시간 회귀식 | 0.244 µs + byte ÷ 3.015 GB/s |
| 쓰기 (simulation 비용) | 2.768 GB/s |

## 7. 관련 문서

- [P3.13 보고서](<../reports/P3.13 Research Report.md>) §3.1, §5: cache 교체와 BRAM 배분 결과
- [P3.21 보고서](<../reports/P3.21 Research Report.md>): 넓은 jitter와 모아 보내기
- [P3.1~P3.4 보고서](<../reports/P3.1~3.4 Research Report.md>): DDR3·BRAM 실측
