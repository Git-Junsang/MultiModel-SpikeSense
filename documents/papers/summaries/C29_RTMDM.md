# C29: RT-MDM

원문: `C29_RTMDM_DAC2024.pdf`
Sukmin Kang, Seongtae Lee, Hyunwoo Koo, Hoon Sung Chwa, Jinkyu Lee, DAC 2024, 6쪽, DOI 10.1145/3649329.3655681
읽은 범위: 원문 전체

## 한 줄 요약

내부 메모리가 작은 MCU에서 DNN을 segment로 나눠 외부 메모리(SD card)에서 DMA로 읽으며 여러 주기 DNN task의 timing을 보장하는 scheduling framework다. Task마다 내부 메모리를 segment group으로 나눠 다음 segment 적재를 지금 segment 연산과 겹쳤고 분석으로 센 schedulable 비율이 자기 변형들보다 32.0–60.5% 높았다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | MCU 내부 메모리에 DNN 모델 여러 개가 다 들어가지 않는다. Segment로 나눠 외부 메모리에서 DMA로 읽으면 CPU 연산과 DMA 적재를 겹쳐야 하는데 겹칠수록 메모리를 차지한 segment 조합이 늘어 timing 분석이 어렵다(§1, §3) |
| 방법 | DP1: task 단위 비선점. Task의 첫 segment가 시작하면 그 task가 끝날 때까지 다른 task의 segment는 CPU와 DMA 어디에서도 돌지 않는다(§3) |
| 방법 | DP2: segment group. Task마다 내부 메모리(system space와 common space를 뺀 나머지)를 N_G개 group으로 나누고 segment는 실행될 때 자기 group 자리를 혼자 쓴다. Group 크기는 그 group에서 가장 큰 segment이고 group 크기의 합이 M − M_common 이하여야 한다(Constraint 1, 식 (1)). 모든 모델이 함께 쓰는 common space(segment 출력, 실행 공간)는 합이 아니라 최댓값 크기다(§3, 각주 2) |
| 방법 | IPE intra-task scheduler: 지금 CPU sub-segment와 다른 group이면 다음 DMA sub-segment(적재)를 겹쳐 돌리고 DMA는 순서대로 한다(ED4-IPE, ED5-IPE). Algorithm 1로 task WCET C*_i를 구해 기존 NP-FP response time 분석에 넣는다(§4, Lemma 2, Theorem 1) |
| 방법 | Segment 수와 group mapping은 task마다 C*_i가 가장 작도록 offline에 정한다(Problem 2, OR-Tools). Task별로 나눠 풀어도 전체 문제(Problem 1)의 해를 놓치지 않는다(§5, Theorem 2) |
| 가정·조건 | 주기·sporadic task model(D_i ≤ T_i), task 하나가 DNN 모델 하나. Job마다 segment마다 DMA sub-segment가 있고 task WCET C_i는 DMA·CPU sub-segment WCET의 합이다. 이전 job이 적재한 segment를 다시 쓰는 규칙은 없다(§2, Fig. 1). Arduino Nano 33 BLE Sense(Cortex-M4F 64 MHz, SRAM 256 KB, DMA, SD card), TensorFlow Lite(§6) |

## 결론

- Case study(τ1 음성 명령 인식 27 KB, 최대 2 segment, T = D = 500 ms. τ2 gesture 인식 31 KB, 최대 4 segment, T = D = 600 ms. Inter-task는 NP-DM): 내부 메모리가 충분하면 IPE-Opt와 IPE-M-M은 deadline을 지켰다. IPE-M-1의 최대 response time은 τ1 596 ms, τ2 651 ms로 deadline을 넘었다. IPE-Opt의 τ2 보장 response time은 436 ms다(§6, Fig. 4)
- 모델 공간을 30 KB로 줄이면 IPE-M-M은 τ2 segment 합 35 KB가 넘쳐 보장하지 못한다. IPE-Opt는 τ2를 4 segment, 2 group({S2,1, S2,3}, {S2,2, S2,4})으로 나눠 max(3, 22) + max(7, 3) = 29 KB만 쓰고 보장 response time 494 ms(≤ 600 ms)를 얻었다(§6, Table 1)
- 무작위 task set(task 2–5개, segment 2–5개, utilization마다 1,000×4×4개): Theorem 1과 Constraint 1로 센 schedulable 비율이 IPE-Opt가 IPE-1-1, IPE-M-M, IPE-M-1보다 각각 32.0%, 45.7%, 60.5% 높다(§6, Fig. 5(a))
- 평가 방식: Arduino Nano 33 BLE Sense 실측(case study, segment 실행 시간은 100번 잰 최댓값)과 Theorem 1로 판정한 schedulability simulation

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| on-chip 메모리보다 큰 weight를 외부 메모리에 두고 필요할 때 적재한다 | RT-MDM은 job마다 모든 segment를 다시 읽고 job 하나가 추론 하나다. 이 연구는 entry에 남은 모델을 다시 읽지 않고 entry가 모자랄 때 PNU-Count로 내보낼 모델을 고른다 | [구조] PNU Cache가 모델을 entry에 남겨 다음 batch에서 다시 쓰고 Grouping이 같은 모델 추론 요청을 batch로 묶어 weight 적재 한 번을 나눠 쓴다 |
| 연산하는 동안 다음 weight를 적재한다 | RT-MDM은 같은 job 안에서 다음 segment를 적재한다. 이 연구는 지금 batch를 연산하는 동안 다음 batch 모델 전체를 빈 entry로 적재하고 layer로 나누지 않는다 | 없음. Prefetch 자체는 주장하지 않는다(09 §3) |
| deadline이 있는 다중 모델 추론 | RT-MDM은 task 단위 비선점 고정 우선순위와 Theorem 1로 response time 상한을 보장한다 | 없음. 이 연구는 32 ms hard deadline 보장을 주장하지 않는다(09 §3) |

## 인용할 때

- RT-MDM이 먼저 했다: MCU 외부 메모리에서 segment 적재와 CPU 연산을 겹치면서 multi-DNN timing을 보장하는 분석, 공유 영역을 합이 아니라 최댓값으로 잡는 segment group. 원문은 "to the best of our knowledge" 첫 연구라고 쓴다. Prefetch와 부분 상주 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: task model §2·Fig. 1, ED·MR·DP §3, Constraint 1 식 (1), IPE §4.1·Algorithm 1·Lemma 2, 보장 §4.2·Theorem 1, 최적화 §5 Problem 1·2·Theorem 2, 결과 §6 Table 1·Fig. 4·5
- 주의: 비교한 IPE-1-1(IPD와 같음), IPE-M-M, IPE-M-1은 모두 RT-MDM 안의 변형이다. 다른 연구와 수치로 비교하지 않았다. 32.0–60.5%가 %p인지 상대 비율인지 원문에 없다
- 주의: 무작위 task set의 주기는 [5000, 50000)에서 뽑았는데 단위가 원문에 없다(§6)
- B18·C14와 이어서: 저자 Hoon Sung Chwa, Jinkyu Lee가 RT-Swap과 같다. RT-Swap처럼 다음 사용으로 내보낼 대상을 고르는 교체 순서는 없다. ZeroSwap처럼 job마다 weight를 다시 읽고 공유 영역을 최댓값 크기로 잡는다. SPET(C31)을 가장 가까운 연구로 들고 SPET은 task 안에서 적재와 연산을 겹치지 못한다고 쓴다(§1)
- 비교군: 지금 비교군에 옮긴 것이 없다
