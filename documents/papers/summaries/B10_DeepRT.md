# B10: DeepRT

원문: `B10_DeepRT_SEC2021.pdf`
Zhe Yang, Klara Nahrstedt, Hongpeng Guo, Qian Zhou, SEC 2021, DOI 확인 못 함(원문은 arXiv:2105.01803v1)
읽은 범위: 원문 전체

## 한 줄 요약

같은 모델·같은 입력 크기의 frame을 시간 window 동안 모아 batch 하나로 묶고 batch를 GPU에서 EDF 순서로 하나씩 실행한다. 비교한 묶음 처리 방식(AIMD, Triton의 batch·BATCH-Delay)보다 deadline miss가 적었다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | GPU 하나를 여러 video stream이 나눠 쓸 때 묶음 처리로 처리량을 올리면서 frame마다 deadline을 지키는 것 |
| 방법 | DisBatcher는 category(같은 모델·같은 입력 크기)마다 길이가 같은 시간 window를 둔다. Window가 끝나면 그동안 도착한 frame을 job instance 하나로 묶는다(§3.2, Fig. 3) |
| 방법 | window 길이는 그 category에서 가장 작은 상대 deadline의 절반이다(Eq. 2). Job instance의 deadline은 다음 window 끝이다. Job instance가 이를 지키면 frame도 deadline을 지킨다(Theorem 1) |
| 방법 | job instance는 비선점·non-idling EDF로 하나씩 실행한다(§3.3, §4.3). GPU가 놀면 window가 끝나기 전에 묶어 보낸다(조기 실행, §4.3) |
| 방법 | admission control은 utilization 검사(Phase 1, Eq. 3–4)와 EDF imitator(Phase 2, Algorithm 1)로 새 stream을 받을지 정한다(§4.2). Adaptation Module은 실행 시간이 profiling 값을 넘으면 그 category의 해상도를 낮춘다(§4.4) |
| 가정·조건 | GPU 하나(RTX 2080 desktop, Jetson TX2). Stream마다 모델 7개 중 하나를 무작위로 고른다. Frame은 주기마다 도착하고 상대 deadline은 주기와 달라도 된다. Soft real-time이라 가끔의 deadline miss를 허용한다. Weight 적재·교체 비용은 다루지 않는다 |

## 결론

- 합성 trace 6개(desktop 3개, Jetson TX2 3개) 모두에서 deadline miss rate가 가장 낮았다. 비교 대상은 AIMD(Clipper·MArk 방식)와 Triton의 batch·BATCH-Delay다(Fig. 4, §6.2). 주기·상대 deadline 평균이 50 ms인 trace에서도 miss rate는 5%였다
- 묶음 처리가 없는 Sequential EDF보다 모든 trace에서 처리량이 같거나 높았다. 상대 deadline이 긴 trace에서 차이가 컸다(Fig. 7, §6.3)
- EDF imitator의 latency 예측 오차는 상대 deadline 평균 300 ms trace에서 최대 250 ms였다(Fig. 8). Admission control 실행 시간은 Jetson TX2·frame 10⁵개에서 5.9 s였고 나머지는 1 s 아래였다(Fig. 9)
- 평가 방식: 실측(GeForce RTX 2080 desktop, Jetson TX2). Stream 도착 간격은 Twitter trace로, 주기와 상대 deadline은 Gamma 분포로 합성했다(§6.2)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 모델 추론 요청을 batch로 묶고 batch를 선점 없이 하나씩 실행한다 | DeepRT는 window가 끝날 때까지 기다렸다가 묶는다. Grouping은 이미 도착한 추론 요청만 묶고 기다리지 않는다 | [실험] simulation(Xeon에서 잰 모델 그룹 지연을 넣음, jitter J = 0.8 ms, entry 4)에서 DDR3 traffic은 제안 6.38, DeepRT Method 11.35 KiB/추론(−44%)이다. 최대 response time은 제안 9.58, DeepRT Method 23.80 ms다. J = 3.2 ms에서는 DeepRT Method의 DDR3 traffic이 더 적다(window 선택에 따라 달라짐). Host 처리 지연은 모델당 25–26트랙 배정에서 잰 값을 모든 시나리오에 넣었고 보드 측정은 없다 |
| 주기 입력과 추론 요청별 deadline을 다룬다 | DeepRT는 frame 도착 시각을 바꾸지 않는다. 이 연구는 Host가 모델별 frame offset을 정해 같은 모델 추론 요청이 함께 생기게 한다 | [구조] window 길이를 정하지 않아도 같은 모델 추론 요청이 함께 도착해 batch가 생긴다 |
| | DeepRT는 모델 weight 적재를 다루지 않는다. 이 연구는 모델 40개 weight 4.97 MiB가 BRAM보다 커서 weight 전송이 병목이다 | [구조] weight가 BRAM보다 클 때를 다룬다. PNU-Count가 다음 사용 시각을 예측해 가장 늦게 쓸 모델을 내보낸다 |
| | DeepRT는 admission control과 Theorem 1로 받은 stream의 deadline을 보이려 한다. 이 연구는 32 ms hard deadline 보장을 주장하지 않는다 | |

## 인용할 때

- 이 논문이 먼저 한 것: 같은 모델 frame을 시간 window로 모아 batch로 묶고 EDF로 비선점 실행하는 것, window를 가장 작은 상대 deadline의 절반으로 두는 규칙. 같은 모델의 묶음 처리·weight 공유와 기다려 묶기 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 근거 위치: window 규칙 §3.2(Eq. 2, Theorem 1, Fig. 3), EDF §3.3·§4.3, 조기 실행 §4.3 끝 문단, admission control §4.2(Eq. 3–4, Algorithm 1), 해상도 조절 §4.4, 결과 §6.2–6.4(Table 2, Fig. 4·7–9)
- 주의: 원문의 request는 frame이 이어지는 video 하나라 이 연구의 트랙에 가깝다. 원문의 frame은 추론 요청에 가깝다
- 주의: latency 보장은 admission control을 통과한 stream에만 해당한다. Profiling한 worst case 실행 시간이 정확하다는 가정도 붙는다(§4.2). Overrun 때문에 deadline miss가 남는다(§6.2). Fig. 4는 DeepRT가 받은 stream만 다른 방법에 넣고 Adaptation Module을 끈 비교다
- 옮긴 방식: DeepRT Method는 DisBatcher의 window와 EDF만 옮겼고 admission control과 해상도 조절은 넣지 않았다. Window 길이와 조기 실행 여부는 조정으로 골랐다([08_EVALUATION §3](../../design_references/08_EVALUATION.md#3-비교-규칙)). 원문은 category마다 timer를 따로 둔다고만 적었다. DeepRT Method는 모델마다 window 시작 시각을 다르게 둔다([simulation_engine §6.2](../../design_references/simulation_engine.md#62-scheduler))
