# B36: ARISE

원문: `B36_ARISE_MobiSys2024.pdf`
Z. Jonny Kong, Qiang Xu, Y. Charlie Hu(Purdue University), "ARISE: High-Capacity AR Offloading Inference Serving via Proactive Scheduling", ACM MobiSys 2024, pp. 451–464, DOI 10.1145/3643832.3661894
읽은 범위: 원문 전체

## 한 줄 요약

GPU server의 proactive scheduler가 AR client마다 offloading 주기와 보낼 frame(시각)을 정해 같은 batch에 들 request가 batch 시작 직전에 함께 도착하게 한다. 정확도 SLA를 지키면서 server 하나가 받는 client 수가 비교 방식보다 1.7–6.9배 많았다(초록, §6.4, Fig. 13).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 일반 inference serving은 request가 서로 독립이고 도착을 제어할 수 없다고 보아 batch를 기회가 생길 때만 만든다(§1.2, §3.1). AR client는 offloading 주기(L)와 E2E offloading latency(k)가 모든 frame의 정확도를 정한다(local tracking, §2) |
| 방법 | 조절 knob은 client별 offloading 주기, client별 offloading 시각(어느 frame을 보낼지, 예: client 1은 frame 0·3·6, client 2는 1·4·7), server batch 크기 세 가지다(§3.1, Fig. 3). Fig. 4의 예에서 도착 시각만 옮기면 client 4개, 주기까지 바꾸면 5개를 모두 받는다 |
| 방법 | 1단계: client마다 정확도 SLA를 지키는 offloading 주기와 batch 크기를 닫힌 식으로 구한다(§4.4.1). 2단계: 앞으로 올 request를 도착 순서대로 batch에 채운다. Batch 크기는 그 안의 모든 client가 견디는 최대값이다. 그 batch의 request 도착 시각을 모두 batch 시작 시각 t로 바꾸고 frame ID를 다시 고른다. 다음 batch는 t에 추론 시간을 더한 시각에 시작한다(§4.4.2, Alg. 1, Fig. 10) |
| 방법 | 고친 schedule로 정확도를 다시 계산해 client를 더하거나 뺀다(verify). 끝난 schedule은 client에 보낸다(apply). Scheduler는 200 ms마다 앞으로 약 1 s의 schedule을 client 상태(정확도 추정, 최근 도착 시각)로 다시 만든다(§4.2, Fig. 6). 늦은 request를 위해 batch마다 추론 시간의 10%를 여유로 둔다. 도착 시각은 최근 도착의 regression으로 예측한다(§4.4.2) |
| 가정·조건 | server 하나는 AR task(모델) 하나만 처리한다(§1). Depth estimation(DenseDepth)과 object detection(ByteTrack)은 따로 실험했다(§6.2). Client는 60 FPS이고 보내지 않은 frame은 local tracking으로 채운다(§2.1, §4.2). 모델 weight 적재는 다루지 않는다 |
| 가정·조건 | emulation: NVIDIA A40 server, Python으로 만든 emulated client, tc로 5G mmWave(uplink 152 ± 6 Mbps, RTT 14 ± 2 ms)와 LTE 조건을 흉내 냈다. Client는 평균 초당 10개 Poisson 도착, 실험은 10분이다(§6.1). Testbed: phone 10대(Pixel 5 7대, Pixel 2 3대), 802.11ac AP, 1 Gbps 링크, 그 위에 5G mmWave 조건을 흉내 냈고 GPU clock은 1200 MHz로 낮췄다(§6.1, §6.5) |

## 결론

