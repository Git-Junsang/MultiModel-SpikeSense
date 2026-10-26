# C17: FaasCache

원문: `C17_FaasCache_ASPLOS2021.pdf`
Alexander Fuerst, Prateek Sharma, ACM ASPLOS 2021, pp. 386–400, DOI 10.1145/3445814.3446757
읽은 범위: 원문 전체(Artifact Appendix는 훑음)

## 한 줄 요약

Function keep-alive를 object cache 교체로 보고 호출 빈도, 초기화 비용, 메모리 크기, 최근 사용을 함께 쓰는 Greedy-Dual-Size-Frequency(GDSF) 정책으로 자리가 모자랄 때만 container를 내보냈다. Azure trace simulation에서 cold start overhead가 10분 TTL보다 3배 넘게 줄었다(Representative trace, cache 15–80 GB).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 고정 TTL keep-alive(OpenWhisk 10분)는 function마다 다른 크기, 초기화 시간, 호출 빈도를 보지 않는다(§1, §3.1) |
| 방법 | warm container를 cache의 object로, warm start를 cache hit로, container 종료를 eviction으로 본다. 자원이 남으면 계속 두고 새 container를 띄울 자리가 없을 때만 priority가 가장 낮은 container를 종료한다(§4, §4.1) |
| 방법 | Priority = Clock + Freq × Cost ÷ Size(식 (1)). Clock은 server의 논리 시계이고 eviction 때 종료한 container의 priority 값이 된다. Freq는 function 호출 횟수, Cost는 초기화 시간, Size는 container 메모리다. Clock만 쓰면 LRU, Freq만 쓰면 LFU다(§4.1, §4.2) |
| 방법 | reuse distance로 hit-ratio curve를 만들어 server 메모리 크기를 정한다(식 (2)). 비례 제어기가 10분마다 cold start 속도를 보고 VM 메모리를 늘리거나 줄인다. 오차가 30%를 넘을 때만 바꾼다(§5, §6) |
| 가정·조건 | server 하나 단위. OpenWhisk 구현(ContainerPool Scala code 100줄 수정)과 Python discrete-event simulator. Azure trace 첫날에서 뽑은 Representative(function 400개), Rare(1,000개), Random(200개). 정책은 종료할 container를 고르는 eviction 정책이고 다음 호출을 예측해 미리 올리지 않는다. Deadline이 없다(§4.1, §6, §7, Table 2) |

## 결론

- Simulation(Representative): GD가 cache 15–80 GB에서 cold start overhead를 10분 TTL보다 3배 넘게 줄였다. 15 GB에서 overhead 0.5%였고 다른 정책은 비슷한 값에 50 GB가 들었다. Rare·Random trace에서는 LRU가 가장 좋았다(Rare에서 TTL 대비 2배, 40–50 GB)(§7.1, Fig. 5)
- OpenWhisk 실측(48 GB server, function 4개 skewed workload): OpenWhisk는 호출의 50%를 drop했고 FaasCache는 warm start를 2배 넘게 늘렸다. 초기화가 긴 floating-point function은 hit ratio가 3배였고 원문은 application latency가 6배 줄었다고 적었다(§7.2, Fig. 8)
- Dynamic scaling은 cold start 속도를 목표(초당 0.0015회) 근처에 두면서 평균 7,000 MB 미만을 썼다. 고정 10,000 MB보다 server 크기가 30% 작다(§7.3, Fig. 9)
- 평가 방식: Azure trace simulation과 OpenWhisk 실측(48-core Intel Xeon Platinum 2.10 GHz, 250 GB RAM server)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 자리가 모자랄 때만 내보내고 남은 대상 중 하나를 priority로 고른다 | GDSF는 호출 빈도, 초기화 비용, 크기, 최근 사용(Clock)으로 priority를 정하고 다음 호출 시각은 예측하지 않는다. PNU-Count는 queue, 모델 그룹 지연 분포, 추론 요청별 지연 분포, n_expect로 다음 사용 시각을 예측해 가장 늦게 쓸 모델을 내보낸다 | [구조] 모델마다 nominal frame 끝 시각을 Host가 정해 두어(Model-Grouped Offset Assignment) 지난 사용 기록 대신 예측한 다음 사용 시각으로 고른다 |
| 모델(function) 하나를 cache 단위로 보고 적재 비용을 줄인다 | FaasCache는 크기와 초기화 시간이 서로 다른 function을 식 (1)로 다룬다. 이 연구는 연산하는 동안 다음 batch 모델을 빈 entry로 prefetch한다 | 없음. PNU-Count는 크기와 적재 비용을 보지 않는다 |

## 인용할 때

- Fuerst·Sharma가 먼저 했다: keep-alive를 cache 교체로 보는 것, 크기·초기화 비용·빈도·최근 사용을 함께 쓰는 GDSF keep-alive, reuse distance로 만든 hit-ratio curve로 메모리 크기를 정하는 것. 모델 단위 cache 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: caching 비유 §1과 §4 첫머리, 식 (1)과 각 항 §4.1, LRU·LFU·SIZE·Landlord 변형 §4.2, hit-ratio curve 식 (2) §5.1, dynamic scaling 식 (3) §5.2, 실험 조건 §7과 Table 2, 결과 Fig. 5–9
- 주의: 초록의 "more than 3×"는 Representative trace 값이다. Rare·Random trace에서는 GD가 아니라 LRU가 가장 좋았다(§7.1)
- 주의: cold start overhead는 dataset 실행 시간의 최댓값 − 평균으로 추정해 container 생성 시간이 빠진다. 저자는 overhead가 낮게 잡히지만 정책 사이 순위는 그대로라고 적었다. 실행 시간 증가는 대체로 10% 아래다(§7, §7.1)
- 주의: HIST(C12의 hybrid policy)는 저자가 best-effort로 다시 구현했고 ARIMA 부분은 뺐다(§7.1). 6배 latency 감소는 Fig. 8의 function 4개 workload에서 나온 값이다(§7.2)
- 비교군: 옮기지 않았다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 GDSF가 없다. 원문은 Clock만 쓰면 LRU가 된다고 적었다(§4.2)
