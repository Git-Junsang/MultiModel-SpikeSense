# 용어

문서·코드·그림은 이 표의 표기만 쓴다. 대소문자와 띄어쓰기까지 같게 쓰고, 영문 용어는 영문 그대로 쓴다.

- 제안 기법 이름(Model-Grouped Offset Assignment, Grouping, Predicted-Next-Use (PNU) Weight Cache, PNU-Count, Membrane Storage)은 단어 첫 글자를 대문자로 쓴다. 고유명사, 약어, 이름 붙은 비교군(Host, FPGA, DDR3, Ethernet, Dysta Method, DeepRT Method, LRU, Oracle MIN)도 대문자다. 나머지는 소문자다.
- Weight cache는 PNU와 함께 쓸 때만 대문자다(PNU Cache, Predicted-Next-Use Weight Cache).
- 소문자 용어도 문장, 제목, 목록, code 주석의 첫머리에서는 첫 글자를 대문자로 쓴다. 표 칸은 이 표의 표기 그대로 쓴다. 그림은 block 이름만 첫 글자를 대문자로 쓰고 화살표·범례 글자는 소문자로 쓴다.
- code 이름, 설정 키, CSV 열은 영문 용어를 snake_case로 쓴다(`period`, `on_chip`, `ddr3_traffic_kib`, `min_deadline_margin_ms`, `model_group_delay`).
- 숫자는 88.7%, 0–0.8 ms(범위는 en dash, 단위는 끝에 한 번), J = 0.8 ms, 1,024샘플처럼 쓴다. 용량은 B·KiB·MiB·GiB, bandwidth는 MB/s·GB/s다(88.7 %, 0~0.8 ms, J=0.8 ms, 1,024 샘플, 용량의 KB·MB, GBps는 쓰지 않는다).
- 그대로 두는 이름: vendor·protocol 이름(AXI `*resp`, MIG, XDMA, Vivado timing slack), 학습 epoch, 참고문헌 제목, 다른 논문 요약에 나오는 그 논문의 용어와 단위.

## 1. Workload와 offset

| 용어                            | 뜻                                                                                                                                                                              |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 모델                            | 장비 ID마다 학습한 weight 한 벌 |
| 트랙                            | mic 하나가 보내는 장비 하나의 stream. 사용할 모델이 정해져 있으며, membrane potential과 판정 상태를 따로 가진다. 영문은 track |
| frame                           | 추론 요청 하나를 만드는 음성 구간. 1,024샘플(64 ms)에서 40차원 mel을 구한다                                                                                                     |
| hop                             | frame을 옮기는 간격. 512샘플(32 ms)                                                                                                                                             |
| frame 전송                      | mic에서 Host로 frame의 샘플이 들어오는 것. 마지막 샘플이 Host에 도착한 시각이 `t_host`다                                                                                      |
| 추론 요청                       | frame 하나의 mel을 Host가 FPGA로 보낸 것. Mic→Host는 frame 전송이고 추론 요청이라 부르지 않는다                                                                                |
| 주기 (T)                        | 32 ms. 각 트랙은 주기마다 추론 요청을 하나 낸다. 영문·code는 period이며, 주기 번호는 k |
| 판정 주기                       | 이어진 frame 31개, 992 ms. 겹치지 않는다                                                                                                                                        |
| segment                         | 이어진 frame 31개의 음성 구간. 학습·평가 데이터의 단위다                                                                                                                       |
| offset                          | 모델 m의 frame을 기준 트랙보다 얼마나 뒤에 자르는지. `O_m = m × T/M = m × 0.8 ms` (M = 40)                                                                                  |
| nominal frame 끝 시각           | offset으로 정한 frame 끝 시각 `O_m + kT`. 추론 요청의 실제 FPGA 도착은 Host 처리 지연과 링크 지연만큼 늦다 |
| Model-Grouped Offset Assignment | 같은 모델을 쓰는 트랙에 같은 offset을 주는 Host 기법. 줄여서 Offset Assignment. code `offset_assignment`                                                                      |
| offset 배정                     | 제안이 아닌 일반 행위(무작위 offset 배정 등)                                                                                                                                    |
| unaligned                       | Offset Assignment가 없는 비교 조건. 시나리오의 offset(트랙마다 무작위 또는 동시 시작)을 그대로 쓴다                                                                             |
| global alignment                | 모든 트랙에 같은 nominal offset을 주는 비교 조건. 제안 기법의 구성요소가 아니다. code `global_alignment`                                                                      |
| 시나리오                        | uniform(균등 배정), skewed(편중 배정), synchronized(동시 시작), skewed_synchronized(동시 시작 + 편중 배정), intermittent(간헐적 추론 요청), fluctuating(운영 중 트랙 구성 변경) |

## 2. FPGA

