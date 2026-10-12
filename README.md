# MultiModel-SpikeSense

40개 SNN 모델로 여러 센서 트랙을 실시간 처리하는 FPGA 가속기 연구다. 핵심 목표는 가중치를 재사용하면서 각 요청의 32 ms deadline을 지키는 것이다.

## 현재 상태

- Phase 1~2: 개발 환경, 보드 연결, 모델 학습, INT8 변환 완료
- Phase 3: DDR3·PCIe 측정과 architecture simulation 완료
- Phase 4 이후: RTL 구현, 보드 통합, 실측 평가 예정

시뮬레이션 결과는 보드 성능 실측값이 아니다. 최신 확정 목표는 [중간보고](documents/presentation/)와 [PROPOSAL.md](documents/design/PROPOSAL.md)를 따른다. P3.6~P3.8에서 나온 XL 모델·1,024트랙 안은 아직 제안 상태다.

## 문서

| 문서 | 내용 |
|---|---|
| [PROPOSAL.md](documents/design/PROPOSAL.md) | 연구 목표와 설계 기준 |
| [TASKS.md](documents/design/TASKS.md) | 진행 상황과 다음 작업 |
| [MODEL_SIZE_PLAN.md](documents/design/MODEL_SIZE_PLAN.md) | 모델 크기와 scheduler 실험 |
| [RELATED_WORK.md](documents/design/RELATED_WORK.md) | 선행연구와 차별점 |
| [연구 보고서](documents/reports/) | 단계별 실험과 결과 |
| [문서 작성 규칙](documents/STYLE_GUIDE.md) | 문체와 형식 |

## 폴더

| 폴더 | 내용 |
|---|---|
| `documents/` | 설계 문서, 보고서, 발표 자료, 논문 |
| `software/` | 모델, 분석, architecture simulation |
| `hardware/` | 보드 시험 설계, FPGA 자료, RTL 작업 공간 |

작업 규칙은 [AGENTS.md](AGENTS.md)를 따른다.
