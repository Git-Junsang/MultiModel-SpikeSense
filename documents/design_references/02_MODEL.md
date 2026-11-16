# 02. 모델

## 1. 요약

장비 ID 40개에 PLIF SNN 모델을 하나씩 둔다. 모델 구조는 모두 L `40→384→256→64→2`이고 weight만 다르다. 입력은 40차원 mel이고, 출력은 정상·이상에 대응하는 값 2개다. 가속기는 INT8 weight와 16 bit membrane potential로 정수 연산을 수행한다. 연산 결과는 software reference(`snn_int8.py`)와 bit 단위로 일치해야 한다.

## 2. 구조

| 항목 | 값 |
|---|---|
| layer | `40→384→256→64→2`, weight layer 4개, bias 없음 |
| weight | 130,176 B (INT8) |
| 뉴런 | 706개 (384 + 256 + 64 + 2), PLIF |
| 뉴런 파라미터 | 뉴런마다 누설 계수 β와 threshold vth를 학습 |
| 갱신 순서 | 누설 → 적분 → 발화 → soft reset (발화하면 vth만큼 뺌) |
| 출력 | layer 4 membrane potential 2개. 0 = 정상, 1 = 이상 |

모델 크기는 P3.6에서 정했다. L보다 작은 모델 4개(XS, P, S, M)는 장비 40대의 평균 AUC가 L보다 0.007–0.029 낮았다. XL은 L보다 평균 AUC가 0.005 높았지만, 차이의 신뢰구간이 0을 포함했다. 미리 정한 채택 기준인 소리 겹침 조건의 AUC 개선 폭 +0.01도 넘지 못했다([P3.6~P3.8 보고서](<../reports/P3.6~3.8 Research Report.md>), [P3.9 보고서](<../reports/P3.9 Research Report.md>)).

## 3. 데이터와 학습

| 항목 | 값 |
|---|---|
| dataset | DCASE 2020 Task 2 배포 데이터만 쓴다. 개발용과 평가용을 합치면 6종 장비의 41개 ID다 |
| 모델 선택 | test 결과를 본 뒤 ROC-AUC가 0.738로 가장 낮은 `fan_id00`을 빼 40개로 정했다 |
| 특징 | 16 kHz, FFT 1,024, hop 512 (32 ms), mel 40, 파일 단위 `power_to_db(ref=max, top_db 80)` → [0, 1] |
| 학습 단위 | frame 31개(992 ms)로 구성한 구간. 학습 구간만 frame 16개씩 겹치게 자른다 |
| 데이터 분할 | 지도학습: 정상 학습 파일과 test 이상 파일의 절반으로 학습하고, 나머지 이상 파일과 test 정상 파일 전체로 평가한다 |
| 손실 | focal loss. 파일 안 구간 출력을 평균해 파일 하나를 학습 단위 하나로 본다 |
| 최적화 | Adam, lr 0.002, cosine 감쇠, batch 512, 60 epoch, seed 42 |
| 채택 checkpoint | 마지막 epoch (`last.pth`) |

정상 데이터만 학습에 쓰는 DCASE 원 과제와 조건이 달라 challenge 성능과 직접 비교하지 않는다.

모델 선택에 test 결과를 썼으므로 선택 편향이 있다. 장비 ID 41개 전체의 평균 FP32 AUC는 0.9510이다. 정확도 결과는 가속기에 올릴 정수 모델을 확인하는 용도로만 쓴다.

| 형식 (`L_normal_noaug`, 40개) | 평균 ROC-AUC (파일 단위) | AUC 0.9 이상 |
|---|---:|---:|
| FP32 | 0.9563 | 35/40 |
| INT8, membrane potential 16 bit 저장 | 0.9554 | 35/40 |
| INT8, membrane potential 12 bit 저장 | 0.9554 | 35/40 |

INT8 양자화로 평균 AUC가 0.0009 줄었다. Membrane potential을 12 bit로 저장해도 모델 40개 모두 16 bit로 저장했을 때와 판정이 같았다. 저장한 state 값까지 같다는 뜻은 아니다.

현재 export한 모델은 `L_normal_noaug`다. Checkpoint를 바꿔도 export 형식과 RTL은 그대로다.

## 4. 정수 규칙

정수 연산은 [snn_int8.py](../../software/model/snn_int8.py)와 같다.

