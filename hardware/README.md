# hardware/ 구성

갱신일: 2026-10-09

| 폴더 | 내용 |
|---|---|
| `src/` | 가속기 RTL(P4). 선행 `plift_core.v` 재사용분 포함 예정. 현재 비어 있음 |
| `testbench/` | RTL testbench(xsim). 현재 비어 있음 |
| `sim/` | xsim 작업·출력 폴더(산출물, 커밋하지 않음). 시뮬레이터는 프로젝트 루트에서 실행하고 `$readmemh` 경로는 루트 기준 상대경로로 쓴다. `p3_core` 검증: `bash hardware/board_test/p3_meas/run_tb.sh` |
| `constraints/` | 보드 XDC `ax7a200b_{base,io,ddr3,pcie}.xdc` |
| `vivado/` | 프로젝트 생성·합성·구현 스크립트 `create_project.tcl` |
| `board_test/` | Phase 1 보드 시험 설계: `p05_blink/`(LED·VIO), `p06_mig/`(DDR3 MIG), `p07_xdma/`(PCIe XDMA). Phase 3 측정 설계: `p3_meas/`(MIG + DDR3 트래픽 생성기 + XDMA + 레지스터, `-fit`은 온칩 메모리 골격 배치 확인). `host/`(Host 쪽 스크립트: 적재 `p3_load.sh`, 레지스터 `p3_regs.py`, DDR3 측정 `p3_ddr_bench.py`, PCIe 지연 `pcie_lat.c`·`p3_pcie_bench.sh`) |
| `data/models/` | P2.6 INT8 모델 40개의 BIN·HEX·132 KiB DDR3 슬롯, 전체 이미지와 manifest |
| `data/golden/` | P2.7 정상·이상 실데이터 골든 80개, 포화 stress 2개, P4.1 `$readmemh`용 대표 HEX |

보드 시험 절차와 결과는 [ENVIRONMENT.md](../documents/design/ENVIRONMENT.md) §5~6을 따른다.
모델 주소·파일 형식은 [MODEL_MEMORY_LAYOUT.md](../documents/design/MODEL_MEMORY_LAYOUT.md)를 따른다.
온칩 메모리 구성과 BRAM 예산은 [ONCHIP_MEMORY.md](../documents/design/ONCHIP_MEMORY.md)를 따른다.