| 용어                                  | 뜻                                                                                                                                                   |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| batch                                 | weight 적재 한 번으로 이어서 처리하는 같은 모델의 추론 요청들. 이미 도착한 추론 요청만 묶는다                                                        |
| Grouping                              | 가장 오래 기다린 추론 요청의 모델을 고르고, 그때 queue에 있는 그 모델 추론 요청을 batch 하나로 묶는 scheduler. FPGA block 이름은 Grouping scheduler  |
| entry                                 | BRAM에서 모델 한 벌의 weight와 누설 계수·threshold를 두는 자리. 개수는 entry 수                                                                     |
| prefetch                              | 연산하는 동안 다음 batch의 모델 전체를 빈 entry로 적재하는 것. layer나 slice로 나누지 않는다                                                         |
| 적재 / 재적재                         | 적재는 DDR3에서 모델 한 벌을 entry로 읽는 것. 재적재는 같은 모델·주기에서 첫 적재 뒤에 다시 읽는 것. 여러 번 재적재하면 반복 적재 |
| 단일 적재                             | 모델·주기마다 한 번만 적재한다는 가정                                                                                                               |
| cache hit / miss                      | 처리할 모델이 entry에 있음 / 없어서 DDR3에서 적재함                                                                                                  |
| hit rate                              | batch 중 cache hit인 batch의 비율                                                                                                                    |
| weight cache                          | 모델 weight를 entry에 두고 교체하는 FPGA block                                                                                                       |
| Predicted-Next-Use (PNU) Weight Cache | 다음 사용 예측이 가장 늦은 모델을 내보내는 weight cache. 약어는 처음 한 번 붙이고 뒤에는 PNU Cache라 쓴다. 절 제목은 Predicted-Next-Use Weight Cache |
| next-use predictor                    | PNU Cache에서 다음 사용 시각을 예측하는 block                                                                                                        |
| PNU-Count                             | Host가 추론 요청 packet에 싣는 이번 주기 예상 추론 요청 수까지 쓰는 PNU. 제안 정책. code `pnu_count`                                               |
| PNU-Timeout                           | 예상 추론 요청 수 없이, timeout 안에서는 추론 요청이 남았다고 보는 PNU. 비교용                                                                       |
| offset-only                           | nominal offset과 지금 queue만 쓰는 교체 정책. 비교용                                                                                                 |
| LRU                                   | 가장 오래 쓰지 않은 모델을 내보내는 교체 정책. 비교용                                                                                                |
| Oracle MIN                            | 실제 미래 도착 시각을 아는 교체 정책. 구현할 수 없는 비교 기준. 처음 소개할 때는 Oracle Belady MIN. code `oracle_min`                              |
| Belady 하한                           | 실행이 만든 고정 batch 순서에 offline Belady MIN을 적용한 적재 수 하한                                                                               |
| victim                                | 교체로 내보낼 entry의 모델                                                                                                                           |
| Membrane Storage                      | membrane potential을 16 bit로 연산하고 12 bit로 포화해 저장하는 방식(12 bit Membrane Storage). On-chip 트랙의 state는 membrane bank에, 나머지 트랙의 state는 DDR3에 둔다 |
| membrane bank                         | on-chip 트랙의 membrane potential을 두는 BRAM                                                                                                        |
| membrane potential                    | 같은 트랙의 다음 추론으로 이어지는 뉴런 값. 줄여서 potential. Membrane potential을 뜻하는 상태는 state라 쓴다 |
| compute array                         | 64-lane output-stationary 연산 block                                                                                                                 |
| request table                         | 도착한 추론 요청을 모델별로 두는 표                                                                                                                  |
| control overhead                      | 추론 하나에서 compute array가 weight word를 누산하지 않는 cycle. Layer 경계에서 앞 layer의 PLIF를 기다리는 시간과 pipeline을 채우고 비우는 시간 |
| tile                                  | BRAM 단위. RAMB36 하나가 1 tile, RAMB18 하나가 0.5 tile                                                                                              |

## 3. 시간과 지연