- Emulation, depth estimation, 5G mmWave: 정확도 SLA 0.02·0.04·0.06과 [0.02, 0.06]에서 ARISE는 모든 비교 방식(Static, Clipper-like, Chameleon-like, ARISE-α)보다 client를 1.7–6.9배 더 받았다. Reactive판인 ARISE-α보다 1.7–3.9배였다(§6.4, Fig. 13). LTE에서는 2.5–5.6배였다(Fig. 16)
- Testbed(phone 10대, SLA 0.02)에서 평균 client 7.6개, 비교 방식의 2.6–3.8배였다(§6.5, Fig. 17). Object detection(SLA 0.2, emulation)은 평균 client 9.6개, 1.9–2.1배였다(§6.7, Fig. 22)
- 도착을 맞추면 GPU가 덜 쉰다. GPU idle은 ARISE-α 24.7%, ARISE 8.8%였다(Fig. 18). Schedule보다 늦게 시작한 batch는 1.6%였다(Fig. 20). Scheduler 한 번에 0.8 ms가 걸렸다(§6.5)
- 평가 방식: emulation(client와 network는 흉내 내고 GPU 추론은 A40에서 실행)과 실측 testbed(phone 10대, network 조건은 emulation)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 주기 입력을 보내는 시각을 정해 같은 batch에 들 입력이 함께 도착하게 하고 batch끼리는 처리 시간만큼 벌린다(Alg. 1 5–10행, §4.5) | ARISE의 batch는 같은 task를 처리하는 server 하나 안에서 client를 묶은 것이다. 모델은 server당 하나라 모델끼리 weight를 바꾸는 문제가 없다. 이 연구는 모델 40개가 FPGA 하나를 나눠 쓰고 같은 모델 트랙에 같은 offset을 준다 | [구조] offset을 모델 기준으로 정해 같은 모델 추론 요청이 함께 생기고 모델끼리는 0.8 ms씩 벌어진다. Grouping과 PNU Cache가 이 순서를 이용해 weight 적재를 줄인다 |
| | ARISE는 200 ms마다 client 상태로 schedule을 다시 만들어 client에 보낸다. Client마다 offloading 주기도 바꾸고 frame을 건너뛴다. 이 연구는 offset이 `O_m = m × 0.8 ms`로 고정이고 feedback이 없으며 트랙마다 32 ms마다 추론 요청 하나를 반드시 처리한다 | [구조] 정확도 추정, schedule 전송, client 쪽 schedule 수신이 없다. Mic와 Host 사이 제어 경로도 필요 없다 |
| 함께 도착한 입력을 batch로 처리한다 | ARISE는 늦은 request를 위해 batch마다 추론 시간의 10%를 여유로 두고 예정한 request가 다 오면 바로 시작한다(§4.4.2, §6.6). 이 연구의 Grouping은 이미 도착한 같은 모델 추론 요청만 묶고 기다리지 않는다. 늦은 추론 요청은 다음 batch로 간다 | [구조] batch를 채우려고 기다리는 시간이 response time에 더해지지 않는다 |

## 인용할 때

- 이 논문이 먼저 한 것: server scheduler가 client마다 offloading 시각과 주기를 정해 같은 batch의 request가 batch 시작 직전에 함께 도착하게 하는 것(proactive scheduling, §4.4.2). 같은 시각 도착으로 batch 만들기 자체는 신규성으로 주장하지 않는다
- 우리가 주장할 수 있는 범위: 모델을 기준으로 offset을 설계해 weight 재사용을 만드는 것, offset이 고정이고 feedback이 없는 것, 기다리지 않는 Grouping과 Predicted-Next-Use (PNU) Weight Cache를 결합한 것
- 근거 위치: 조절 knob §3.1·Fig. 3–4, workflow §4.2·Fig. 6, packing·coordination §4.4.2·Alg. 1·Fig. 10, 도착 맞춤 §4.5, 실험 조건 §6.1, 결과 Fig. 13·16–18·20·22
- 주의: 1.7–6.9배는 동시에 받은 client 수의 비이고 지연 지표가 아니다. 범위의 끝은 비교 방식과 SLA 조합마다 다르다. 서론의 "up to 5.2x and 6.9x"는 Clipper-like와 Chameleon-like 각각의 최대다(§1.2). Static 등 비교 방식의 고정값은 offline 탐색으로 정한 강한 기준이라고 적었다(§6.3)
- 주의: client는 frame을 건너뛰고 local tracking으로 채우므로 모든 frame을 deadline 안에 처리하는 문제가 아니다. 공동 1저자 Qiang Xu는 EdgeSync(B29)의 저자이기도 하다. 두 논문은 서로 인용하지 않는다
