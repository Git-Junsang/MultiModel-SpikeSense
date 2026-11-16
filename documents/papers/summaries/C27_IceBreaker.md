# C27: IceBreaker

원문: `C27_IceBreaker_ASPLOS2022.pdf`
Rohan Basu Roy, Tirthak Patel, Devesh Tiwari, ACM ASPLOS 2022, pp. 753–767, DOI 10.1145/3503222.3507750
읽은 범위: 원문 전체(부록 A 포함). 그림의 막대 값은 본문에 적힌 것만 옮겼다

## 한 줄 요약

함수마다 지난 1시간의 호출 수 시계열을 Fourier 변환으로 외삽해 다음 1분의 호출 수를 예측한다. 그리고 점수에 따라 비싼 서버, 싼 서버, 미리 띄우지 않음 가운데 하나를 고른다. AWS EC2 위 OpenWhisk 실측에서 OpenWhisk 10분 keep-alive보다 keep-alive cost를 60% 넘게 줄였고 평균 service time을 40% 넘게 줄였다(§5, Fig. 6).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 미리 띄운(warm-up) 함수의 keep-alive cost는 다음 호출 확률과 상관없이 시간당 같다. 기존 예측(histogram, ARIMA)은 호출 주기가 바뀌면 늦게 따라가고 동시 호출 수(concurrency)를 직전 값으로 둔다(§1, §3.1, Fig. 4) |
| 방법 | FIP: 1분 interval마다 지난 1시간의 호출 수에서 2차 다항식 추세 a t² + b t + c를 빼고 FFT로 큰 harmonic 10개의 주파수와 위상을 구한다. 추세와 cos 항을 더해 다음 interval의 호출 수를 예측한다. 0이 아닌 예측 사이 간격이 다음 호출까지 시간이다(§3.1) |
| 방법 | PDM: 함수마다 S_u = (T_n + (1 − F_p) + (1 − I_s) + (1 − M_r))/4를 구한다(Eq. 1). T_n은 cold start 비율, F_p는 띄웠지만 호출되지 않은 비율, I_s는 비싼 서버와 싼 서버의 (실행 + cold start) 시간 비, M_r은 메모리 비율이고 모두 min-max 정규화한다. S_u가 2/3보다 크면 비싼 서버, 1/3–2/3이면 싼 서버에 띄우고 1/3보다 작으면 띄우지 않는다. 두 문턱값은 서버 종류별 빈 메모리 비율에 따라 움직인다(§3.2, Algorithm 1) |
| 방법 | S_u가 local window 안에서 10% 넘게 바뀌지 않으면 띄울 위치를 유지한다(ping-pong 방지). 메모리가 크고 비싼 서버 이득이 작은 함수는 다음 window에 비싼 서버에서 띄운다(§3.3) |
| 가정·조건 | OpenWhisk와 Docker. 기본 구성은 비싼 서버 m5n($0.01475/GB/hour) 10대와 싼 서버 t4g($0.0084/GB/hour) 18대이고 두 종류에 예산을 반씩 쓴다(§4). 호출 간격은 Azure Functions trace(2주), 실행 시간과 cold start는 가장 가까운 ServerlessBench 응용을 쓴다. 비교군 Wild와 FaasCache는 비싼 서버를 먼저 쓰도록 고쳤다. Deadline은 없다(§4) |

## 결론