| 용어                          | 뜻                                                                                                                                               |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| response time                 | `t_recv − t_host`. Frame 마지막 샘플의 Host 도착부터 Host 결과 수신까지                                                                       |
| 준비 완료 뒤 response time    | `t_recv − t_ready`. 즉시 송신이면 입력 링크, FPGA 처리, 결과 링크                                                                             |
| 송신 뒤 response time         | `t_recv − t_send`                                                                                                                             |
| Host 처리 지연                | `t_ready − t_host`. 모델 그룹 지연과 추론 요청별 지연의 합. 영문 Host processing delay                                                        |
| 모델 그룹                     | Host가 함께 계산하는 같은 모델·같은 주기의 추론 요청들. FPGA가 이미 도착한 추론 요청으로 구성하는 batch와 구분한다 |
| 모델 그룹 지연 G(m, k)        | 모델 그룹 전체에 공통인 Host 처리 지연. 주기마다 바뀐다. 줄여 쓰지 않는다. 영문·그림 model-group delay                                          |
| 추론 요청별 지연 j(i, k)      | 모델 그룹 안에서 추론 요청마다 다른 Host 처리 지연. Simulation은 `Uniform(0, J)`. 영문 per-request delay                                       |
| jitter (J)                    | 같은 모델·같은 주기 추론 요청의 Host 처리 완료 시각이 퍼지는 폭. Simulation에서는 j(i, k)의 상한인 지연 상한 J를 뜻한다. 모델 그룹 지연과 구분한다 |
| 링크 지연                     | Host와 FPGA 사이 전송 지연(Host-FPGA 통신). 입력 `t_arr − t_send`, 결과 `t_recv − t_done`                                                  |
| mic–Host 지연                | mic에서 Host까지 frame을 전송하는 데 걸리는 지연. Response time에 넣지 않고 따로 측정한다 |
| 즉시 송신                     | Host가 준비된 추론 요청을 바로 보낸다. 기본 구성                                                                                                 |
| 즉시 입출력                   | 즉시 송신에 더해, FPGA도 연산이 끝나자마자 결과를 보내는 것                                                                                      |
| 모아 보내기                   | Host가 같은 모델·주기 추론 요청을 모았다가 한꺼번에 보낸다. 비교 구성                                                                           |
| deadline                      | `t_host + 32 ms`. 모든 입력에서 지키는 것을 보장하는 기준은 hard deadline                                                                      |
| deadline miss                 | response time이 32 ms를 넘었거나 결과가 없는 추론 요청. Drop을 포함한다. Cache miss와 다르다                                                     |
| drop                          | 같은 트랙의 이전 추론 요청이 FPGA 연산을 마치기 전에 도착해 버린 추론 요청. 처음 설명할 때만 폐기(drop)                                          |
| deadline 여유                 | 32 ms − response time. 최솟값을 최소 deadline 여유라 부른다. code `min_deadline_margin_ms`                                                    |
| 관측 최대                     | 결과가 나온 추론 요청에서 측정한 최댓값. 보장된 상한이 아니다 |
| 조건부 response time (R_cond) | Host·링크 지연의 측정 최대와 단일 적재 가정으로 계산한 response time                                                                            |
| hard worst case               | 명시한 운용 제약 안에서 가능한 모든 입력과 도착 과정 중 가장 긴 response time(worst case response time). 아직 구하지 않았다                      |

## 4. 지표

| 용어               | 뜻                                                                                                                                                                                             |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DDR3 traffic       | 측정 구간의 weight와 membrane potential 읽기·쓰기 byte ÷ 완료한 추론 수. KiB/추론. CSV `ddr3_traffic_kib`                                                                                  |
| DDR3 bandwidth     | 단위 시간당 DDR3 전송 byte. 단위는 MB/s·GB/s. 측정 구간의 사용량은 사용 bandwidth(`ddr3_used_bandwidth_mbps`), 읽기에 사용할 수 있는 상한은 DDR3 읽기 bandwidth(보드 실측 순차 읽기 3.015 GB/s, `ddr3_bandwidth_mbps`) |
| 파일 단위 평균 AUC | 모델마다 test 파일 단위로 구한 AUC의 평균                                                                                                                                                      |

Frame 전송과 DDR3 전송은 추론 요청이라 부르지 않는다.

## 5. 쓰지 않는 표기

