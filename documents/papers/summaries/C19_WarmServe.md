# C19: WarmServe

원문: `C19_WarmServe_ICML2026.pdf`
Chiheng Lou, Sheng Qi, Rui Kang, Yong Zhang, Chen Sun, Pengcheng Wang, Xuanzhe Liu, Xin Jin, ICML 2026(원문 표기: Proceedings of the 43rd ICML, Seoul, PMLR 306), arXiv:2512.09472v2(2026-05-21). 원문에 DOI가 없고 PMLR 게재판은 확인하지 못했다
읽은 범위: 원문 전체(부록 A–D 포함)

## 한 줄 요약

LLM 부하의 주기성으로 5분 window마다 모델별 평균·최대 부하를 예측하고 부하가 오기 전에 여러 LLM의 weight를 놀고 있는 GPU에 함께 올려 두는(one-for-many GPU prewarming) multi-LLM serving system이다. GPU 16개 실측에서 P99 TTFT가 SLLM-GPU보다 최대 50.79배 짧았고 MuxServe보다 추론 요청을 최대 2.5배 더 처리했다(§4.3).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | autoscaling은 burst가 온 뒤에 instance를 만들어 cold start가 길다. GPU sharing은 모델마다 KV cache가 줄어 throughput이 떨어진다. 저자는 둘 다 앞으로의 부하를 모르기 때문이라고 본다(§1, §2.1) |
| 방법 | 예측: 시간을 t분 window로 나누고 모델마다 다음 window의 평균·최대 동시 추론 요청 수를 CSP로 예측한다. 지난 D일(보통 7) 같은 window의 평균에 최근 N개(보통 10) window의 오차를 가중 평균해 더한다(§3.1, Eq. 1–3). 기본 window는 5분이다(§4.4) |
| 방법 | 배치: 모델마다 replica를 최대 ⌈L_P/B⌉ − K개 prewarm한다. 점수는 예측 부하와 active instance 수의 차이, weight 전체를 GPU에 올리는 시간(T_c)으로 정하고 burst용 replica에는 (L_P − L_A)/L_A를 더 곱한다. 점수 순으로 GPU group에 놓고 두 모델의 GPU 집합이 일부만 겹치지 않게 한다(§3.2, Algorithm 1, 부록 B의 Eq. 5–8·Fig. 13) |
| 방법 | 전환: prewarm한 모델에 burst가 오면 그 GPU의 다른 prewarm weight를 내보내고 instance를 띄운다(§3). 곧 반납될 GPU는 쓰지 않는 KV cache 자리에 다른 모델 weight를 미리 올린다(proactive prewarming, §3.3, Eq. 4). CUDA VMM API로 page table을 바꾸고 이 작업을 다른 작업과 겹친다(§3.4, 부록 C) |
| 가정·조건 | GPU server 2대(GPU 8개씩, GPU당 dense FP16 약 1K TFLOPS, NVLink 400 GB/s). GPU 이름은 적지 않았다. Weight는 GPU server의 CPU 메모리에 두고 PCIe 5.0 x16으로 올린다. 모델은 Llama2 7B 둘, 13B, 70B(12.55–128.49 GB, Table 1)다. 추론 요청은 AzureConv trace에서 모델마다 다른 요일을 뽑아 만들고 모델별 비율은 지수 α의 power-law다. 지표는 TTFT·TPOT이다(§4.1) |

## 결론

