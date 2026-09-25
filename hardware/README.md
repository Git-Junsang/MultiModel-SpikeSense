# hardware/ 구성

갱신일: 2026-09-23

| 폴더 | 내용 |
|---|---|
| `src/` | 가속기 RTL(P3). 선행 `plift_core.v` 재사용분 포함 예정. 현재 비어 있음 |
| `testbench/` | RTL testbench(xsim). 현재 비어 있음 |
| `sim/` | xsim 작업·출력 폴더. 시뮬레이터는 프로젝트 루트에서 실행하고 `$readmemh` 경로는 루트 기준 상대경로로 쓴다 |
| `constraints/` | 보드 XDC `ax7a200b_{base,io,ddr3,pcie}.xdc` |
| `vivado/` | 프로젝트 생성·합성·구현 스크립트 `create_project.tcl` |
| `board_test/` | Phase 0 보드 시험 설계: `p05_blink/`(LED·VIO), `p06_mig/`(DDR3 MIG), `p07_xdma/`(PCIe XDMA), `host/`(Host 쪽 스크립트) |

보드 시험 절차와 결과는 [ENVIRONMENT.md](../documents/design/ENVIRONMENT.md) §5~6을 따른다.
