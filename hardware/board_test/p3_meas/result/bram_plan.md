## 구성 요소별 tile 수 (RAMB36 환산)

| 구성 요소 | 깊이 × 폭 | 데이터 | tile |
|---|---|---:|---:|
| weight cache entry 1개 | 4,096 × 256 bit (4,068 사용) | 130,176 B | 28.5 |
| 슬라이스 이중 buffer | 2 × 512 × 256 bit | 32,768 B | 7.5 |
| membrane potential L1 | 196,608 × 16 bit | 393,216 B | 96 |
| membrane potential L2 | 131,072 × 16 bit | 262,144 B | 64 |
| membrane potential L3 | 32,768 × 16 bit | 65,536 B | 16 |
| membrane potential L4 | 1,024 × 16 bit | 2,048 B | 0.5 |
| β·vth 40모델 상주 | 28,240 × 16 bit | 56,480 B | 14 |
| β·vth entry 1개분 | 706 × 16 bit | 1,412 B | 0.5 |
| 요청 queue | 512 × 512 bit | 32,768 B | 7.5 |
| 트랙 메타 | 512 × 64 bit | 4,096 B | 1 |
| 부분 상주: 40모델 L1 | 19,200 × 256 bit | 614,400 B | 142.5 |

membrane potential 합계 176.5 tile = 48.4% (데이터 722,944 B, 물리 794.25 KiB)

## 저장 정책별 예산 (XDMA 20.5 + 기타 0 tile 실측 반영)

| 시나리오 | 고정 사용 | weight에 남는 tile | 전체 모델 entry | 잔여 tile |
|---|---:|---:|---:|---:|
| A. 제안서 배분: 모델 1벌 prefetch buffer, β·vth 40모델, queue·메타 BRAM | 248 | 117 | 4 | 3 |
| B. 슬라이스 이중 buffer, β·vth 40모델, queue·메타 BRAM | 227 | 138 | 4 | 24 |
| C. 별도 buffer 없음(빈 entry에 직접 채움), β·vth 40모델, queue·메타 BRAM | 219.5 | 145.5 | 5 | 3 |
| D. 슬라이스 이중 buffer, β·vth entry별(+buffer 1벌), queue·메타 분산 RAM | 205 | 160 | 5 | 15 |
| E. 별도 buffer 없음, β·vth entry별, queue·메타 분산 RAM | 197 | 168 | 5 | 23 |

제안서 709.375 KiB 갱신: 365 − XDMA 20.5 − membrane potential 176.5 − prefetch 1벌 28.5 = 139.5 tile = 627.75 KiB (물리), β·vth·queue·메타까지 빼면 117 tile = 526.50 KiB
부분 상주(40모델 L1 전체 142.5 tile)는 시나리오 B 잔여 138 tile에 들어가지 않는다 (차이 -4.5).
membrane potential을 전부 DDR3에 두면(시나리오 B 기준) weight에 314.5 tile → entry 11개. membrane potential 이동량은 요청당 읽기·쓰기 2 × 1,412 B.
