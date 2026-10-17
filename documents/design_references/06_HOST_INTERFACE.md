# 06. Host와 통신

## 1. 요약

Host는 PC다. 마이크 입력에서 mel을 구하고(특징 추출), 트랙마다 모델의 offset에 맞춰 frame을 끊어 추론 요청을 바로 보낸다(offset 배정). 결과를 받아 판정하고 deadline miss를 센다. FPGA와는 Gigabit Ethernet(UDP)으로 연결한다. 추론 요청과 결과의 필드는 P3.9에서 정한 것을 그대로 쓴다. Ethernet 위의 framing, 제어 경로, 모델 적재 경로는 아직 정하지 않았다.

## 2. Host 역할

| 일 | 내용 |
|---|---|
| 입력 | USB 마이크 또는 다채널 오디오 장치. 1,024트랙 부하 시험은 load generator가 대신한다 |
| 특징 추출 | 16 kHz, 64 ms 구간에서 mel 40개, 32 ms씩 이동. 0~127로 양자화 ([02_MODEL.md](02_MODEL.md) §4) |
| offset 배정 | 트랙마다 frame 끝 시각을 모델의 offset에 맞춘다 ([05_SCHEDULING.md](05_SCHEDULING.md) §2) |
| frame 자르기 기준 | Host clock. 장치마다 다른 오디오 clock을 따르면 frame 끝이 시간이 갈수록 offset에서 벗어난다 |
| 오디오 buffer | 저지연 설정(목표 1~4 ms). 실제 값은 측정으로 정한다(§9) |
| 전송 | frame이 끝나자마자 추론 요청 하나를 보낸다. offset 단위로 모아 보낼지는 jitter 측정 뒤 정한다(§9) |
| 시각 | FPGA 시각과의 차이를 1초마다 구한다(§5) |
| 판정 | 트랙마다 결과 31개의 평균으로 판정한다 ([02_MODEL.md](02_MODEL.md) §5) |
| deadline 확인 | 보낸 `(track_id, seq)`와 받은 결과를 대조한다. deadline까지 결과가 없으면 deadline miss로 센다 |
| 시작 설정 | 모델 image 적재, 트랙·모델 수, `offset_table`, on-chip 트랙 수 설정 |

전처리는 Host에서 한다. ATtiny급 MCU로는 트랙 하나도 처리하지 못한다. 학습 특징은 파일 단위로 정규화했으므로 실시간 정규화 방법은 따로 정해야 한다(미정).

## 3. 링크

Gigabit Ethernet(KSZ9031, RGMII), UDP를 쓴다(2026-10-13). UDP 대역폭은 약 100 MB/s로 추정한다.

필요한 대역폭은 1,024트랙 × 31.25 Hz × (요청 64 B + 결과 32 B) = 3.07 MB/s다. Ethernet 지연과 jitter는 아직 재지 않았다. simulation의 입출력 지연은 PCIe 64 B 실측 표본(H2C p50 27.2 µs)이다.

## 4. Packet 내용

little-endian이다. UDP datagram 하나에 몇 개를 담을지, 순번 확인과 재전송을 할지는 미정이다.

### 4.1 추론 요청 (64 B)

| Byte | 크기 | 이름 | 내용 |
|---:|---:|---|---|
| 0 | 1 | `magic` | `0xA5` |
| 1 | 1 | `flags` | bit0 `RESET_STATE` |
| 2 | 2 | `track_id` | 0 ~ `N_TRACKS − 1` |
| 4 | 2 | `seq` | 트랙별 순번, Host가 증가 |
| 6 | 1 | `model_id` | 0 ~ `N_MODELS − 1` |
| 7 | 1 | — | 0 |
| 8 | 4 | `t_gen_us` | frame 마지막 샘플의 수음 시각, FPGA 시각 기준 |
| 12 | 4 | — | 0 |
| 16 | 40 | `x` | mel 40개, uint8 0~127 |
| 56 | 8 | — | 0 |

