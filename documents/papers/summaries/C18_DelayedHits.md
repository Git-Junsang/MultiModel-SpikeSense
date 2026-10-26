# C18: Caching with Delayed Hits

원문: `C18_DelayedHits_SIGCOMM2020.pdf`
Nirav Atre, Justine Sherry, Weina Wang, Daniel S. Berger, ACM SIGCOMM 2020, DOI 10.1145/3387514.3405883. 받은 PDF는 CMU PDL의 저자 공개본(19쪽, 부록 포함)이다
읽은 범위: 본문 전체(§1–8). 부록 A는 A.3.2와 A.4만 읽었다

## 한 줄 요약

Miss를 처리하는 동안 같은 object의 request가 쌓이는 delayed hit가 있으면 hit rate 최적인 Belady도 latency 최적이 아님을 보였다. Latency 최적 offline 알고리즘 belatedly는 Belady보다 평균 latency가 최대 45% 낮았고 online 정책 MAD는 CDN prototype에서 LRU보다 12.4–18.3% 낮았다(초록, §5.2).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 기존 cache 모델은 결과를 hit와 miss 둘로만 센다. Fetch가 끝나기 전에 같은 object의 request가 오면 그 request는 남은 fetch 시간만큼 기다린다(delayed hit). Hit rate로 낸 latency 추정(Eq. 1)은 실제보다 작다(§1, §2, Fig. 1–2) |
| 방법 | Z = fetch 시간 ÷ 평균 request 간격이다. Miss 하나의 aggregate delay는 miss의 Z에 그 뒤 Z 안에 온 같은 object request의 기다린 시간(Z − t)을 더한 값이다(§1, §3.1 Eq. 2) |
| 방법 | belatedly(offline): latency 최소 cache schedule을 MCMCF 문제로 바꾸고 miss edge의 비용을 aggregate delay로 둔다(§3.1, Theorem 1). 분수 해를 Gurobi로 풀고 randomized rounding으로 정수 schedule을 얻는다. 두 해의 차이는 최대 1.71%다(§3, Fig. 6, 부록 A.4 Table 3) |
| 방법 | 순위: Rank(x) = AggDelay(x) ÷ TTNA(x)이고 TTNA는 다음 request까지 남은 시간이다. Belady는 1/TTNA만 쓴다. 미래를 아는 belady-ad는 belatedly와 평균 latency 차이가 0.1–12% 안이다(§4.1, Eq. 3, 각주 7, Fig. 12) |
| 방법 | MAD(online): TTNA는 LRU·ARC·LHD의 추정을 쓰고 AggDelay는 지난 request가 모두 miss였다고 보고 miss 하나당 aggregate delay 평균을 낸다. Rank가 작은 object를 내보낸다(§4.2, Algorithm 1) |
| 가정·조건 | 이론 모델은 object 크기와 fetch 시간이 모두 같고 fetch가 끝나면 쌓인 request를 바로 모두 처리한다(§2 각주 2, §6). Trace는 CDN, CAIDA Equinix 10G packet, Microsoft의 networked file system이다(§2.3). 지표는 평균 latency이고 deadline은 다루지 않는다 |

## 결론

