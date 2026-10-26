# B30: Deep Speech 2 (§7.1 batch Dispatch만 요약)

원문: `B30_DeepSpeech2_ICML2016.pdf`
Dario Amodei 등 33명(Baidu Research Silicon Valley AI Lab, 저자 순서는 알파벳순), ICML 2016(PMLR 48). 원문에 DOI가 없다. 받은 PDF는 arXiv:1512.02595v1(2015-12-08) 판이다
읽은 범위: §7(배포) 전체, 그중 §7.1 중심. §1, §3.1, §3.7은 배포와 이어진 문단만 읽었다

## 한 줄 요약

여러 사용자 audio stream을 GPU 하나에서 batch로 묶어 weight 읽기를 나눠 쓰는 batch Dispatch를 만들었다. 앞 batch가 끝나면 그때 준비된 만큼만 묶는 eager batching으로 동시 stream 10개에서 중앙값 44 ms, 98번째 백분위 70 ms의 latency를 냈다(§7.1, Fig. 6).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 추론 요청을 하나씩 처리하면 추론 요청마다 network weight를 모두 읽는다. On-chip cache를 잘 쓰지 못해 메모리 bandwidth가 병목이 되고 추론 요청 하나로는 병렬성이 적어 SIMD·multi-core를 쓰기 어렵다. RNN은 sample마다 matrix-vector 곱을 차례로 해야 해서 더 어렵다(§7.1) |
| 방법 | batch Dispatch는 사용자 추론 요청의 stream 데이터를 batch로 모은 뒤 forward propagation을 한다. Batch가 크면 효율이 좋지만 모으는 동안 사용자가 기다린다(§7.1) |
| 방법 | eager batching: 앞 batch가 끝나면 그때까지 준비된 일만으로 다음 batch를 바로 처리한다. Batch 크기를 키우지 않아 계산 효율은 낮지만 end-user latency를 줄이는 데 가장 좋았다고 적었다(§7.1) |
| 방법 | 배포 모델은 단방향 RNN 5층(hidden 2,560), row convolution 1층(τ = 19), fully-connected 1층이다. 발화가 들어오는 대로 계산한다(§3.7, §7.4). Half precision으로 돌리고 batch 크기 10 이하에서 쓰는 matrix 곱 kernel을 따로 만들었다(§7.2) |
| 가정·조건 | 배포 대상은 Mandarin system이다(§7). Production system은 NVIDIA Quadro K1200 GPU 하나에서 동시 stream 10–30개를 처리한다(Fig. 5). Latency는 발화 끝부터 전사 결과가 나올 때까지의 계산 지연이고 internet 전송은 넣지 않는다(§7). 여러 모델을 한 GPU에 두는 내용과 deadline은 다루지 않는다 |

## 결론

- 부하가 클수록 큰 batch에서 처리하는 비율이 커졌다. 동시 stream 10개에서도 절반이 넘는 일을 batch 크기 2 이상에서 처리했다(§7.1, Fig. 5)
- 동시 stream 10개에서 latency 중앙값은 44 ms, 98번째 백분위는 70 ms였다. 부하가 늘면 scheduler가 큰 batch로 옮겨 latency를 낮게 유지한다고 적었다(§7.1, Fig. 6)
- 동시 stream 10개에서 90%가 넘는 batch가 크기 4 이하였다. 이 범위에서 전용 kernel은 peak bandwidth의 90%를 냈다(§7.2)
- 평가 방식: production system 실측. Batch 크기 분포와 latency 그림만 있고 다른 묶음 처리 방식과 견준 데이터는 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 여러 stream의 입력을 batch로 묶어 weight 읽기 한 번을 나눠 쓴다. Batch를 키우려고 기다리지 않고 앞 batch가 끝나면 그때까지 도착한 만큼 묶는다(§7.1). Grouping도 같다(05 §3) | batch Dispatch는 도착 시각을 바꾸지 않아 batch 크기가 부하에 따라 달라진다(Fig. 5). 이 연구는 Host가 같은 모델 트랙에 같은 offset을 줘(Model-Grouped Offset Assignment) 같은 모델 추론 요청이 함께 생긴다 | [구조] 기다리지 않아도 같은 모델 추론 요청이 함께 도착해 batch가 생긴다 |
| 추론 요청마다 weight를 읽으면 메모리 bandwidth가 병목이 된다고 본다(§7.1, §7.2) | 모델 교체는 다루지 않는다. Bandwidth 부담은 half precision과 전용 kernel로 줄인다(§7.2). 이 연구는 FPGA 하나가 모델 40개로 mic 트랙 1,024개를 처리하고 weight 4.97 MiB가 BRAM보다 커서 weight 전송이 병목이다 | [구조] PNU-Count가 다음 사용 시각을 예측해 가장 늦게 쓸 모델을 내보낸다 |
| stream마다 앞 시점의 state를 이어 쓴다. 원문은 RNN hidden state(§3.1 Eq. 3), 이 연구는 트랙별 membrane potential이다 | 원문은 batch 안 stream마다 RNN state를 어디에 두는지 적지 않았다. 이 연구는 membrane potential을 16 bit로 계산하고 12 bit로 저장한다 | [구조] 12 bit Membrane Storage로 남는 BRAM에 768트랙의 state를 둔다. 원문에는 견줄 내용이 없다 |

## 인용할 때

- 이 논문이 먼저 한 것: 여러 사용자 audio stream을 GPU 하나에서 batch로 묶고 앞 batch가 끝나면 그때 준비된 만큼만 처리하는 eager batching. 같은 모델의 묶음 처리·weight 공유 자체는 신규성으로 주장하지 않는다(09 §3). 기다리지 않고 도착한 만큼 묶는 규칙도 이 논문이 먼저 썼다. 09 §3은 Grouping을 PNU-Count·12 bit Membrane Storage와 결합한 구조로만 주장한다
- 근거 위치: latency 정의 §7 셋째 문단, 문제 §7.1 첫 문단, batch Dispatch와 eager batching §7.1 둘째·셋째 문단, batch 크기 분포 Fig. 5, latency Fig. 6, 단방향 모델 §3.7(Fig. 3), kernel §7.2(Fig. 7), 배포 모델 구성 §7.4
- 주의: latency 정의가 다르다. 원문은 발화 끝부터 전사 결과까지의 계산 지연이다(§7). 이 연구의 response time은 frame 마지막 샘플이 Host에 도착한 때부터 Host가 결과를 받을 때까지다. 44 ms·70 ms를 32 ms deadline과 견주지 않는다
- 주의: 동시 stream 10개의 98번째 백분위가 §1은 67 ms, §7.1은 70 ms다. Eager batching이 가장 좋았다는 문장(§7.1)에는 비교한 방식과 데이터가 없다. Symphony(B09)는 eager 방식이 batch가 작아 처리량이 낮다고 봤다
- 주의: 받은 판은 arXiv v1이다. ICML 2016 게재판의 절·그림 번호는 확인하지 못했다
- 옮긴 방식: simulation 비교군에 없다. 모델이 하나일 때 Grouping의 구성원 규칙과 같다