트랙과 모델의 대응은 Host가 정한다. 같은 트랙에는 항상 같은 `model_id`를 쓴다. FPGA는 이 일관성을 검사하지 않는다.

### 4.2 결과 (32 B)

| Byte | 크기 | 이름 | 내용 |
|---:|---:|---|---|
| 0 | 2 | `track_id` | |
| 2 | 2 | `seq` | 요청 값 그대로 |
| 4 | 1 | `model_id` | |
| 5 | 1 | `flags` | bit0 state reset 적용, bit1 포화 발생, bit2 `LATE` |
| 6 | 2 | `batch_n` | 이 요청이 속한 batch 크기 |
| 8 | 4 | `t_gen_us` | 요청 값 그대로 |
| 12 | 4 | `t_in_us` | `ingest` 시각 |
| 16 | 4 | `t_start_us` | 연산 시작 |
| 20 | 4 | `t_done_us` | 연산 완료 |
| 24 | 2 | `out0` | layer 4 membrane potential 0, int16 |
| 26 | 2 | `out1` | layer 4 membrane potential 1, int16 |
| 28 | 4 | — | 0 |

`LATE`는 `t_done_us > t_gen_us + DEADLINE_US − MARGIN_US`일 때 켠다. 실제 deadline miss는 Host가 수신 시각으로 판정한다.

### 4.3 입력 검사

`ingest`는 아래 요청을 버리고 `REQ_DROP`을 올린다. 첫 오류는 `ERR_CODE`, `ERR_INFO`에 남긴다. 버린 요청은 결과가 없으므로 Host가 deadline miss로 센다.

| ERR_CODE | 조건 | ERR_INFO |
|---:|---|---|
| 1 | `magic` ≠ `0xA5` | 수신 순번 |
| 2 | `track_id` ≥ `N_TRACKS` | `track_id` |
| 3 | `model_id` ≥ `N_MODELS` | `track_id` |
| 4 | `x` 중 하나 > 127 | `track_id` |
| 5 | 같은 트랙의 이전 요청이 아직 끝나지 않음 | `track_id` |
| 6 | DDR3 AXI 오류 응답 | 주소 |

## 5. 시각

FPGA는 µs counter `NOW_US`와 100 MHz counter `NOW_CYC`를 둔다. Host는 이 값으로 자기 clock과의 차이를 구한다.

```text
h1 = host_now() ; f = read(NOW_US) ; h2 = host_now()
clock_diff = f − (h1 + h2) / 2
t_gen_us   = host_t_gen + clock_diff
```

`host_t_gen`은 frame 마지막 샘플을 마이크가 받은 시각이다. Host는 block이 들어온 시각과 그 block 안의 샘플 위치로 이 시각을 거꾸로 계산한다. 장치 안의 ADC·USB 지연은 이 계산에 들어가지 않으므로 loopback으로 따로 잰다(방법 미정).

Host는 1초마다 clock 차이를 다시 구한다. 오차 예산은 100 µs다. ±50 ppm clock 차이가 1초에 50 µs를 만든다. Ethernet 왕복 시간이 길거나 들쭉날쭉하면 오차가 커지므로, 왕복을 여러 번 재서 가장 짧은 것을 쓴다(방법 미정). 응답 시간과 deadline miss는 Host clock으로 잰다. `t_in_us`, `t_start_us`, `t_done_us`는 FPGA 안의 지연을 나누는 데 쓴다.

## 6. 시작과 종료

```text
1. bitstream 적재(QSPI), MIG calibration 확인
2. 모델 image(hardware/data/models_l64/models.ddr.bin)를 DDR3 MODEL_BASE에 적재   ← 경로 미정
3. N_TRACKS, N_MODELS, OFFSET_TABLE(모델 40개의 offset 번호), on-chip 트랙 수 설정
4. SOFT_RESET: entry 무효화, request table·counter 초기화
5. RUN = 1
6. 트랙마다 segment 첫 요청에 RESET_STATE
종료: 요청 중단 → IDLE = 1 대기 → RUN = 0
```

