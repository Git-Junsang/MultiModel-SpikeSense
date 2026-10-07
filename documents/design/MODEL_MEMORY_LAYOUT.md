# INT8 모델 파일·DDR3 주소 레이아웃

작성일: 2026-10-07 | 형식 버전: 1 | 관련 작업: P2.6, P2.7

## 1. 공통 규칙

- 모델 ID 0~39는 `software/model_develop/dcase_data.py` 안의 `UNITS` 순서다. 정확한 표는 `hardware/data/models/manifest.json`에 기록한다.
- 가중치는 층 순서 L1→L4, 층 안에서 PyTorch Linear `[out, in]` 행 우선(뉴런 우선)이다. INT8 음수는 2의 보수 원시 바이트다.
- β는 Q0.8 `uint8`, 임계값은 가중치 층 단위의 `uint8`이다. 두 파라미터는 각각 L1→L4 뉴런 순서다.
- DDR3 모델 영역 기준 주소를 `MODEL_BASE`라고 하면 `model_id` 슬롯은 `MODEL_BASE + model_id × 0x21000`이다. `MODEL_BASE`는 P3.9 레지스터맵에서 확정한다.
- 128 B 정렬은 파일 형식의 섹션 경계일 뿐이다. 최종 DMA 슬라이스 크기는 P3.1·P3.8 측정으로 결정한다.

## 2. 모델 슬롯

모델 한 슬롯은 `0x21000 = 135,168 B = 132 KiB`다.

| 섹션 | 슬롯 오프셋 | 크기(B) | 내용 |
|---|---:|---:|---|
| L1 W | `0x00000` | 15,360 | 384×40 |
| L2 W | `0x03C00` | 98,304 | 256×384 |
| L3 W | `0x1BC00` | 16,384 | 64×256 |
| L4 W | `0x1FC00` | 128 | 2×64 |
| β | `0x1FC80` | 706 | 384+256+64+2 |
| 정렬 패딩 | `0x1FF42` | 62 | 0 |
| 임계값 | `0x1FF80` | 706 | 384+256+64+2 |
| 뒤쪽 패딩 | `0x20242` | 3,518 | 0 |

실제 가중치는 130,176 B, β·임계값은 1,412 B이다. 필요한 섹션만 전송하면 모델당 131,588 B이고, 슬롯 전체를 연속 전송하면 패딩을 포함해 135,168 B이다. 가중치 전송량 평가에서 두 방식을 구분해 기록한다.

40개 슬롯의 `models.ddr.bin`은 5,406,720 B = 5.15625 MiB다. 주소 계산에는 슬롯 크기를 쓰며, 실제 DMA 바이트 계수에는 전송한 섹션의 실제 크기를 쓴다.

## 3. 산출물

`hardware/data/models/<unit>/`:

- `weights.bin`, `weights.hex`: 패딩 없는 가중치 130,176 B. HEX는 한 줄에 1 B다.
- `params.bin`, `params.hex`: 패딩 없는 β 706 B + 임계값 706 B.
- `model.slot.bin`: 위 표의 132 KiB DDR3 슬롯.
- `metadata.json`: 모델 ID, 오프셋, 층별 스케일, SHA-256.

`hardware/data/models/manifest.json`은 40개 ID↔장비 매핑과 주소를, `models.ddr.bin`은 40개 슬롯을 ID 순서로 붙인 이미지를 담는다.

## 4. 파라미터 저장 판단

모델별 β·임계값은 DDR3 슬롯에 항상 포함한다. 이는 로딩 형식을 완결적으로 만들기 위한 것이며 매 요청마다 전송한다는 뜻은 아니다. P3에서 전부 온칩 상주, 캐시 엔트리와 함께 교체, 필요 섹션만 선택 전송을 같은 자원 예산으로 비교한다.

5개 모델의 가중치+파라미터 유효 데이터는 657,940 B = 642.52 KiB다. 슬롯 패딩까지 BRAM에 복사하는 구현은 675,840 B = 660 KiB이므로, P3.2·P3.4에서 패딩 제거와 파라미터 저장소를 확정한다.

## 5. 재생성·검증

```bash
python3 software/model_develop/export_models.py
python3 software/model_develop/make_golden_vectors.py
python3 software/model_develop/verify_p1_artifacts.py
```

`verify_p1_artifacts.py`는 40개 체크포인트를 다시 양자화해 BIN·HEX·슬롯과 비교하고, DDR3 이미지·SHA-256, 80개 실데이터 골든과 2개 포화 stress 벡터를 전수 재계산한다.
