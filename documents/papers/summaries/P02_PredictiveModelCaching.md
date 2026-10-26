# P02: Predictive Model Caching

원문: `P02_Google_PredictiveModelCaching_US8626791B1.pdf`
출원인 Google Inc.(지금은 Google LLC), 발명자 Wei-Hao Lin, Travis H. K. Green, Robert Kaplow, Gang Fu, Gideon S. Mann, 공개 번호 없음(출원 공개 없이 US 8,626,791 B1로 등록), 우선일 2011-06-14(US 13/159,882 출원일), 등록일 2014-01-07. 발명자 이름은 PDF 글자가 깨져 Google Patents로 확인했다. 공개 이력도 Google Patents 기준이다
읽은 범위: 청구항 19개, 요약, col. 1–2(배경·Summary), col. 10–14(FIG. 3·4). Col. 2–10(FIG. 1·2의 platform 설명)은 caching 글이 없는 것만 확인

## 한 줄 요약

과거 추론 요청(원문 predictive request)의 시각과 답한 모델 ID로 scheduling model을 학습해 목표 시각에 쓰일 가능성이 높은 모델을 secondary 메모리에서 primary 메모리로 미리 올리는 특허다. 실험은 없다. 명세서는 적재 시간이 처리 시간에서 빠져 response time이 준다고 적었다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | primary 메모리에 없는 모델은 secondary 메모리에서 찾아 올린 뒤에야 추론 요청을 처리하므로 response time이 길어진다(col. 11) |
| 방법 | 청구항 1 요지: 학습된 모델들을 ID와 함께 secondary 메모리에 둔다. 한 사용자(first user)가 낸 과거 추론 요청의 시각과 답한 모델 ID 기록으로 그 사용자 전용 scheduling model을 학습한다. 이 scheduling model로 목표 시각에 추론 요청을 받을 가능성이 가장 높은 모델 집합을 찾는다. 그중 가능성이 더 높은 모델을 골라 volatile primary 메모리에 저장한다(청구항 1) |
| 방법 | 목표 시각은 날짜, 요일, 하루 중 시각과 그 조합이다(청구항 2). 예: 6월 1일(수요일) 오전 9:00에 쓰일 모델 집합을 예측해 cache 316에 올린다. Scheduling model은 사용자 그룹(같은 회사 등), 지역, 모델 하나마다 따로 둘 수 있다. 함께 쓰이는 모델을 찾는 scheduling model도 있다(col. 12, 청구항 12·17) |
| 방법 | primary 메모리가 모자라면 덜 쓰이거나 목표 시각에 쓰일 가능성이 낮은 모델을 내보내거나 처음부터 올리지 않는다. 최근 5분 안에 추론 요청을 받은 모델은 남기는 예와 모델 크기를 쓰일 가능성과 견주는 예가 있다(col. 13, 청구항 15·16) |
| 가정·조건 | cloud의 predictive modeling server(데이터 센터). Secondary 메모리는 non-volatile(hard drive, flash), primary 메모리는 volatile(RAM, DRAM)이다. 사용 기록은 한 달에서 여러 해까지 모은다. 원문에 주기, deadline, 묶음 처리가 나오지 않는다(col. 1, col. 11–13, 청구항 1) |

## 결론

- 명세서가 밝힌 효과: 추론 요청 전에 모델을 primary 메모리에 올려 두면 secondary 메모리에서 읽는 시간이 처리 시간에서 빠져 지연이 줄거나 없어진다(col. 12 끝, col. 14). 메모리와 계산 자원을 효율적으로 쓴다(col. 2)
- 실험, simulation, 수치가 없다
- 평가 방식: 없음(특허 명세서)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 과거 기록으로 다음에 쓸 모델을 예측해 미리 올린다 | P02는 시각과 모델 ID 기록으로 학습한 scheduling model이 날짜·요일·시각 단위로 쓸 모델 집합을 고른다. PNU-Count는 queue, 모델 그룹 지연 분포, 추론 요청별 지연 분포, n_expect로 모델마다 32 ms 주기 안의 다음 사용 시각을 예측한다 | [구조] 모델마다 nominal frame 끝 시각을 Host가 정해 둔다(Model-Grouped Offset Assignment). 분포는 그 시각보다 늦어지는 폭만 맡는다. Host가 추론 요청 packet에 n_expect를 실어 보내므로 FPGA가 이번 주기에 남은 추론 요청 수를 안다 |
| 자리가 모자라면 쓰일 가능성이 낮은 모델을 내보낸다 | P02는 덜 쓰이거나 목표 시각에 쓰일 가능성이 낮은 모델을 고르고 메모리 크기는 정하지 않는다. PNU-Count는 entry 4개 안에서 다음 사용 예측이 가장 늦은 모델 하나를 고른다 | 없음. 다음 사용 예측으로 내보내는 원리는 같다 |

## 인용할 때

- Google(Lin 등)이 먼저 했다: 과거 추론 요청의 시각과 모델 ID로 목표 시각에 쓸 모델을 예측해 빠른 메모리에 미리 올리고 쓰일 가능성이 낮은 모델을 내보내는 것. 다음 사용 예측에 따른 미리 적재는 신규성으로 주장하지 않는다. Prefetch와 다음 사용 시점 교체 원리 자체도 주장하지 않는 범위다(09 §3)
- 근거 위치: 청구항 1(사용자 전용), 2(목표 시각 종류), 12(함께 쓰는 모델), 15·16(내보내기), 17(지역 전용), 요약, FIG. 3 설명 col. 10–13(기록 항목 col. 11, 6월 1일 예 col. 12, 교체와 5분 예 col. 13 앞부분), FIG. 4 단계 402–410(col. 13–14)
- 주의: 등록 청구항은 요약보다 좁다. 독립항 1·4·8은 한 사용자 전용 scheduling model, 17–19는 한 지역 전용 scheduling model로 한정된다. 한정 없는 형태는 요약과 명세서에만 있다
- 주의: 예측 단위가 날짜·요일·시각이고 메모리 계층은 disk·flash에서 DRAM으로 가는 cloud server다. 이 연구의 32 ms 주기, DDR3에서 BRAM으로 가는 적재와는 시간 단위와 계층이 다르다
- 비교군: 옮기지 않았다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
