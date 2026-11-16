# C30: TinyMem

원문: `C30_TinyMem_HotMobile2025.pdf`
Changmin Jeon, Taesik Gong, Juheon Yi, Fahim Kawsar, Chulhong Min, HotMobile 2025, 6쪽, DOI 10.1145/3708468.3711888
읽은 범위: 원문 전체

## 한 줄 요약

Tiny AI accelerator(MAX78000)에서 여러 DNN을 번갈아 돌리면 추론보다 weight 적재가 오래 걸린다는 것을 쟀다. Weight를 지우지 않고 남기기(preservation), 다음 모델 미리 적재(preloading), 2D layout packing을 모델 실행 순서와 함께 정해 throughput을 SeqLoad보다 1.97–5.01배 높였다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | MAX78000의 weight 메모리는 442 KB이고 core마다 따로 둔 2D layout이다. Layer마다 모든 core에서 같은 주소 offset을 써서 빈 자리가 많은데도 모델 여러 개를 함께 두지 못한다. 모델을 바꿀 때마다 CPU RAM에서 weight를 다시 적재한다(§1, §2.2–2.3, Fig. 1) |
| 방법 | Weight preservation: 모델을 바꿀 때 unload하지 않고 다른 모델이 덮어쓴 부분만 다시 적재한다(§3.1, Fig. 3b) |
| 방법 | Weight preloading: 가속기가 추론하는 동안 쉬는 CPU가 다음 모델의 남지 않은 weight를 지금 모델이 쓰지 않는 자리에 미리 적재한다. Layer 단위 preloading은 끊김이 잦아 쓰지 않는다(§3.1, §3.3, Fig. 3c) |
| 방법 | Weight packing과 joint optimizer: MaxRect로 모델마다 layout을 작게 묶고 네 모서리로 옮긴 후보 4개를 만든다. 4^n개 layout 조합과 의존성을 지키는 실행 순서를 모두 따져 예상 throughput이 가장 큰 것을 고른다(§3.3, Algorithm 1) |
| 방법 | 적재 시간은 k × weight 크기로 예측한다(MAX78000에서 k = 68.455 ns/byte). 추론 시간은 offline profiling 표로 예측한다(§3.3) |
| 가정·조건 | 모델들이 같은 빈도로 정해진 순서대로 번갈아 돈다. Throughput = 모든 모델의 초당 추론 수. Deadline은 없다. MAX78000 Feather board(데이터 메모리 512 KB, weight 메모리 442 KB), INT8 모델 5개, 모델 2개·3개 조합 × Small·Medium·Large(§4.1, Table 1·2) |

## 결론

- 진단: 모델 하나의 추론 시간보다 weight 적재 시간이 길다. SimpleNet-100은 적재 24.0 ms, 추론 4.58 ms이고 KwsNet은 12.1 ms, 1.44 ms다. SimpleNet-100과 TinySSD를 따로 돌리면 throughput이 186, 40 inference/s인데 번갈아 돌리면 13으로 떨어진다(§2.2, Fig. 2, Table 1)
- Throughput은 SeqLoad보다 모델 2개 조합에서 2.12–5.01배, 3개 조합에서 1.97–2.62배 높다. 기법별 평균 향상은 preservation 1.95배, packing 1.67배, preloading 1.24배다. 모델 2개 조합에서는 preloading할 빈 자리가 없어 Preservation & Packing과 결과가 같다(§4.2, Fig. 7)
- Weight 메모리가 5.3배 큰 MAX78002(모델 3개)에서는 SeqLoad 8.04, Preservation 12.77, Preservation & Preloading 13.92, TinyMem 12.81 inference/s다. Packing이 조금 낮췄다(§4.2, Table 3)
- 평가 방식: MAX78000 Feather board와 MAX78002에서 돌린 실험. Throughput을 잰 방법은 원문에 따로 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| weight 적재가 병목이다. 모델 weight 합이 on-chip 메모리보다 커서 모델을 바꿀 때마다 다시 적재한다 | TinyMem은 모델 2–3개를 정해진 순서로 번갈아 돌린다. 이 연구는 모델 40개 weight 4.97 MiB가 BRAM(약 1.6 MiB)보다 크고 추론 요청 도착에 따라 다음 모델이 정해진다 | [구조] Model-Grouped Offset Assignment와 Grouping으로 같은 모델 추론 요청을 batch로 묶어 weight 적재 한 번을 여러 추론 요청이 나눠 쓴다. TinyMem은 모델 전환 한 번에 추론 하나다 |
| 남은 weight는 다시 적재하지 않고 연산하는 동안 다음 모델을 미리 적재한다 | TinyMem은 layout과 순서를 offline에 정하고 겹친 layer 부분만 다시 적재한다. 이 연구는 entry 하나에 모델 전체를 두고 PNU-Count가 queue와 지연 분포로 다음 사용을 예측해 내보낼 모델을 고른다 | [구조] 실행 순서가 정해져 있지 않아도 PNU Cache가 실행 중에 victim을 고른다 |
| 한 가속기에서 여러 모델을 돌린다 | TinyMem의 지표는 throughput이고 deadline이 없다. 이 연구는 32 ms deadline과 response time을 본다 | 없음. 직접 비교하지 않았다 |

## 인용할 때

- TinyMem이 먼저 했다: tiny AI accelerator에서 weight 적재가 추론보다 길다는 측정, 2D weight 메모리에서 weight 남기기·미리 적재·packing과 실행 순서를 함께 정하기. Weight 적재가 병목이라는 진단과 prefetch 자체는 신규성으로 주장하지 않는다(09 §3)
- 우리 진단과의 관계: "모델 weight 합이 on-chip 메모리보다 커서 weight 적재가 병목"이라는 진단을 다른 장치에서 수치로 보인 선행이다. TinyMem은 CPU RAM에서 가속기 weight 메모리로의 복사이고 이 연구는 DDR3에서 BRAM entry로의 적재라 수치를 옮겨 쓰지 않는다
- 근거 위치: 진단 §2.2·Fig. 2·Table 1, 2D layout §2.3·Fig. 1, 기법 §3.1·Fig. 3, joint optimizer §3.3·Algorithm 1, 결과 §4.2·Fig. 7·Table 3
- 주의: 초록의 1.97–5.01배는 SeqLoad 대비다. 본문 §4.2에는 "up to 5.09×"(모델 2개 Small)도 있어 초록과 다르다
- 주의: MAX78002의 "up to 1.73×"는 Table 3의 Preservation & Preloading(13.92 ÷ 8.04)과 맞는다. TinyMem 열(12.81)은 SeqLoad의 약 1.59배다(계산)
- 주의: Table 1의 Size(MB) 열(SimpleNet-100 4.0)은 weight 메모리 442 KB보다 커서 무엇의 크기인지 확인하지 못했다. 적재 시간 24.0 ms를 k로 나누면 약 351,000 B다(계산)
- 비교군: 지금 비교군에 옮긴 것이 없다