- 기본 구성에서 OpenWhisk 대비 keep-alive cost를 60% 넘게(본문 66%) 줄였고 평균 service time을 40% 넘게 줄였다. 다음으로 나은 기법은 service time을 13% 줄였고 미래 호출을 모두 아는 Oracle은 54% 줄였다(§5, Fig. 6). 95번째 백분위 service time은 36% 줄었다
- 예측: cold start 시간 감소가 Oracle과 6% 차이였다(Fig. 8). 비싼 서버에서 띄웠지만 호출되지 않은 warm-up 비용은 OpenWhisk보다 65% 넘게 줄었다(Fig. 9(b)). 예측 부담은 1분 interval마다 30 ms 미만이었다. LSTM으로 바꾸면 부담이 243배가 되고 이득은 조금 늘었다(§5, Fig. 11)
- 서버 구성을 비싼 서버 20대부터 싼 서버 35대까지 같은 예산으로 바꿔도 Wild와 FaasCache보다 service time이 짧았다(Fig. 12). 비용 비 1.23배(t3 대 t4g)에서도 keep-alive cost 17%, service time 14%를 줄였다(Fig. 13 설명)
- 평가 방식: AWS EC2 VM 위 OpenWhisk 실측(Azure trace의 도착 pattern, ServerlessBench 응용)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 대상(함수, 모델)마다 다음 사용 시각과 사용 수를 예측해 미리 올려 둘지 정한다 | FIP는 지난 1시간 기록을 FFT로 외삽해 주기와 호출 수를 모두 추정한다. PNU-Count는 주기 32 ms와 nominal offset O_m = m × 0.8 ms가 정해져 있어 주기를 추정하지 않는다. 분포는 nominal 시각보다 늦어지는 폭(모델 그룹 지연, 추론 요청별 지연)만 맡고 수는 Host가 `n_expect`로 알려 준다(04 §3.1) | [구조] 주기와 예상 수를 과거 기록에서 추정하지 않는다. Host가 Offset Assignment로 도착 기준 시각을 정하고 그 주기의 추론 요청 수를 packet에 싣는다 |
| 쓰일 가능성이 높은 대상을 빠른 자리에 둔다 | IceBreaker는 가능성이 낮으면 자리가 남아도 띄우지 않거나 싼 서버에 둔다. 메모리 종류가 둘이고 목표는 keep-alive cost와 service time이다. PNU-Count는 BRAM entry 4개가 모자랄 때만 다음 사용이 가장 늦은 모델 하나를 내보내고 목표는 DDR3 traffic이다 | 없음. 문제가 다르다. 이종 서버 배치와 keep-alive 비용은 이 연구에 없다 |

## 인용할 때

- Roy 등이 먼저 했다: 함수 호출 수 시계열의 주기를 Fourier 변환으로 찾아 다음 호출과 동시 호출 수를 예측하는 것, 호출 가능성 점수로 비싼 서버와 싼 서버에 나눠 미리 띄우는 것. 저자는 이종 서버를 섞어 serverless 함수를 띄우는 연구가 처음이라고 적었다(§1, §7). 주기 예측으로 미리 적재하는 것 자체는 신규성으로 주장하지 않는다. Prefetch와 다음 사용 시점 교체도 주장하지 않는 범위다(09 §3)
- 근거 위치: 동기 §2(Table 1, Fig. 2), FIP §3.1(Fig. 4–5), utility score §3.2(Eq. 1, Algorithm 1), 안전장치 §3.3, 구현 §3.4, 실험 조건 §4, 결과 §5(Fig. 6–14)
- 주의: 초록은 keep-alive cost를 45%, "execution time"을 27% 줄였다고 적었다. 본문(§1, §5)에서 45%와 27%는 OpenWhisk 대비 개선율이 다음으로 나은 기법보다 큰 폭(%p)이고 27%의 대상은 service time이다. OpenWhisk 대비 값은 60% 넘게(66%)와 40% 넘게다
- 주의: 비싼 서버만 쓴 구성에서는 keep-alive cost가 25% 늘었다고 적었고 비교 기준은 밝히지 않았다(§5, Fig. 12 설명). 비용 비 실험은 1.3–2.4배라고 했지만 본문 예에는 1.28배와 1.23배가 있다
- 주의: 결정 단위가 1분 interval과 1시간 window다. 이 연구의 32 ms 주기, 0.8 ms offset 간격과 시간 규모가 다르다
- 비교군: 옮기지 않았다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
