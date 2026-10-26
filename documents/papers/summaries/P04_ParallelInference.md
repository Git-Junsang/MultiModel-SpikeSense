# P04: Parallel Inference

원문: `P04_Samsung_ParallelInference_US12223444B2.pdf`
출원인 삼성전자, 연세대학교 산학협력단(Samsung Electronics Co., Ltd., Industry-Academic Cooperation Foundation, Yonsei University), 발명자 Ho Young Kim, Won Woo Ro, Sung Ji Choi, 공개 번호 US 2022/0237487 A1(2022-07-28), 우선일 2021-01-25(KR 10-2021-0010439), 등록일 2025-02-11(US 12,223,444 B2)
읽은 범위: Google Patents 본문 글 전체(요약, 명세서, 청구항 20개). 받은 PDF는 이미지라 글자가 없어 대조하지 않았다

## 한 줄 요약

Inference task의 layer를 compute array 크기의 sublayer group으로 나눠 schedule하는 가속기 특허다. Weight를 공유하는 group은 compute array를 나눠 함께 돌리고 공유 group이 없으면 weight 전송 예측 시간이 첫 group의 연산 예측 시간보다 짧은 group을 남는 compute array에 올려 전송과 연산을 겹친다. 실험은 없다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 여러 inference task를 compute array 여러 개로 함께 처리하면서 노는 compute array를 줄이고 weight 전송을 연산과 겹쳐 자원 효율을 높인다(FIG. 1·9 설명) |
| 방법 | 청구항 1 요지: group 중 첫 group의 weight를 공유하는 group이 있는지 본다. 없으면 노는 compute array가 있는지 본다. 있으면 메모리 time(weight 전송 시간)이 첫 group의 computation time과 겹치는 둘째 group을 고른다(청구항 1·7) |
| 방법 | Host가 compiler 실행 중에 layer를 compute array 크기(예: 128 × 128)에 맞춰 sublayer로 나누고 layer마다 sublayer를 compute array 수(예: 16개)까지 묶어 group을 만든다. Group마다 weight 전송 예측 cycle(MB), 연산 예측 cycle(CB), weight·입력 주소, 의존 정보를 scheduling table에 적어 가속기로 보낸다(FIG. 2·3, Table 1·2) |
| 방법 | 우선순위가 가장 높은 group을 고른다. Weight 주소 범위가 같은 group이 있으면 compute array를 나눠(group이 셋이면 16개를 6·5·5개로) 함께 돌린다. Weight fetcher는 첫 group의 weight를 compute array 1–16에 보내고 입력은 group마다 따로 보낸다(연산 610–630, FIG. 7, Table 3의 7행) |
| 방법 | 공유 group이 없으면 의존이 없는 group을 후보 queue에 넣는다. 후보 queue의 첫 group이 세 조건(sublayer 합 ≤ compute array 수, MB cycle < SRAM_C, MB cycle < 첫 group의 CB cycle)을 만족하면 둘째 group으로 고른다. SRAM_C는 on-chip 메모리 남은 용량만큼 옮기는 예측 시간이다. Compute array가 남으면 셋째 group도 고른다. 이때는 첫 group의 CB cycle에서 둘째 group의 MB cycle을 뺀 값과 비교한다(청구항 5·8·9, 연산 640·650, FIG. 9–11) |
| 가정·조건 | DNN 가속기(NPU). Compute array는 weight stationary systolic array이고 on-chip 메모리(scratchpad, SRAM)와 외부 메모리(DRAM, HBM)를 쓴다. Inference task 사이 순서는 우선순위로 정한다(FIG. 1·4·12 설명). 원문에 주기, deadline, 도착 시각 조정이 나오지 않는다 |

## 결론

- 명세서가 밝힌 효과: weight를 공유하는 group을 우선 함께 처리하고 한 group의 연산 시간에 다른 group의 weight 전송 시간을 겹쳐 자원 효율이 좋아진다(FIG. 1 설명, FIG. 9·11 설명). 우선순위가 높은 inference task를 먼저 처리하면서 여러 task를 함께 돌린다(FIG. 12)
- 실험, simulation, 수치가 없다. Compute array 16개와 128 × 128은 예시다
- 평가 방식: 없음(특허 명세서)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 weight를 쓰는 작업을 함께 처리해 weight를 한 번 가져와 여러 입력에 쓴다 | P04는 queue에 있는 group 중 weight 주소 범위가 같은 group을 찾아 compute array를 나눠 동시에 돌린다. 이 연구의 Grouping은 이미 도착한 같은 모델 추론 요청을 batch로 묶어 weight 적재 한 번으로 이어서 처리한다. 기다리거나 선점하지 않는다 | [구조] Model-Grouped Offset Assignment로 같은 모델 추론 요청이 함께 생기게 해 묶을 기회를 Host에서 만든다. P04 명세서에는 inference task가 생기는 시각을 정하는 방법이 없다 |
| 연산하는 동안 다음 weight를 옮겨 전송 시간을 가린다 | P04는 Host가 적어 둔 전송·연산 예측 cycle을 비교해 겹칠 group을 고른다. 이 연구는 연산하는 동안 다음 batch 모델 전체를 빈 entry로 prefetch하고 빈 entry가 없으면 PNU-Count가 내보낼 모델을 고른다(04 §3) | 없음. 연산과 전송을 겹치는 prefetch 자체는 주장하지 않는 범위다(09 §3) |

## 인용할 때

- 삼성전자·연세대(Kim·Ro·Choi)가 먼저 했다: 여러 inference task의 group 중 weight를 공유하는 group을 찾아 함께 처리하는 scheduler, 남는 compute array에 weight 전송 시간이 연산 시간과 겹치는 group을 올리는 방법. 같은 모델의 묶음 처리·weight 공유와 prefetch 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: 청구항 1·5·8·9, 요약, FIG. 6(연산 610–660), FIG. 7(공유 group 병렬), FIG. 9–11(겹치기), FIG. 13(연산 1310–1350), Table 3·4(dynamic scheduling algorithm), FIG. 2·3(group과 scheduling table)
- 주의: group은 추론 요청 묶음이 아니라 한 layer를 compute array 크기로 나눈 sublayer 묶음이다(FIG. 2). 이 연구의 batch, 모델 그룹과 다르다
- 주의: 청구항 1이 권리로 적은 동작은 공유 group이 없을 때 겹칠 group을 고르는 것이다. 공유 group을 함께 돌리는 동작(연산 630)은 명세서에만 있고 청구항에는 판단 조건으로만 나온다
- 주의: 단·행 번호와 Google Patents 글의 글자 오류는 확인하지 못했다. 위치는 그림·연산·표·청구항 번호로 적었다
- 비교군: 옮기지 않았다
