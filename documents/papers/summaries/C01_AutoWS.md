# C01: AutoWS

원문: `C01_AutoWS_weight_streaming.pdf`
Yu, Bouganis, 2023

## 1. 문제

Layer-pipeline accelerator는 weight를 모두 on-chip에 두면 memory가 부족할 수 있다. AutoWS는 weight 일부만 상주시키고 나머지를 stream한다.

## 2. 방법

- layer weight를 fragment로 나눔
- 일부는 on-chip에 고정
- 나머지는 shared double buffer로 DMA
- layer별 burst 수를 맞춰 DMA 대기 감소
- memory를 확보할 때 추가 bandwidth가 작은 layer부터 선택

Layer 실행 순서가 고정돼 있어 transfer schedule도 정적이다.

## 3. 결과

ResNet-18, ZCU102:

| 항목 | 전체 on-chip | AutoWS |
|---|---:|---:|
| Weight memory | 8.3 MB | 4.6 MB |
| 전체 on-chip memory | 8.7 MB | 5.1 MB |
| Device 대비 | 172 % | 99 % |
| Off-chip bandwidth | 0.1 Gbps | 105.1 Gbps |
| Throughput | 141 FPS | 142 FPS |

MobileNetV2/Zedboard에서는 AutoWS가 325.9 ms, sequential layer 방식이 8.3 ms였다. Bandwidth가 부족하면 streaming이 불리할 수 있다.

## 4. 우리 연구에 쓰는 범위

비교 대상:

- 소수 모델 전체 cache
- 모든 모델 일부 상주
- 두 방식을 합친 hybrid

첫 layer가 준비되자마자 계산을 시작할 수 있지만, 총 weight byte가 줄어드는 것은 아니다. L2가 전체 weight의 75.5 %라 뒤에서 다시 기다릴 수 있다.

차이:

- AutoWS는 단일 모델과 정적 layer schedule을 쓴다.
- 우리는 비동기 다중 모델 추론 요청과 deadline을 다룬다.
- 어느 모델을 먼저 실행할지는 AutoWS 범위 밖이다.

부분 상주와 prefetch 자체를 신규성으로 주장하지 않는다. 같은 BRAM에서 transfer byte, 시작 시각, 완료 시각을 비교하는 방법을 참고한다.

원문 확인: 구조 §III~IV, 결과 표 2~3·그림 6~7.
