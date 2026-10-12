# INT8 모델 파일과 DDR3 layout

## 1. 규칙

- `model_id` 0~39는 `dcase_data.py`의 `UNITS` 순서다.
- 최종 ID와 주소는 `hardware/data/models/manifest.json`을 기준으로 한다.
- 가중치는 L1→L4 순서다. 각 layer는 PyTorch Linear `[out, in]` row-major다.
- 가중치는 INT8 two's complement다.
- β는 Q0.8 `uint8`, 임계값은 `uint8`이다.
- model slot 주소는 `MODEL_BASE + model_id × 0x21000`이다.
- `MODEL_BASE`는 P3.9 register map에서 정한다.

128 B 정렬은 file section 경계다. DMA slice 크기는 별도로 정한다.

## 2. Model slot

slot 하나는 `0x21000 = 135,168 B = 132 KiB`다.

| Section | Offset | 크기(B) | 내용 |
|---|---:|---:|---|
| L1 weight | `0x00000` | 15,360 | 384×40 |
| L2 weight | `0x03C00` | 98,304 | 256×384 |
| L3 weight | `0x1BC00` | 16,384 | 64×256 |
| L4 weight | `0x1FC00` | 128 | 2×64 |
| β | `0x1FC80` | 706 | 384+256+64+2 |
| padding | `0x1FF42` | 62 | 0 |
| threshold | `0x1FF80` | 706 | 384+256+64+2 |
| padding | `0x20242` | 3,518 | 0 |

유효 data는 131,588 B다. 가중치만 130,176 B이고 β·임계값은 1,412 B다. slot 전체를 보내면 135,168 B다. 전송량을 보고할 때 어느 값을 썼는지 표시한다.

40개 slot을 붙인 `models.ddr.bin`은 5,406,720 B다.

## 3. 파일

`hardware/data/models/<unit>/`:

| 파일 | 내용 |
|---|---|
| `weights.bin`, `weights.hex` | padding 없는 가중치 130,176 B |
| `params.bin`, `params.hex` | β와 임계값 1,412 B |
| `model.slot.bin` | 132 KiB slot |
| `metadata.json` | ID, offset, scale, SHA-256 |

`manifest.json`은 ID와 장비 mapping을 담는다. `models.ddr.bin`은 모든 slot을 ID 순서로 붙인 image다.

β·임계값을 slot에 넣었다고 매 요청마다 전송할 필요는 없다. 전체 상주, cache와 함께 교체, 필요한 section만 DMA하는 방법을 비교한다.

## 4. 재생성과 검증

```bash
python3 software/model_develop/export_models.py
python3 software/model_develop/make_golden_vectors.py
python3 software/model_develop/verify_p1_artifacts.py
```

검증 script는 checkpoint를 다시 양자화해 BIN, HEX, slot, DDR3 image, SHA-256을 비교한다. 실데이터 80개와 saturation test 2개도 다시 계산한다.
