# A16: SNN dataflow

원문: `A16_IdentifyingDataflows_SNN.pdf`
Sharma, Ankit, Roy, ISLPED 2022

## 1. 문제

SNN에는 input, weight, output 외에 membrane potential과 timestep이 있다. ANN dataflow에 시간 loop만 더하면 메모리 이동을 제대로 줄이지 못할 수 있다.

## 2. 방법

논문은 세 가지 규칙을 제안한다.

1. 같은 작업의 여러 timestep을 연속 처리해 membrane state를 재사용한다.
2. PE 주변의 작은 buffer에 맞게 tile을 고른다.
3. 시간축 일부를 더 가까운 메모리 level로 옮긴다.

한 메모리의 traffic만 줄이면 다른 level의 traffic이 늘 수 있다. 전체 energy와 latency를 함께 봐야 한다.

## 3. 결과

Timeloop 기반 분석이다. FPGA 보드 실측이 아니다.

- SNN loop order는 ANN의 7!에서 8!로 늘어난다.
- Hardware와 workload에 따라 최적 dataflow가 달랐다.
- 일부 조건에서 baseline보다 EDP가 최대 98% 줄었다.

최대 개선값을 모든 SNN에 적용하면 안 된다.

## 4. 우리 연구에 쓰는 범위

512트랙의 membrane state는 다음과 같다.

```text
512 × 706 × 2 B = 722,944 B = 706 KiB
```

트랙이 늘면 state BRAM이 늘고 모델 cache가 줄어든다. A16은 이 공간 경쟁을 분석해야 한다는 근거다.

차이:

- A16은 단일 모델의 내부 dataflow를 다룬다.
- 우리는 모델·트랙 단위 scheduling을 다룬다.
- 미래 timestep이 아직 없어 temporal batching을 그대로 쓸 수 없다.

Membrane pressure와 temporal reuse 자체는 신규성이 아니다. 우리 기여 범위는 다중 트랙 state와 모델 cache의 결합 효과다.

원문 확인: 문제 §2, 규칙 §3.3, 평가 §4–5.