## 7. Register

32 bit register다. 64 bit 값은 LO를 읽을 때 HI를 고정한다. Ethernet으로 읽고 쓰는 방법과 새 항목의 주소는 미정이다. 유지하는 항목은 P3.9 주소를 그대로 쓴다.

| 주소 | 이름 | 접근 | 내용 |
|---|---|---|---|
| `0x0000` | `ID` | R | `0x534E_4E58` |
| `0x0004` | `VERSION` | R | 설계 버전 |
| `0x0008` | `STATUS` | R | bit0 `RUN`, bit1 `IDLE`, bit2 `MIG_CALIB`, bit3 `ERR` |
| `0x0010` | `NOW_US` | R | µs counter |
| `0x0014`, `0x0018` | `NOW_CYC_LO/HI` | R | 100 MHz counter |
| `0x0020` | `CTRL` | RW | bit0 `RUN`, bit1 `SOFT_RESET`, bit2 `CNT_CLEAR`, bit3 `ERR_CLEAR` |
| `0x0028` | `N_TRACKS` | RW | 1~1,024 |
| `0x002C` | `N_MODELS` | RW | 1~40 |
| `0x0030` | `MODEL_BASE` | RW | `0x0000_0000` |
| `0x0034` | `STATE_BASE` | RW | `0x0200_0000` |
| `0x0040` | `DEADLINE_US` | RW | 32,000 |
| `0x0044` | `MARGIN_US` | RW | `LATE` 판정 여유. 값은 Ethernet 측정 뒤 정한다 |
| 미정 | `OFFSET_TABLE[40]` | RW | 모델별 offset 번호 0~39 |
| 미정 | `N_ONCHIP` | RW | on-chip membrane potential 트랙 수 |

`RUN = 1`일 때 설정 register 쓰기는 무시한다.

counter는 모두 R이고 `CNT_CLEAR`로 0이 된다. 이름은 simulator 지표와 맞췄다.

| 주소 | 이름 | 내용 |
|---|---|---|
| `0x0200` | `REQ_IN` | 통과한 요청 |
| `0x0204` | `REQ_DROP` | 버린 요청 |
| `0x0208` | `RES_OUT` | 보낸 결과 |
| `0x020C` | `LATE` | `LATE` flag 결과 |
| `0x0210` | `BATCHES` | batch 수 |
| `0x0214` | `MODEL_LOADS` | weight 적재 수 |
| `0x0218` | `WEIGHT_BYTES_LO/HI` | weight DMA byte |
| `0x0220` | `STATE_BYTES_LO/HI` | membrane potential DMA byte |
| `0x0228` | `CMP_BUSY_LO/HI` | 연산 cycle |
| `0x0230` | `CMP_STALL_LO/HI` | 요청이 있는데 DMA를 기다린 cycle |
| `0x023C` | `MAX_PENDING` | 최대 대기 요청 수 |
| `0x0240` | `SAT_COUNT` | membrane potential 포화 횟수 |
| `0x0300` | `ERR_CODE` | 첫 오류 |
| `0x0304` | `ERR_INFO` | 첫 오류 정보 |

## 8. 미정

| 항목 | 정할 것 |
|---|---|
| UDP framing | datagram당 요청 수, 순번 확인, 손실 처리 |
| 제어 경로 | register 읽기·쓰기 packet 형식 |
| 모델 적재 | Ethernet으로 받은 image를 DDR3에 쓰는 방법 |
| Ethernet 지연·jitter | M4 측정(§9). `MARGIN_US`와 entry 수에 반영 |
| Host jitter와 보내기 방식 | M1~M3 측정(§9). 즉시 보내기와 offset 단위 모아 보내기 중 고른다 |
| Ethernet MAC 자원 | BRAM·LUT, clock 경계 |
| 실시간 특징 정규화 | 파일 단위 정규화를 대신할 방법 |