| 쓰는 표기                                          | 쓰지 않는 표기                                                                                                    |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| response time                                      | 응답 시간, 응답 지연, 지표 이름으로 쓴 latency                                                                    |
| DDR3 traffic                                       | DDR3 전송량, 트래픽, 읽기량, DDR traffic                                                                          |
| bandwidth                                          | 대역폭, 전송률                                                                                                    |
| DDR3                                               | DRAM, DDR 단독                                                                                                    |
| Model-Grouped Offset Assignment, Offset Assignment | Model-grouped, 제안을 뜻하는 offset 배정, slot(offset을 뜻할 때. DDR3의 모델 slot은 그대로), 정렬 slot, 위상 정렬 |
| Grouping                                           | grouping, 그룹핑                                                                                                  |
| weight cache, PNU Cache                            | PNU 없이 쓴 Weight Cache, PNU cache, 캐시                                                                         |
| PNU-Count, PNU-Timeout                             | PNU-count, PNU-timeout                                                                                            |
| Membrane Storage                                   | membrane storage                                                                                                  |
| membrane potential                                 | 막전위                                                                                                            |
| compute array                                      | Compute-array, 연산기, 연산부                                                                                     |
| 모델 그룹 지연                                     | 모델 묶음 지연, 묶음 지연, 그룹 지연, 묶음 공통 지연, group delay                                                 |
| 추론 요청별 지연                                   | 요청별 지연                                                                                                       |
| Host 처리 지연                                     | Host 지연                                                                                                         |
| 추론 요청                                          | 단독으로 쓴 요청(요청서, 동사 '요청하다', 제어 packet의 요청·응답은 그대로)                                      |
| deadline, deadline miss, hard deadline             | 마감, 마감 위반, 데드라인, 하드 데드라인                                                                          |
| deadline 여유                                      | slack(Vivado timing slack은 그대로)                                                                               |
| batch                                              | 묶음(batch를 뜻할 때)                                                                                             |
| Dysta Method, DeepRT Method                        | Dysta식, DeepRT식, 우리 비교군을 뜻하는 Dysta·DeepRT 단독                                                        |
| worst case                                         | 최악(response time을 말할 때)                                                                                     |
| 주기, period                                       | epoch(32 ms 주기를 뜻할 때. 학습 epoch는 그대로)                                                                  |
| 즉시 송신                                          | 즉시 보내기, 즉시 전송                                                                                            |
| 준비 완료 뒤 response time                         | 준비 완료 뒤 시간, Host 처리 지연을 뺀 시간                                                                       |
| mic                                                | 마이크                                                                                                            |
| on-chip                                            | onchip, 온칩                                                                                                      |
| 장비                                               | 기계(장비 종류·ID를 뜻할 때)                                                                                     |
| 데이터, 메모리                                     | 한국어 문장의 data, memory                                                                                        |
| state                                              | membrane potential을 뜻하는 상태                                                                                  |
| 보드                                               | 한국어 문장의 board(폴더 이름 `board_test`는 그대로)                                                            |
| out-of-context, 배치·배선                         | OOC, P&R                                                                                                          |
| 영문 용어 그대로(simulation, scheduler, weight, entry, queue, offset, frame, jitter, timestep, seed, thread, hardware, register, pipeline, testbench) | 시뮬레이션, 스케줄러, 가중치, 엔트리, 큐, 오프셋, 프레임, 지터, 타임스텝, 시드, 스레드, 하드웨어, 레지스터, 파이프라인, 테스트벤치 같은 음차·번역 |
| Host                                               | host, 호스트                                                                                                      |
| entry 수                                           | entry 개수                                                                                                        |
| 적재, 재적재                                       | 로드, 로딩(weight 적재를 뜻할 때)                                                                                 |
| 모델 그룹                                          | 모델 묶음                                                                                                         |
| 링크 지연, Host-FPGA 통신                          | Host-FPGA 사이를 뜻하는 통신 지연·전송 지연, Host↔FPGA                                                           |
| mic–Host 지연(en dash)                             | mic-Host 지연, 마이크–Host 지연                                                                                   |
| nominal frame 끝 시각                              | nominal 생성 시각                                                                                                 |
| trade-off                                          | 트레이드오프, 맞바꿈                                                                                              |
| 묶음 처리, weight 공유(기존 원리를 말할 때)        | 한국어 문장의 batching, weight sharing                                                                            |
| 전처리, 특징 추출, 양자화, 수음                    | 한국어 문장의 preprocessing, feature extraction, quantization, mic 수음을 뜻하는 녹음                             |
| 메타데이터, 영문 track(s)                          | 한국어 문장의 metadata, 영문 sensor stream(s)                                                                     |
| Gigabit Ethernet, Ethernet                         | 1 GbE, 이더넷, 문장 속 ethernet                                                                                   |
| 라즈베리파이 5, Artix 7, Host runtime              | RPi, RPi5, Artix-7, 런타임                                                                                        |
| INT8, FP32, layer-wise symmetric INT8, focal loss  | 문장 속 int8, layer별 대칭, 본문의 Focal Loss                                                                     |
| 균등분포, 지도학습                                 | 균등 분포, supervised                                                                                             |
| LazyBatching, Grenier 등(저자 인용)                | Lazy Batching, Grenier 외                                                                                         |
| hop                                                | hop을 풀어 쓴 "구간을 32 ms씩 앞으로 옮긴다"                                                                      |

## 6. 옛 보고서에만 나오는 이름

| 이름                          | 뜻                                                                                                                                |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| offset-order weight cache     | P3.13~P3.24의 교체 정책. 트랙마다 실제 지연을 알고 있어 미래 정보가 섞였다. P3.25에서 버렸다                                      |
| 외부 지연                     | P3.22까지 쓴 시간 기준(mic 수음부터)에서 FPGA 밖 지연 전체. 지금은 mic–Host 지연, Host 처리 지연, 링크 지연으로 나눈다           |
| 시나리오 키 U·K·S·SK·I·R | 2026-10-26 전 code·CSV의 시나리오 이름. uniform·skewed·synchronized·skewed_synchronized·intermittent·fluctuating으로 바꿨다 |
