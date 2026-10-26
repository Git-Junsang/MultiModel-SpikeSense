# B21: CAN Offset Assignment

원문: `B21_CANoffsets_CRC2008.pdf`
Mathieu Grenier, Lionel Havet, Nicolas Navet, "Scheduling messages with offsets on Controller Area Network - a major performance boost", Automotive Embedded Systems Handbook(CRC Press, 2008) 장의 저자 개정본(2008-08-16), handbook 장 DOI 10.1201/9780849380273.ch14(OpenAlex 기준, 받은 PDF에는 없다). 원 논문은 ERTS 2008의 "Pushing the limits of CAN - scheduling frames with offsets provides a major performance boost"이다(제목은 OpenAlex 기준)
읽은 범위: 원문 전체(저자 개정본)

## 한 줄 요약

CAN station마다 주기 message stream의 offset(첫 frame을 보내기 전에 늦추는 시간)을 가장 덜 붐비는 구간의 가운데로 정해 동시 전송을 피했다. Body network 하나에서 가장 낮은 priority frame의 WCRT(worst-case response time)가 64.8 ms에서 21.6 ms로 줄었다(§4.1, Fig. 2).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | frame의 WCRT는 그보다 priority가 높은 message가 모두 같은 시각에 나올 때 생긴다. 부하가 늘면 WCRT가 크게 늘어난다. 저자는 이것이 bus 사용률을 30–40% 정도로 낮게 두는 까닭일 수 있다고 본다(§1) |
| 방법 | offset을 주기가 짧은 stream부터 하나씩 정한다. [0, T_k) 안에서 부하가 가장 작은 possible release time이 가장 길게 이어진 구간을 찾아 그 가운데에 offset을 둔다. 정한 stream의 전송 시각은 release array에 더한다(§2.4.2, Table 1). 계산량은 O(n · max T_k / g)이다 |
| 방법 | offset과 주기는 g의 배수다. g는 communication controller에 frame을 넘기는 communication task의 주기이고 보통 5 ms보다 짧다. 서로 다른 주기 값이 5–10개 정도로 적다고 가정한다(§2.1). Release jitter는 없다고 둔다(§2.2) |
| 가정·조건 | 알고리즘은 station마다 따로 돌고 다른 station의 stream은 보지 않는다(§2.2). Station 사이에 전역 시계 동기화가 없어서 stream이 서로 벌어지는 것은 station 안에서뿐이다. 다른 station의 frame은 같은 시각에 나올 수 있다(§2) |
| 가정·조건 | NETCARBENCH로 만든 body network(ECU 15–20개, message 평균 71개, 125 kbit/s, 주기 50 ms–2 s)와 chassis network(ECU 5–15개, 평균 58.5개, 500 kbit/s, 주기 10 ms–1 s)다. 평균 부하는 35%다(§3, Table 3). Message 대부분은 soft real-time이고(§1) 지표는 NETCAR-Analyzer로 계산한 WCRT다(§2.3) |

## 결론

- Body network 하나(125 kbit/s, 부하 37.6%, message 68개): gain이 가능한 frame은 모두 WCRT가 줄었고 priority가 낮을수록 많이 줄었다. 가장 낮은 priority frame은 64.8 ms에서 21.6 ms로 약 3분의 1이 됐다. 무작위 offset 100번의 평균보다도 짧았다(§4.1, Fig. 2)
- 부하의 약 30%를 station 하나가 내는 body network: 그 station에만 offset을 줘도 가장 낮은 priority frame의 WCRT가 34.5% 줄었다. 부하가 큰 station 네 곳에 주면 48% 줄었다(§4.3, Fig. 7)
- 부하를 40–60%로 올린 body network 하나: 60%에서 gain은 늘린 부하를 기존 station에 나누면 2.8배, 새 station에 두면 2.1배였다. 60% 부하에서 offset을 쓴 가장 낮은 priority frame의 WCRT가 offset 없는 30% 부하의 WCRT와 비슷했다(§5, Fig. 8)
- 평가 방식: NETCARBENCH가 만든 network를 NETCAR-Analyzer로 분석한 WCRT 계산이다. 실측은 없다(§2.3, §3). 무작위 network 4,000개(body·chassis × 부하 집중 유무, 1,000개씩)의 감소 비율 분포는 Fig. 3·4에 있다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 주기 stream에 offset을 줘 생성 시각에 간격을 두고 한 시각에 몰리지 않게 한다(§1, §2) | CAN 알고리즘은 각 stream의 첫 frame을 이미 정한 frame들과 되도록 멀리 둔다(§2.4). 함께 처리해 얻는 이득은 다루지 않는다. 이 연구는 같은 모델 트랙에 같은 offset을 주고 모델끼리만 0.8 ms씩 벌린다 | [구조] 같은 모델 추론 요청이 함께 생겨 Grouping이 batch로 묶고 weight 적재 한 번으로 처리한다 |
| offset 하나로 그 뒤 생성 시각이 `O_k + i · T_k`로 모두 정해진다(§2.4) | CAN은 주기 값이 여러 개이고 offset을 탐색으로 고른다(§2.1, §2.4.2). Offset은 station 안에서만 통한다(§2). 이 연구는 주기가 32 ms 하나이고 offset은 `O_m = m × 0.8 ms`로 고정이다 | 없음. Offset 배정 알고리즘끼리는 비교하지 않았다 |
| | CAN은 offset을 준 뒤의 WCRT를 NETCAR-Analyzer로 정확히 계산한다(§2.3) | 없음. 이 연구는 32 ms hard deadline 보장을 주장하지 않는다(09 §3) |

## 인용할 때

- 이 논문이 먼저 한 것: 주기 message stream에 offset을 줘 동시 전송을 피하고 WCRT를 줄이는 것, 가장 덜 붐비는 구간 가운데에 offset을 두는 저비용 알고리즘. 주기 작업의 생성 시각에 간격 두기 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 근거 위치: 알고리즘 §2.1·§2.4(Definition 1–4, Table 1·2), station별 실행과 전역 동기화 없음 §2·§2.2, WCRT 결과 §4.1(Fig. 2–4), 부하 분포 설명 §4.2(Fig. 5·6), 일부 station만 offset §4.3(Fig. 7), 부하 증가 §5(Fig. 8)
- 주의: 선점 task의 offset 배정은 참고문헌 [3](Goossens 2003)과 [4](Grenier 등, RTNS 2006)가 먼저 다뤘다(§1). 이 논문은 주기 값이 적은 자동차 CAN message에 맞춘 알고리즘이다. 저자는 NETCAR-Analyzer의 비공개 알고리즘이 이 알고리즘보다 훨씬 낫다고 적었다(§2.3)
- 주의: offset을 써도 보낼 일의 양은 같다. 전송을 기다리는 일의 peak가 작아졌고 누적 도착량 곡선이 직선에 가까워졌다(§4.2, Fig. 5·6). §2.3 본문의 "Figure 2"는 화면 그림을 가리키지만 그 caption은 Figure 1이다. 절·그림 번호는 저자 개정본 기준이다
- 비교군: simulation 비교군에 없다
