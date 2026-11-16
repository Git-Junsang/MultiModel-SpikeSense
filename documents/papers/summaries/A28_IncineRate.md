# A28: IncineRate

원문: `A28_IncineRate_MCSoC2025.pdf`
Björn A. Lindqvist, Artur Podobas, IEEE MCSoC 2025, pp. 165–172, DOI 10.1109/MCSoC67473.2025.00035
읽은 범위: 원문 전체

## 한 줄 요약

OpenCL(HLS)로 만든 FPGA 가속기 framework다. AlexNet·VGG16·ResNet18을 ANN(ReLU·QCFS) 또는 SCNN(IF 뉴런)으로 돌린다. Network 구조와 timestep 수를 실행 중에 정하므로 FPGA를 재구성하지 않고 여러 network를 돌릴 수 있다고 쓴다. Agilex 7에서 CIFAR-10 ResNet18은 T = 16에서 95.6%, 10 FPS였다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 상용 neuromorphic hardware(Loihi, TrueNorth)는 CNN layer를 지원하지 않아 SCNN을 hardware에서 재기 어렵다. 기존 FPGA SCNN 가속기는 지원하는 network·layer·timestep이 제한된다(§I, §IV) |
| 방법 | PyTorch network를 OpenCL kernel 호출 순서(task schedule)로 바꾸고 차례로 실행한다. Network 구조, timestep 수 등은 실행 중에 정한다(초록, §III-A) |
| 방법 | 16 × 16 PE의 output-stationary systolic array(PE마다 cycle당 MAC 8개)가 convolution·FC를 맡는다. im2col로 행렬을 만들고 tile을 double-buffered on-chip 메모리에 둔다. Feature map은 off-chip ping-pong buffer에 둔다(§III-A, §III-C, §III-D) |
| 방법 | ANN을 QCFS activation으로 학습한 뒤 IF 뉴런(soft reset)으로 바꾼다. Weight와 feature map은 single-precision floating point이고 양자화하지 않는다(§II-B, §III-A) |
| 가정·조건 | Terasic DE10-Agilex(Agilex 7 AGFB014R24), off-chip 8 GB 모듈 4개, Host i9-12900K와 PCIe. 실험은 network·mode마다 따로 합성한 설계 9개로 했다(Table I). 모델 전환 비용, weight 적재 순서, 주기 deadline, 입력 stream은 원문에 나오지 않는다 |

## 결론

- 자원(설계 9개): ALM 60–64%, DSP 53–55%, M20K 28–30%, clock 475–531 MHz다. Clock은 주로 합성 seed에 따라 달라진다(§V-A, Table I)
- CIFAR-10 ResNet18은 ReLU mode 96.7%·200 FPS, SNN mode T = 4 91.6%·38 FPS, T = 16 95.6%·10 FPS다. CIFAR-100 ResNet18 T = 16은 78.0%·10 FPS다. SNN mode에서 T가 두 배가 되면 FPS가 약 절반이 된다(§V-A, Table II)
- 추론 시간은 systolic array가 약 절반이고 그다음이 membrane potential 갱신이다. im2col/tile이 약 25%다(§V-A, Fig. 4)
- 평가 방식: 보드 실측(DE10-Agilex, Host i9-12900K, PCIe)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| FPGA 하나가 재구성 없이 여러 SNN 모델을 돌리려 한다. 연산은 output-stationary array가 맡는다 | IncineRate는 Host가 network 하나의 task schedule을 실행하고 모델 전환 비용과 weight 적재 순서를 다루지 않는다. 이 연구는 구조가 같은 모델 40개가 batch마다 바뀐다 | [구조] PNU-Count로 다음에 쓸 모델을 entry에 남기고 Grouping으로 같은 모델 추론 요청을 묶어 weight 재적재를 줄인다 |
| Host가 입력을 FPGA로 보낸다 | IncineRate는 Host와 PCIe로 잇고 입력은 image이며 주기 deadline이 없다. 이 연구는 트랙 1,024개가 32 ms마다 추론 요청을 낸다 | [구조] Model-Grouped Offset Assignment로 같은 모델 추론 요청이 함께 생기게 한다 |
| membrane potential을 갱신한다 | IncineRate는 입력 사이에 state를 이어 가는 내용이 없다. 이 연구는 트랙마다 state를 추론 요청 사이에 이어 간다 | [구조] 12 bit Membrane Storage로 768트랙의 state를 BRAM에 둔다 |
| 여러 network를 지원한다 | IncineRate는 구조가 다른 CNN·SCNN과 timestep 수를 실행 중에 바꾼다. 이 연구의 모델 40개는 구조가 같고 weight만 다르다 | 없음. Network 구조 유연성은 IncineRate가 넓다 |

## 인용할 때

- Lindqvist·Podobas가 먼저 했다: 한 FPGA 설계에서 network 구조와 timestep 수를 실행 중에 정해 여러 SCNN과 ANN을 돌리는 framework. 원문은 OpenCL(HLS) 기반 end-to-end SCNN framework로서 "to the best of our knowledge, the first"라고 쓴다(§I 기여). 여러 SNN 모델을 한 FPGA에서 돌리는 것 자체는 신규성으로 주장하지 않는다
- 근거 위치: 실행 중 설정 초록·§III-A, systolic array §III-C, im2col §III-D, 자원 Table I, 정확도·FPS Table II·Fig. 3, 시간 구성 Fig. 4, 다른 가속기 비교 Table III·IV
- 주의: 제목의 "Multi-Modal"은 CNN과 SCNN을 함께 돌린다는 뜻이다(§I 기여). 여러 sensor 입력이나 여러 모델 동시 실행이 아니다
- 주의: 실험은 network·mode마다 따로 합성한 설계 9개로 했고 합성할 component는 지원할 network에 맞춰 고른다(§III-A, Table I). 한 bitstream에서 network를 바꾼 시간이나 결과는 없다. P3.18 §3.2 표는 "재구성 없이 여러 SCNN을 실행"이라고 적었다
- 주의: Weight를 어디에 두는지는 따로 적지 않는다. VGG16 parameter 1억 3,800만 개는 가장 큰 FPGA의 on-chip 메모리에도 들어가지 않는다고만 쓴다(§II-G)
- 주의: 원문은 SNN mode 속도가 T에 "proportional"하다고 쓰지만 Table II의 FPS는 T에 반비례한다