- Belatedly 대비 Belady의 평균 latency는 Z가 수천 이상인 경우 9–37% 높았다. Delayed hit를 처음 본 FPGA software switch(DRAM 100 ns, Z < 1)에서는 차이가 1% 미만이었다(§3.2, Fig. 7, Table 2)
- CDN prototype(C++, 64-way set-associative, cache 크기는 동시 활성 object 최대 수의 5%, object 1 KB): LRU-MAD가 LRU보다 평균 latency를 origin RTT 68·103·226 ms에서 12.4·14.7·18.3%, object마다 origin을 무작위로 정하면 16.8% 줄였다. Object당 8 B counter 4개를 더 쓴다(§5.1–5.2, Fig. 14)
- Simulation에서 MAD는 miss rate를 Network·Storage에서 상대값으로 최대 10%(평균 +1.84%·+1.43%) 늘렸고 CDN에서는 평균 1.89% 줄였다(절대 차이는 1% 이하, 각주 16). 저자는 workload에 따라 latency와 bandwidth 사이 trade-off가 있다고 결론지었다(§5.4, Fig. 21)
- 평가 방식: CDN caching node prototype 실측(CMU 서버, GCP VM origin 3곳)과 delayed hit를 넣은 trace simulation

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| fetch(적재)가 끝나기 전에 온 같은 대상의 request는 그 fetch 한 번으로 함께 처리된다. 이 연구도 weight를 적재하는 동안 도착한 같은 모델 추론 요청은 적재가 끝난 뒤 batch 하나에 들어간다(03 §3 4단계) | Atre 등은 쌓인 request마다 기다린 시간(Z − t)을 비용으로 센다(Eq. 2). 이 연구의 cache 비교 지표는 DDR3 traffic(KiB/추론)이라 적재 한 번을 여러 추론 요청이 나눠 쓰면 비용이 준다 | 없음. 목표가 다르다. MAD는 평균 latency를 줄이고 PNU-Count는 BRAM이 정해진 상태에서 DDR3 traffic을 줄인다 |
| 다음 사용까지 남은 시간으로 내보낼 대상을 고른다 | MAD는 쌓일 request가 많은 object를 더 오래 남긴다(Eq. 3). PNU-Count는 다음 사용 시각만 비교해 가장 늦은 모델을 내보낸다. 남은 추론 요청 수 r(예상 수 − 도착 수)은 다음 도착까지 남은 시간 δ_j(x, r) = (J − x)/(r + 1)을 구하는 데만 쓴다(04 §3.1) | [구조] 이번 주기 예상 추론 요청 수를 Host가 추론 요청 packet의 n_expect로 알려 주고 FPGA는 도착한 수만 센다. MAD는 쌓일 request 양을 지난 miss window의 평균으로 추정한다(Algorithm 1) |

## 인용할 때

- 이 논문이 먼저 한 것: delayed hit를 넣은 cache latency 최소화 문제와 offline 해법(belatedly), aggregate delay를 다음 request까지 남은 시간으로 나눈 교체 순위(MAD). 저자는 delayed hit의 분석 모델과 이를 겨냥한 알고리즘을 낸 선행연구를 모른다고 적었다(§7). 다음 사용 시점 교체 원리 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: delayed hit 정의 §1·§2(Fig. 1–2), Belady 반례 §2.2(Fig. 3), Z 예시 Table 2, MCMCF와 aggregate delay §3.1(Eq. 2, Theorem 1), Belady와 차이 §3.2(Fig. 7–9), belady-ad §4.1(Eq. 3, Fig. 11–12), MAD §4.2(Algorithm 1), prototype §5.1–5.2(Fig. 13–15), simulation §5.3–5.4(Fig. 16–22), 한계 §6
- 주의: 수치마다 비교 대상이 다르다. 초록의 45%와 §3.2의 9–37%는 belatedly 대 Belady, 12.4–18.3%는 prototype의 LRU-MAD 대 LRU다. §1의 simulation 이득(switch 15–43%, CDN 10–60%, storage 5–40%)은 같은 base 알고리즘(LRU·ARC·LHD)과 견준 값이다
- 주의: Origin C의 RTT가 본문은 226 ms, Fig. 14는 223 ms다(§5.1–5.2). 부록 A 첫머리에 부록은 peer review를 받지 않았다고 적혀 있다
- 주의: PNU-Count도 다음 사용 시각만으로 순위를 매기므로 Belady와 같은 방식이다. Atre 등은 이 방식이 delayed hit에서 latency 최적이 아님을 보였다(§2.2). 이 연구는 cache 정책을 DDR3 traffic으로 견줬고 이 연구 조건의 Z는 구하지 않았다. 이 연구의 Oracle MIN도 cache 결정에 따라 batch 구성이 바뀌어 전체 시스템의 최적은 아니다(04 §3.2)
- 비교군: 옮기지 않았다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
