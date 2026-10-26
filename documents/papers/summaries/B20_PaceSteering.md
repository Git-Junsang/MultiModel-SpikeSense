# B20: Pace Steering

원문: `B20_PaceSteering_FMEC2024.pdf`
Antero Vainio, Sasu Tarkoma, "Flow Control Solution to Avoid Bottlenecks in Edge Computing for Video Analytics", FMEC 2024, DOI 10.1109/FMEC62297.2024.10710217
읽은 범위: 원문 전체(University of Helsinki 저장소의 accepted manuscript)

## 한 줄 요약

Edge server가 앞 frame의 queueing time만큼 다음 frame을 늦추라고 camera client에 알려 frame이 server가 빌 때 도착하게 한다(Pace Steering, PS). 10 FPS stream을 frame 95%가 latency 요구 안에 들도록 80개까지 처리해 PS가 없을 때의 두 배였다(초록, Fig. 4b).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 여러 camera stream이 edge server 하나와 Wi-Fi 링크를 나눠 쓰면 frame이 server queue에서 기다리고 링크 부하가 한꺼번에 몰린다(§I) |
| 방법 | server가 다음 frame을 늦출 시간(synchronization delay)을 client에 상대값으로 알리는 피드백 방식이다. 시계 동기화가 필요 없다(§III-A, Eq. 4). 앞 frame의 queueing time q를 그대로 쓰면 다음 frame이 앞 task가 끝날 때 도착한다(§III-B, Eq. 5–6, Fig. 2) |
| 방법 | 연결 수 N_c가 Eq. 10의 상한 `Δt_cs / Δt`를 넘으면 batching을 쓴다. Batch 안의 각 frame을 batch index i_b로 다음 task들에 나눠 `s(i, j + 1) = i_b · Δt + q(i, j) mod Δt`(Eq. 11)만큼 늦춘다. 그러면 client가 같은 크기의 mini batch로 나뉜다(§III-C). Δt는 task 처리 시간이다 |
| 가정·조건 | 평가 모델은 VGG-11 하나다(CIFAR-10, §IV-A). Server는 한 번에 task 하나를 처리한다(§III). Client마다 frame rate가 일정하고 task 처리 시간 편차가 작다(§III-B). Embedded GPU edge server와 Wi-Fi 6 환경이다(평균 144.4 Mbit/s, §IV-B). 지표는 frame 95%가 frame rate로 정한 latency 요구 안에 드는지다(초록, Fig. 4) |

## 결론

- Batching 없이 5 FPS: frame 95%가 latency 요구를 지키는 최대 연결 수가 11에서 13으로 늘었다(Fig. 4a). Flow control이 없으면 client들이 거의 같은 시각에 보내 tail latency가 생겼다. PS에서는 보내는 시각이 서로 달라졌다(Fig. 5)
- Batching과 10 FPS: 처리할 수 있는 연결이 40에서 80으로 늘었다(Fig. 4b). Batching을 쓰면 결과 전송(TX)이 E2E latency를 지배했다. PS는 무선 링크 병목을 줄였다(Fig. 7). PS에서 batch 크기 분포의 분산과 평균이 더 작았다(Fig. 8)
- 평가 방식: 실측. Embedded GPU edge server와 Wi-Fi 6 환경이고 client는 노트북의 Python asyncio coroutine이다(§IV-B). 비교 대상은 flow control이 없는 FCFS·B-FCFS뿐이다(§IV-A)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 일정한 주기로 생기는 입력을 보내는 시각을 정해 처리 장치 앞 대기를 줄이고 함께 처리할 입력이 같은 시각에 도착하게 한다 | PS는 모델 하나에서 client를 같은 크기 mini batch로 나눈다. 이 연구는 같은 모델 트랙에 같은 offset을 주고 모델끼리 0.8 ms씩 벌려 모델 40개의 weight 재사용 기회를 만든다 | [구조] offset을 모델 단위로 주고 PNU-Count와 함께 쓴다. PS는 여러 모델로 넓히는 방법을 범위 밖으로 남겼다(§III) |
| | PS는 server가 잰 queueing time을 client에 돌려주는 피드백 방식이고 Wi-Fi 링크 부하도 다룬다. 이 연구의 offset은 `O_m = m × 0.8 ms`로 고정이고 Host가 frame을 자르는 시각만 정한다. 링크는 Gigabit Ethernet UDP이고 즉시 송신이다 | [구조] FPGA에서 Host로 돌려주는 제어 신호가 필요 없다 |

## 인용할 때

- 이 논문이 먼저 한 것: 일정한 frame rate의 stream이 보내는 시각을 server 상태로 조절해 server queueing을 없애는 것(flow control). Batch index로 client를 나눠 같은 mini batch의 frame이 함께 도착하게 하는 것(Eq. 11). 주기 작업의 생성 시각에 간격 두기 자체와 같은 시각 도착으로 batch 만들기 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 근거 위치: 한 번에 task 하나를 처리한다는 가정과 "같은 server가 여러 모델을 처리하는 경우는 모델마다 시간 window를 배정하거나 pipeline parallelism으로 넓힐 수 있으나 범위 밖"이라는 문장은 §III 첫머리(§III-A 앞 문단, PDF 4쪽)에 있다. §V(PDF 8쪽)는 여러 모델을 앞으로의 과제로 적었다. 식은 §III-A–C(Eq. 4–11, Fig. 2), 결과는 §IV-D(Fig. 4–8)
- 주의: batching이 없을 때 PS는 stream이 보내는 시각을 서로 다르게 만든다(Fig. 5d). Batching이 있을 때는 같은 mini batch에 든 client의 도착을 맞춘다. 두 동작을 나눠 인용한다
- 주의: §III의 모델별 시간 window 문장은 이 연구의 모델별 offset과 가깝게 읽힌다. 원문에는 그 방법과 평가가 없다. Eq. 11에서 i_b의 범위와 mod가 걸리는 범위도 원문에 정의가 없다
- 주의: 논문 제목에는 Pace Steering이 없다. 80개·두 배는 10 FPS·batching·frame 95% 기준이다. Simulation 비교군에 없다
