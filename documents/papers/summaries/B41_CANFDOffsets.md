# B41: CAN-FD Signal Offset Assignment

원문: `B41_CANFDOffsets_RTSS2017.pdf`
Prachi Joshi, S. S. Ravi, Soheil Samii, Unmesh D. Bordoloi, Sandeep K. Shukla, Haibo Zeng, "Offset Assignment to Signals for Improving Frame Packing in CAN-FD", IEEE RTSS 2017, pp. 167–177, DOI 10.1109/RTSS.2017.00023
읽은 범위: 원문 전체(11쪽)

## 한 줄 요약

CAN-FD frame 하나에 주기가 다른 signal을 실을 때 signal마다 offset을 줘 frame instance에 나눠 싣는다(SOAP, signal offset assignment problem). 가장 많이 실린 instance가 작아져 frame payload와 bus bandwidth 사용률이 내려간다. Signal 300개 합성 system에서 bandwidth 사용률이 약 10.54% 개선됐다. Offset은 부하를 고르게 벌리는 데만 쓴다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 기존 frame packing은 주기가 다른 signal을 한 frame에 실어도 offset을 0으로 둔다. Frame payload는 고정이라 모든 signal payload의 합 이상이어야 하고 일부 instance는 비운 채 보낸다. CAN-FD payload는 0–8, 12, 16, 20, 24, 32, 48, 64 bytes 중 하나다(§I-A, §III, Fig. 1) |
| 방법 1 | frame instance 간격은 signal 주기의 최대공약수 t_b다. 주기 t_i인 signal의 offset은 {j × t_b : j = 0, …, t_i/t_b − 1} 중 하나다. Frame payload는 instance별 점유 최댓값을 담는 가장 작은 CAN-FD 크기다. 목표는 최대 점유를 줄이는 것이다(§IV) |
| 방법 2 | 주기가 두 개만 있어도 strongly NP-complete다(3-PARTITION에서 환원, Theorem 1). 주기가 모두 같으면 offset은 모두 0이다(§V) |
| 방법 3 | GAF: 같은 주기 signal끼리 makespan 최소화(부하 균형) 문제로 offset을 정한 뒤 합친다. 근사 성능은 base 주기 signal이 있으면 1 + ρ(K − 1), 없으면 ρK다(K는 주기 종류 수, ρ는 MMP 알고리즘의 근사비). A1 greedy(ρ = 2), A2 크기 내림차순 greedy(ρ = 4/3), A3 ILP(ρ = 1)를 쓴다(§VI, Fig. 3, Theorem 3) |
| 방법 4 | [13]의 greedy frame packing이 signal을 frame에 넣을 때마다 SOAP로 bandwidth를 계산한다. 그 뒤 CAN response time 분석(Davis 등)과 Audsley priority 배정으로 schedulability를 확인하고 실패하면 signal을 빼서 다시 싣는다(§VII, Fig. 4). AUTOSAR에서는 frame마다 signal 위치 LUT를 둔다(§VII-A) |
| 가정·조건 | Signal deadline은 주기와 같다. Kramer 등 benchmark 지침으로 만든 합성 system(Table I), 실험마다 1,000개, CAN-FD bus 하나, ECU 3개, signal 50–300개, bit rate는 arbitration 단계 500 kbit/s, 데이터 단계 2 Mbit/s, CPLEX(§VIII) |

## 결론

- Signal 수가 늘수록 개선이 커졌고 300개에서 bandwidth 사용률이 약 10.54% 개선됐다. A1·A2·A3의 결과는 거의 같았다(Fig. 5, §VIII-A)
- Signal이 많은 경우 schedulable system 비율이 약 5.4% 늘었다. 최대 payload가 줄어 frame response time도 줄었다(Fig. 6, §VIII-B)
- 실제 자동차 사례(ECU 17개, signal 3,429개)에서 bandwidth 사용률이 29%에서 약 26.7%로 내려갔다. Signal의 약 69%가 같은 주기(1,000 ms)이고 약 60%가 2 bit 이하라 개선이 작았다(Fig. 7, §VIII-C)
- 평가 방식: packing 알고리즘과 schedulability 분석으로 계산했다. 실측은 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 주기 source에 offset을 줘 생성 시각을 정한다. Offset 하나로 그 뒤 시각이 모두 정해진다(§IV) | SOAP의 offset은 같은 주기 signal을 서로 다른 instance로 벌려 최대 점유를 줄인다(MMP). 같은 종류를 한 시각에 모으지 않는다. 이 연구는 같은 모델 트랙에 같은 offset을 줘 같은 모델 추론 요청을 함께 생기게 하고 모델끼리만 0.8 ms씩 벌린다 | [구조] 같은 모델 추론 요청이 함께 생겨 Grouping이 batch로 묶고 weight 적재 한 번으로 처리한다 |
| 한 시각에 부하가 몰리지 않게 한다 | SOAP가 줄이는 것은 frame payload(bandwidth)이고 response time 개선은 부산물이다(§II). 주기 종류가 여럿이고 offset을 근사 알고리즘·ILP로 고른다. 이 연구는 주기가 32 ms 하나이고 `O_m = m × 0.8 ms`로 고정이다 | 없음. Offset 배정 알고리즘끼리는 비교하지 않았다 |

## 인용할 때

- 이 논문이 먼저 한 것: CAN-FD frame 안 signal에 offset을 줘 frame payload를 줄이는 문제(SOAP)의 정식화, NP-complete 증명, MMP 근사 알고리즘을 쓰는 GAF. 주기 작업의 생성 시각에 간격을 두는 것 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- B21과의 관계: 원문은 Grenier 등(ERTS 2008, B21의 원 논문)을 [9]로 들고 그 offset은 frame, 곧 scheduling 단위에 주는 것이라 이 논문의 signal offset과 다르다고 적었다(§II). 두 논문 모두 offset을 부하를 벌리는 데만 쓴다. 같은 종류를 한 시각에 모으려고 offset을 쓰는 경우는 둘 다 없다
- 근거 위치: 예시 §I-A(Fig. 1), 문제 정의 §IV, 복잡도 §V(Theorem 1), GAF §VI(Fig. 3, Theorem 3), 적용 §VII(Fig. 4), 결과 §VIII(Table I, Fig. 5–7)
- 주의: 10.54%가 사용률의 절대 차(%p)인지 상대 비율인지 원문에 적혀 있지 않다. 사례 연구는 2.3%p 차이, 상대 약 8%라고 적었다(§VIII-C)
- 주의: 여러 signal을 frame 하나에 싣는 frame packing은 [13](Joshi 등, ECRTS 2017)의 단계다. 이 논문이 더한 것은 frame 안 offset이다. 원문의 offset은 signal이 frame 첫 instance에서 떨어진 시간이다
- 비교군: simulation 비교군에 없다
