# B35: Patterns for FPGA Multi-accelerator Edge

원문: `B35_PatternsFPGAEdge_DATE2022.pdf`
Seyyed Ahmad Razavi, Hsin-Yu Ting, Tootiya Giyahchi, Eli Bozorgzadeh(UC Irvine), DATE 2022, pp. 116–119, DOI 10.23919/DATE54114.2022.9774767
읽은 범위: 원문 전체(4쪽)

## 한 줄 요약

FPGA edge 하나가 주기적으로 추론 요청을 보내는 end device 여러 대를 받는다. 도착 pattern으로 재적재를 줄이는 실행 순서를 미리 정하고, 실행 중에는 end device의 송신 시각을 기대 시각에 맞추게 해 FCFS보다 response time을 크게 줄였다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | FCFS로 처리하면 accelerator를 자주 바꿔 재구성·재적재 비용이 쌓인다. network 지연이 흔들리면 미리 정한 일정과 실제 도착이 어긋난다 |
| 방법 1 | 배포 전에 도착 순서에서 pattern을 뽑는다. hyperperiod 크기 window로 episode mining(EMMA)을 돌려 대표 pattern P + q를 만든다(Alg. 1, §III-A) |
| 방법 2 | 대표 pattern으로 slot별 accelerator와 실행 순서를 MILP로 정한다. 목적은 평균 response time이고, 재적재 시간과 hyperperiod 사이 재적재, slot 부하 균형을 제약으로 넣는다. 같은 accelerator task는 순서를 바꿔 몰아 처리한다(§III-B) |
| 방법 3 | 실행 중 staggering module이 device마다 도착 시각과 기대 시각의 차이를 sliding window로 평균한다. 평균이 문턱을 넘으면 'Wait command'를 보내 device가 sampling 시각을 옮긴다. 시계 동기는 필요 없다(§IV-A, Fig. 3) |
| 방법 4 | slot마다 online scheduler가 offline 표를 기준으로 삼는다. 지금 accelerator의 queue를 다 처리하고, 일찍 끝나면 다음 accelerator를 미리 가져온다. 다음 accelerator는 offline 표의 round-robin 순서다(§IV-B, Alg. 2) |
| 가정·조건 | Xilinx ZCU104, accelerator slot 3개, BNN accelerator([6]의 모델). End device는 라즈베리파이 3B+·4B 7대, 5 GHz WiFi, TCP. Device마다 2–8 fps, 합계 26·30·34 fps, 10분 실험, timeout 1 s. 정규분포 지연(평균 0–70, 표준편차 0–10)을 일부러 더했다 |

## 결론

- Static(같은 offline 표를 그대로 따름, [6]) 대비 평균 response time 7–36%, 평균 대기 시간 12–60% 감소(Table I)
- FCFS는 timeout이 4,348–8,343개, 평균 response time 859–881 ms였다. 제안은 timeout 0–2개다(Table I)
- Wait command는 2초에 한 번 이하로 보내고, edge의 CPU 사용률 증가는 5% 미만이다(§V)
- 평가 방식: 보드 실측(ZCU104와 라즈베리파이)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 주기 source의 송신 시각을 기대 시각에 맞춘다 | 기대 시각은 임의 시각에 시작한 device의 도착을 관측해 뽑은 pattern이고, Wait command로 계속 맞춘다. 이 연구는 Host가 모델마다 offset을 설계해 고정한다 | [구조] 같은 모델 추론 요청이 함께 생기고 모델끼리 0.8 ms씩 벌어지도록 offset을 정하므로 pattern 추출과 feedback 경로가 없다 |
| 같은 accelerator task를 몰아 처리하고 다음 것을 미리 가져온다 | 재적재 단위는 slot의 accelerator(재구성)이고, 다음 accelerator는 offline 표의 순서만 본다 | [구조] PNU-Count는 모델 그룹 지연 G(m, k)와 추론 요청별 지연 j(i, k)의 분포, n_expect로 이번 주기에 아직 올 추론 요청을 가려 weight entry를 교체한다 |
| FPGA 하나에서 여러 DNN을 나눠 쓴다 | device 7대, slot 3개, soft real-time(timeout 1 s) | [구조] 모델 40개, 트랙 1,024개, 32 ms deadline을 다룬다. 같은 모델 트랙도 membrane potential을 따로 둔다 |

## 인용할 때

- 이 논문이 먼저 한 것: FPGA 다중 accelerator edge에서 주기 source의 송신 시각을 기대 시각으로 옮기는 staggering, 재적재를 줄이는 정적 실행 순서, 알려진 순서로 다음 accelerator를 미리 가져오기. 이 셋 자체는 신규성으로 주장하지 않는다
- 이 연구가 주장할 범위: 모델을 기준으로 offset을 설계해(Model-Grouped Offset Assignment) weight 재사용을 만들고, Host 처리 지연 분포와 n_expect로 다음 사용을 예측하는 PNU Cache, 기다리지 않는 Grouping을 결합한 것
- 근거 위치: staggering §IV-A와 Fig. 3, online scheduler §IV-B와 Alg. 2, MILP 제약 §III-B, 결과 Table I
- 주의: 'staggering'은 도착을 벌리는 뜻이 아니라 기대 시각으로 옮긴다는 뜻이다. 추가 지연의 단위는 원문에 없다. 선행 연구 [6](Ting 등, ASAP 2020)은 고정 pattern을 가정한 정적 일정이고 원문은 받지 못했다