- Prewarm한 weight로 instance를 띄우면 TTFT가 prewarm 없을 때보다 60.13–87.63배 짧았다(70B 40.29 s → 0.67 s). 이미 돌고 있는 instance는 0.05 s였다(§4.2, Table 2)
- SLLM-GPU보다 P95 TTFT는 1.07–10.06배, P99 TTFT는 1.53–50.79배 짧았다. RPS 15, α = 0.5에서 MuxServe의 P95·P99 TTFT는 WarmServe의 34.5배·134.0배였다(§4.3, Fig. 4)
- AzureConv 5분 window의 예측 상대 오차는 평균 부하 5.3%, 최대 부하 7.3%였다(§3.1). Window를 3분·40분으로 바꾸면 TTFT 100 ms 안에 처리한 추론 요청이 5분일 때의 0.46배·0.30배였다(§4.4, Fig. 5)
- 평가 방식: GPU 16개 실측(vLLM 기반 구현)과 GPU 512개 simulation(§4.5, Table 3)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 다음에 쓸 모델의 weight 전체를 미리 올려 둔다. 메모리 하나(GPU, BRAM)에 여러 모델 weight를 함께 둔다 | WarmServe는 5분 window마다 모델별 동시 추론 요청 수(평균·최대)를 예측한다. 기준은 지난 7일 같은 window의 부하다(§3.1). 예측하는 값은 부하량이고 다음 사용 시각은 예측하지 않는다. PNU-Count는 32 ms 주기 안에서 모델마다 다음 사용 시각을 ms 단위로 예측한다. 기준은 nominal frame 끝 시각 `O_m + kT`이고 모델 그룹 지연 분포와 Uniform(0, J)로 늦어지는 폭만 더한다(04 §3.1) | [구조] 다음 사용 시각의 기준이 offset으로 정해져 있어 며칠 치 부하 기록으로 주기성을 학습하지 않아도 된다. 이번 주기 예상 추론 요청 수도 Host가 추론 요청 packet의 n_expect로 알려 준다 |
| 자리가 모자라면 올려 둔 weight 일부를 내보낸다 | WarmServe는 burst가 온 모델이 GPU를 혼자 쓰도록 그 GPU의 다른 prewarm weight를 모두 내보낸다(§3, 부록 C). 무엇을 올릴지는 점수로 정한다(부록 B.1). PNU-Count는 entry 4개가 모자랄 때 다음 사용 시각이 가장 늦은 모델 하나를 내보낸다 | 없음. 목표가 다르다. WarmServe는 GPU cluster에서 cold start로 늘어나는 TTFT를 줄이고 이 연구는 FPGA 하나의 BRAM이 정해진 상태에서 DDR3 traffic을 줄인다 |

## 인용할 때

- WarmServe가 먼저 했다: LLM 부하의 주기성으로 모델별 부하를 예측해 여러 LLM weight를 GPU 하나에 미리 올리는 것(one-for-many GPU prewarming), 곧 반납될 GPU의 남는 KV cache 자리에 다음 모델을 미리 올리는 것. 예측으로 미리 적재하는 것(prefetch)과 모델 단위 cache 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: 주기성 §2.2(Fig. 1–2), 예측 §3.1(Eq. 1–3), 배치 §3.2(Algorithm 1)와 부록 B(Eq. 5–8, Fig. 13), proactive prewarming §3.3(Eq. 4), 메모리 전환 §3.4와 부록 C(Fig. 14), 실험 조건 §4.1(Table 1), 결과 §4.2(Table 2)·§4.3(Fig. 4)·§4.4(Fig. 5)·§4.5(Table 3)·§4.6(Fig. 6), hit ratio 부록 A.4(Fig. 12)
- 주의: 초록의 50.8배는 SLLM-GPU 대비 P99 TTFT의 최댓값이다. P95는 1.07–10.06배다. 2.5배는 MuxServe와 견준 처리 가능 추론 요청 수다(§4.3)
- 주의: 예측 정확도 92.7%(최대 부하)와 94.7%(평균 부하)는 AzureConv 값이다(§2.2). 다른 trace는 Fig. 6에 그림만 있다. 저자도 짧은 시간의 도착은 stochastic하다고 보고 분 단위 window의 통계만 예측한다(§1, §3.1)
- 주의: 식 (2)의 가중 2^(w−1)은 w가 클수록, 곧 오래된 window일수록 크다. 바로 뒤 본문은 최근 오차에 더 큰 가중을 준다고 적어 식과 반대다(§3.1)
- 주의: serverless prewarming의 선행으로 Shahrad 등(C12)을 비롯한 연구를 든다. WarmServe는 LLM이 여러 GPU에 걸치고 weight 전체를 올려야 하는 점에 맞춰 배치와 메모리 관리를 고쳤다고 적었다(§5)
- 비교군: 옮기지 않았다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