```text
입력                x_q   = clip(round(mel × 127), 0, 127)
weight              W_q   = clip(round(W / s_l), −128, 127),  s_l = max|W_l| / 127 (layer별 대칭)
누설 계수           β_q   = clip(round(β × 256), 0, 255)       Q0.8
threshold           vth_q = round(thr / s_l)                    uint8
layer 1 전류        cur   = (Σ x_q · W_q) >> 7                  산술 shift(내림)
layer 2~4 전류      cur   = Σ spike · W_q
membrane potential  mem   = sat16(((β_q · mem) >> 8) + cur)
발화                spike = mem ≥ vth_q ;  mem −= spike · vth_q
저장                mem_s = clip(mem, −2,048, 2,047)            12 bit, 다음 추론으로 넘길 때만
```

누산기는 layer 1에 부호 포함 21 bit 이상이 필요하다(40 × 127 × 128). 선행 `plift_core.v`는 16 bit를 넘으면 wrap-around되므로 포화로 바꿨다(P4.1).

Membrane potential은 16 bit 포화 연산으로 계산한다. 다음 추론으로 넘길 state를 저장할 때만 12 bit로 포화한다. 저장 폭을 10 bit로 줄이면 평균 AUC 변화는 −0.0002였다. 8 bit(아래 2 bit 버림)에서는 평균 변화가 −0.0008이었지만, 장비 4대의 AUC가 0.01–0.02 떨어졌다([P3.13 보고서](<../reports/P3.13 Research Report.md>) §4).

## 5. 판정

Host가 학습·golden과 같은 규칙으로 판정한다.

| 항목 | 규칙 |
|---|---|
| 판정 주기 | 트랙마다 이어진 추론 요청 31개(992 ms). 겹치지 않는다. 31개 frame이 담는 음성은 64 + 30 × 32 ms = 1,024 ms다 |
| 초기화 | 판정 주기의 첫 추론 요청에서 membrane potential을 0으로 시작(`RESET_STATE`) |
| 판정 | `out0`와 `out1`을 각각 31개씩 평균한 뒤 큰 쪽을 선택 |
| 이상 점수 | 각 출력 평균에 layer 4 scale을 곱하고 softmax를 적용한 P(이상). Scale은 `metadata.json`의 `weight_scales[3]` |
| 결과 누락 | 그 판정 주기는 판정하지 않고 따로 센다. 다음 판정 주기는 `RESET_STATE`로 새로 시작 |

판정 주기 992 ms와 frame 하나의 deadline 32 ms는 다른 시간이다.

학습 특징은 파일 단위로 정규화했다(`ref=max`). 실제 stream에서는 파일 전체의 최댓값을 미리 알 수 없다. Host는 트랙마다 mel dB의 최대·최소를 정규화 기준으로 유지하고 frame이 들어올 때 갱신한다.

1. Mel dB가 트랙의 하한 F보다 작으면 F로 맞춘다. Mic 바닥 잡음과 0인 샘플은 모두 F가 된다. 기본값은 F = −80 dB다. Mic를 사용할 때는 장비를 끈 상태에서 바닥 잡음을 측정하고, 그보다 높은 값으로 F를 정한다. DCASE 소리는 −65 dB 아래로 내려가지 않으므로 F = −80 dB는 학습 특징을 바꾸지 않는다.
2. Frame의 최댓값이 F + 6 dB 이하면 무음 frame으로 본다. 이때는 정규화 기준을 갱신하지 않는다. 처음 소리가 난 frame에서 기준을 초기화한다.
3. Frame의 최댓값이 기준 최대 − 15 dB보다 작으면 조용한 frame으로 본다. 소리가 켜지거나 꺼지는 경계 frame이 여기에 해당한다. 이때는 기준 최소를 유지하고, 기준 최대만 현재 값 쪽으로 낮춘다. DCASE 정상 소리에서는 frame 최댓값의 99.9%가 기준 최대와 15.5 dB 이내의 차이를 보인다.
4. Frame의 최댓값이 기준 최대보다 높거나 최솟값이 기준 최소보다 낮으면 해당 기준을 즉시 갱신한다. 그렇지 않으면 시간 상수 τ = 5 s로 기준을 현재 frame의 값 쪽으로 이동시킨다. 판정 주기가 바뀌어도 정규화 기준은 유지한다.

정규화에 미래 frame을 쓰지 않으므로 frame 경계, deadline, 계산 시작 시각은 바뀌지 않는다. Membrane potential은 판정 주기마다 `RESET_STATE`로 초기화한다.

