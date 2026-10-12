# hardware

| 폴더 | 내용 |
|---|---|
| `src/` | 가속기 RTL 작업 공간 |
| `testbench/` | xsim testbench |
| `sim/` | xsim 임시 파일과 결과 |
| `constraints/` | AX7A200B XDC |
| `vivado/` | Vivado project·build script |
| `board_test/` | LED, MIG, XDMA, DDR3·PCIe 측정 설계 |
| `data/models/` | INT8 모델 40개와 DDR3 image |
| `data/golden/` | 정상·이상 80개와 saturation test 2개 |

시뮬레이터는 project root에서 실행한다. `$readmemh` 경로도 root 기준으로 쓴다.

관련 문서:

- 보드 환경과 절차: [ENVIRONMENT.md](../documents/design/ENVIRONMENT.md)
- 모델 주소: [MODEL_MEMORY_LAYOUT.md](../documents/design/MODEL_MEMORY_LAYOUT.md)
- BRAM 구성: [ONCHIP_MEMORY.md](../documents/design/ONCHIP_MEMORY.md)