## 9. jitter 측정 계획

jitter는 같은 모델 요청의 도착 시각이 배정된 offset에서 달라지는 시간 폭이다. 환경이 정하는 값이라 재야 한다. 필요한 entry 수가 jitter에 비례한다([04_MEMORY.md](04_MEMORY.md) §4). simulation은 0.8 ms 균등분포를 가정했다.

| 원인 | 추정 크기 | Host가 줄이는 방법 |
|---|---|---|
| 오디오 장치가 데이터를 묶어 넘기는 주기 | 저지연 설정 1~4 ms, 기본 설정 10~20 ms | buffer를 줄인다. USB는 1 ms 아래로 못 가고 줄일수록 interrupt와 녹음 끊김(xrun) 위험이 는다 |
| 장치마다 다른 clock(수십 ppm) | 보정하지 않으면 계속 커진다(50 ppm이면 1시간에 180 ms) | Host clock 기준으로 frame을 자른다(§2) |
| Host mel 계산·OS jitter | 평소 1 ms 미만, 가끔 수 ms | thread 배치 |
| Ethernet 전송 | 0.1 ms 안팎(추정) | |

| 구성 | FPGA가 보는 jitter(추정) | 필요 entry |
|---|---|---|
| 다채널 오디오 장치(같은 clock), 또는 offset 단위 모아 보내기 | 0.1~0.5 ms | 2 |
| USB 마이크 여러 개, 저지연 buffer, 즉시 보내기 | 1~4 ms | 3~6 |
| USB 마이크 여러 개, 기본 buffer, 즉시 보내기 | 10~20 ms | 13~26, BRAM에 안 들어감 |

offset 단위 모아 보내기는 Host가 모델 하나의 그 주기 요청이 다 준비될 때까지, 또는 offset 시각 + 대기 D까지 기다렸다가 한꺼번에 보내는 것이다(D ≥ 오디오 buffer 주기). FPGA가 보는 jitter는 전송 jitter만 남고 응답 시간이 D만큼 는다. simulation에서는 entry 2로 jitter와 관계없이 약 6.26 KiB/추론을 유지했고 jitter 20 ms에서 최대 응답 시간은 21.8 ms였다.

| # | 측정 | 방법 | 결과 | 필요한 것 |
|---|---|---|---|---|
| M1 | 장치 사이 frame 준비 시각 jitter와 수음 → Host 지연 | 장치 N개를 동시에 stream 녹음하며 block이 Host에 들어온 시각과 샘플 위치를 기록한다. buffer 1·2·4·10 ms 비교 | buffer별 jitter와 지연의 평균·p99·최대. 지연은 외부 지연으로 deadline 32 ms에서 먼저 빠진다 | USB 마이크 2개 이상(가능하면 다채널 장치) |
| M2 | 장치 clock drift | 1시간 녹음해 장치별 sample rate와 Host clock의 차이를 구한다 | 장치별 ppm | M1과 같음 |
| M3 | Host 계산 jitter | 1,024트랙분 음성을 복제해 32 ms마다 mel을 구하며 끝나는 시각 분포를 기록한다 | p99·최대 | 아무 Linux PC |
| M4 | 전송 jitter | Host에서 UDP 64 B를 보내 지연 분포를 기록한다. 처음엔 PC 2대로, Ethernet RTL이 생기면 보드로 | p99·최대 | PC 2대, 이후 보드 |

결정 순서:

1. M3·M4를 잰다. 장치 없이 할 수 있다.
2. M1·M2를 잰다.
3. 즉시 보내기면 측정한 jitter로 entry 수를 정한다. 모아 보내기면 entry 2로 두고 D를 M1의 buffer 주기 이상으로 정한다.
4. 측정한 jitter 분포와 Ethernet 지연 표본을 simulator에 넣어 다시 확인한다([07_SIMULATION.md](07_SIMULATION.md) §6).