```text
d    = max(dB, F)                                 frame k의 d 최대·최소 = m_k, n_k
m_k ≤ F + 6이면 hi_k = hi_(k−1), lo_k = lo_(k−1)   (무음 frame)
hi_k = max(m_k, a·hi_(k−1) + (1 − a)·m_k)          a = e^(−32 ms / τ), τ = 5 s
lo_k = min(n_k, a·lo_(k−1) + (1 − a)·n_k)          m_k < hi_(k−1) − 15이면 lo_k = lo_(k−1)  (조용한 frame)
l    = max(lo_k, hi_k − 80)
x    = clip((d − l) / (hi_k − l), 0, 1)           x_q = clip(rint(127x), 0, 127)
```

다음은 `L_normal_noaug`를 재학습하지 않고 정규화 방식만 바꾼 결과다.

| 정규화 방식 | 실행 환경·입력 조건 | 평균 ROC-AUC | AUC 0.9 이상인 모델 수 |
|---|---|---:|---:|
| 파일 단위(학습 특징, 실시간 적용 불가) | software | 0.9554 | 35/40 |
| 위의 실시간 정규화 규칙 | software, 여러 파일을 한 트랙으로 이어서 처리 | 0.9539 | 36 |
| 위의 실시간 정규화 규칙 | 보드, P5.3 입력, 파일 사이 무음 | 0.9531 | 35 |

다른 정규화 방식, 각 처리를 뺐을 때의 결과는 [P2.9 보고서](<../reports/P2.9 Research Report.md>)에 있다.

## 6. Export 형식

DDR3에 올리는 모델은 64-lane slot(L) 형식이다. Slot 하나는 256 KiB이고, 앞의 131,648 B가 유효 데이터다. 모든 section은 32 B로 정렬한다. Weight 적재 시에는 유효 데이터 131,648 B를 DMA 한 번으로 읽는다.

| Section | 시작 주소 | 크기 (B) | 배치 |
|---|---:|---:|---|
| params | `0x00000` | 1,472 | 뉴런별 `{β u8, vth u8}`. layer 1 384 → layer 2 256 → layer 3 64 → layer 4 2, 끝은 0 |
| L1 | `0x005C0` | 15,360 | `(g × 40 + i) × 64 + j` = `W1[64g + j][i]` |
| L2 | `0x041C0` | 98,304 | `(g × 384 + i) × 64 + j` = `W2[64g + j][i]` |
| L3 | `0x1C1C0` | 16,384 | `i × 64 + j` = `W3[j][i]` |
| L4 | `0x201C0` | 128 | `k × 64 + j` = `W4[k][j]` |

params의 layer 시작은 0, 768, 1,280, 1,408 B이고 뉴런 n은 `시작 + 2n`에 있다. `model_id` 0–39는 [dcase_data.py](../../software/dataset/dcase_data.py)의 `UNITS` 순서다.

| 파일 (`hardware/data/models_l64/<장비>/`) | 크기 | 내용 |
|---|---:|---|
| `model.slot.bin` | 256 KiB | DDR3 slot image |
| `weights.bin`, `params.bin` | 130,176 B, 1,412 B | slot의 weight, params |
| `entry.hex` | 2,034줄 | on-chip entry, 한 줄 512 bit, lane j = bit `[8j+7:8j]` |
| `params.hex` | 706줄 | 한 줄 16 bit = `{vth, β}` |
| `metadata.json` | | ID, 주소, scale, SHA-256 |

`models.ddr3.bin`은 slot 40개를 ID 순서로 이어 붙인 10,485,760 B image다. Golden vector는 `hardware/data/golden_l64/`(16 bit 저장)와 `golden_l64_m12/`(12 bit 저장)에 있다. 각 묶음은 test 입력 80개(장비마다 정상·이상 1개)와 포화 시험 2개로 구성한다. 각 vector에는 layer별 전류, 포화 전 membrane potential, spike, reset 뒤 membrane potential을 담는다.

Export와 검증 명령은 [README](../../README.md#학습과-export)에 있다.

## 7. 관련 문서

- [P2.1~P2.2 보고서](<../reports/P2.1~2.2 Research Report.md>): dataset과 모델 선택
- [P2.3~P2.4 보고서](<../reports/P2.3~2.4 Research Report.md>): 학습
- [P2.5 보고서](<../reports/P2.5 Research Report.md>): INT8 방식
- [P2.6~P2.7 보고서](<../reports/P2.6~2.7 Research Report.md>), [P3.10 보고서](<../reports/P3.10 Research Report.md>): export와 golden
- [학습 결과 REPORT.md](../../software/train_result/L_normal_noaug/REPORT.md)
