# B25: Nakayama 등 (B26·B27 함께)

원문: `B25_Nakayama_IoTJ2022.pdf`(주), `B26_Onodera_CCNC2021.pdf`, `B27_Onodera_JOCN2023.pdf`
IoT-J: Yu Nakayama, Yukito Onodera(Tokyo University of Agriculture and Technology), Anh Hoang Ngoc Nguyen, Yuko Hara-Azumi(Tokyo Institute of Technology), "Real-Time Resource Allocation in Passive Optical Network for Energy-Efficient Inference at GPU-Based Network Edge", IEEE Internet of Things Journal, vol. 9, no. 18, pp. 17348–17358, 2022, DOI 10.1109/JIOT.2022.3155606
CCNC: Yukito Onodera, Yoshiaki Inoue, Daisuke Hisano(Osaka University), Yu Nakayama, "Real-Time and Energy-Efficient Inference at GPU-Based Network Edge using PON", IEEE CCNC 2021, 6쪽(PDF에 쪽 번호 없음), DOI 10.1109/CCNC49032.2021.9369452
JOCN: Yukito Onodera, Yoshiaki Inoue, Daisuke Hisano, Naoto Yoshimoto(Chitose Institute of Science and Technology), Yu Nakayama, "Real-time batch processing at a GPU-based edge with a passive optical network", Journal of Optical Communications and Networking, 2023(2023-06-09 게재), DOI 10.1364/JOCN.476116. 받은 파일은 Optica가 공개한 저자 수락 원고라 권·호·쪽이 없다
읽은 범위: 세 편 전체. IoT-J Table II·Fig. 7–8과 JOCN Table 3은 PDF 그림으로 확인했다

## 한 줄 요약

카메라 여러 대가 TWDM-PON으로 GPU edge server 하나에 영상을 올린다. ONU마다 파장과 time-domain group을 배정하고 송신 시작 시각을 group 도착 시각에서 거꾸로 계산해 같은 group 영상이 같은 시각에 도착하게 한다. 목적은 batch를 키우는 것이고 세 편 모두 Python simulation에서 IPACT보다 지연이 낮고 batch가 같거나 컸다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | batch가 크면 weight를 메모리에서 읽는 부담이 여러 입력에 나뉘어 GPU 효율이 오른다(IoT-J §I, NVIDIA 자료 [2] 인용). 기존 PON 대역 배정(IPACT)은 REPORT·GATE 교환으로 지연이 길고 batch 크기를 고려하지 않는다(CCNC §II, IoT-J §II-B) |
| 방법(공통) | time-domain group g마다 edge 도착 시각 t_g를 두고 group끼리 σ씩 벌린다(Eq. 1). ONU를 파장 하나·group 하나의 자리에 배정하고 송신 시작 시각을 `s = t_g − 전파 지연 − 직렬화 지연 − OLT와 edge 사이 지연`으로 정한다(세 편 모두 Eq. 4) |
| 방법(맞추는 단위) | 한 group의 한 파장에는 ONU 하나만 든다(CCNC Eq. 10, IoT-J Eq. 14). 그래서 PON 하나에서 한 시각에 함께 도착하는 카메라는 파장 수(4대)까지다. Edge server 하나에 붙은 모든 PON의 같은 group이 같은 t_g에 도착한다(Eq. 4의 t_g에 PON 첨자가 없다, IoT-J Fig. 2). 전부를 한 시각에 맞추지 않는다 |
| 방법(CCNC, 개념) | 고정 배정. 파장 하나를 group 수만큼 채운 뒤 다음 파장으로 넘어가 켜진 파장 수를 줄인다(0-1 정수계획 Eq. 8–12, Alg. 1). Edge server가 배정된 group에 맞춰 카메라 촬영 시각을 조정한다(§III-A, Eq. 5). Group 하나가 batch 하나다(§III-A·B) |
| 방법(IoT-J, SAT) | cycle마다 다시 배정. ONU가 버퍼 상태를 보내면 OLT가 request가 있는 ONU를 slot(파장 × group)에 넣는다. 배정을 3-SAT로 바꿔 FPGA SAT solver(AmoebaSAT)로 푼다(§III-D·F, Eq. 11–14). 카메라는 임의 시각에 영상을 만들고 ONU에서 배정된 slot까지 기다린다(§III-C2, Eq. 5). Edge server는 group 여러 개를 모아 한 batch로 처리한다(§III-A·C1) |
| 방법(JOCN, batch processing) | 추정해서 다시 배정. 카메라마다 주기 ω와 알 수 없는 offset δ로 영상을 만든다고 보고 edge server가 도착 timestamp로 ω와 δ를 추정한다(Eq. 5, 8–15). 다음 cycle의 대기 지연이 가장 작은 group에 ONU를 넣는다(Eq. 16–18, Alg. 1). ONU는 새 영상이 오면 저장된 영상을 덮어쓴다(§3.B.5). JOCN은 CCNC가 모든 카메라의 생성 시각을 맞출 수 있다고 가정했고 이 가정을 뺐다고 적었다(§1) |
| 가정·조건 | group은 edge server가 계산에 쓰는 논리적 구성이고 같은 group의 ONU는 물리적·응용 속성을 공유하지 않는다(JOCN §3.B.2). 모델을 나누지 않는다. 추론은 객체 인식 DNN 하나이고 edge 처리 시간은 batch 크기와 무관한 고정값이다(IoT-J §V-A3·D). Weight 적재와 메모리는 simulation에 없다 |
| 가정·조건 | CCNC: PON 16개, PON당 ONU 1–32개, 파장 4개, 10 Gb/s, 영상 2.2 MB, σ = 200 ms, 최대 batch 140.8 MB(§IV-A). IoT-J: PON 16개, PON당 ONU 32–128개, 5 MB 영상 초당 8장, σ = 5 ms, group 2개, T_limit = 10 ms, 처리 10 ms, 최대 batch 128 MB, 10 ms마다 배정(Table II, §V-B). JOCN: PON 10개, PON당 ONU 4–64개, ω = 1/3 s, δ는 0–ω 균등분포, σ = 150 ms, T_limit = 250 ms, 최대 batch 140.8 MB(64장)(Table 3) |

## 결론

- 세 편 모두 제안 방식의 지연(영상 생성부터 edge 처리 시작까지)이 카메라 수와 무관하게 낮았고 IPACT는 카메라 수에 따라 늘었다(CCNC Fig. 4, IoT-J Fig. 7b, JOCN Fig. 10). JOCN에서 IPACT는 PON당 카메라가 16대를 넘으면 batch가 140.8 MB를 넘어 지연이 급히 늘었다(§5.C.1). 본문에 지연 수치는 없다
- Batch: CCNC는 카메라가 적어도 batch가 컸다(Fig. 6). IoT-J는 손실 없는 조건에서 IPACT와 비슷했다(Fig. 7a). IPACT가 queue에 20 ms 넘게 머문 영상을 버리는 조건에서 PON당 카메라 128대일 때 평균 batch는 제안 약 128 MB, IPACT 약 19 MB였고 손실률은 약 21%, 82%였다. 평균 지연은 둘 다 20–34 ms였다(Fig. 8, 그림에서 읽은 값). JOCN은 IPACT와 비슷했고 시각 추정이 없는 CCNC 방식은 더 작은 값으로 수렴했다(Fig. 13)
- IoT-J의 SAT 풀이는 50 MHz FPGA를 가정하면 평균 약 1 μs다(software로 반복 횟수를 세어 환산, Fig. 6). Software solver(3 ms 가정)를 쓰면 batch가 약 64 MB에서 멈추고 손실이 늘었다(Fig. 9)
- GPU 효율과 에너지는 재지 않았다. Batch 크기(MB)로 대신했고 에너지 평가는 이후 과제로 남겼다(CCNC §V, JOCN §6)
- 평가 방식: simulation(자체 Python3 simulator, 100회 반복). JOCN만 실제 GE-PON(ONU 3개, 라즈베리파이 4 3대)에서 IPACT 지연을 재서 simulation의 overhead를 25 ms로 맞췄다(§4)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 주기 입력이 도착하는 시각을 group 단위로 정한다. 같은 group은 같은 시각에 도착하고 group끼리는 σ씩 벌어진다(Eq. 1·4). 모델끼리 0.8 ms씩 벌리는 이 연구와 같은 모양이다 | group은 PON마다 파장 수만큼 ONU를 채운 자리이고 모델과 무관하다(JOCN §3.B.2). 모델은 하나다. 이 연구는 같은 모델을 쓰는 트랙이 한 group이고 group 크기는 그 모델의 트랙 수다 | [구조] 같은 모델 추론 요청이 함께 생겨 Grouping이 weight 적재 한 번으로 처리한다. Nakayama 등은 weight 적재를 동기로만 들고 처리 시간을 고정값으로 두었다 |
| 망 쪽(OLT, edge server)이 송신 시각을 정해 도착을 맞춘다 | IoT-J는 cycle마다 request를 받아 slot을 다시 배정하고 JOCN은 카메라 주기·offset을 추정해 group을 다시 고른다. 카메라 offset은 정할 수 없는 값으로 둔다. CCNC만 고정 배정이다. 이 연구의 Host는 frame을 자르는 시각을 `O_m = m × 0.8 ms`로 정해 고정하고 feedback이 없다 | [구조] 추정, cycle마다 하는 재배정, SAT solver가 없다. 트랙이 늘거나 줄어도 모델의 offset이 그대로다 |
| 함께 도착한 입력을 batch로 처리한다 | edge server는 정해진 간격으로 buffer의 데이터를 처리하고 최대 batch를 넘는 데이터는 다음 batch로 넘긴다(IoT-J §V-A3). 이 연구의 Grouping은 이미 도착한 같은 모델 추론 요청만 묶는다 | 없음 |

## 인용할 때

- 세 편이 먼저 한 것: 주기 source의 송신 시각을 edge 도착 시각에서 거꾸로 계산해 같은 group 입력을 같은 시각에 도착시키고 group끼리 σ씩 벌려 GPU batch를 키우는 방식. CCNC(2021)가 가장 이르고 EdgeSync(2025)보다 앞선다. 같은 시각 도착으로 batch 만들기, group 안은 맞추고 group끼리 벌리기는 신규성으로 주장하지 않는다
- 우리가 주장할 수 있는 범위: 모델을 기준으로 offset을 설계해 weight 재사용을 만드는 것, offset이 고정이고 feedback이 없는 것, 기다리지 않는 Grouping과 Predicted-Next-Use (PNU) Weight Cache를 결합한 것
- EdgeSync(B29)와의 관계: 둘 다 group 안은 맞추고 group끼리 벌린다. 둘 다 group이 모델과 무관하고 평가 모델이 하나다. EdgeSync는 UE camera의 촬영 시각을 1 ms씩 옮기고 network 경합을 피하려고 group 크기를 profile로 고르며 4G LTE testbed에서 쟀다. Nakayama 등은 PON slot 하나에 ONU 하나만 넣어 경합을 배정으로 없애고 ONU 송신 시각을 맞추며 simulation만 했다. EdgeSync는 Nakayama 등을 인용하지 않는다
- 근거 위치: CCNC 개념 §III-A, 송신 시각 Eq. 4–5, 배정 Eq. 8–12·Alg. 1, 결과 Fig. 4–7. IoT-J 개념 §III-A, 송신 시각 Eq. 4–8, SAT Eq. 11–14, 조건 Table II, 결과 Fig. 6–9. JOCN 가정 변경 §1, group 정의 §3.B.2, 추정·배정 Eq. 5–18·Alg. 1, 예비 실험 §4, 결과 Fig. 10–13
- 주의: 모델별 group이라는 문장은 세 편 어디에도 없다. 제목과 초록의 energy-efficient는 평가하지 않았다. 결과 수치는 대부분 그림에만 있다. JOCN 결론(§6)은 CCNC 문장을 옮겨 촬영 시각을 조정한다고 적었지만 본문은 카메라 offset을 추정한다
- 주의: [09_RELATED_WORK](../../design_references/09_RELATED_WORK.md) §4 표는 세 편을 초록 기준으로 "전문 미확보", "offset을 두는 방식이 아니다"라고 적었다. 전문을 보면 CCNC는 카메라 촬영 시각을 group에 맞추고 JOCN은 카메라별 offset δ를 추정한다. Offset을 모델 기준으로 설계하지 않을 뿐 도착 시각을 맞춰 batch를 만드는 점은 같다
- 주의: 이 연구의 비교 조건에는 모델과 무관하게 정원만큼 묶어 group끼리 벌리는 조건이 없다. Global alignment(모든 트랙에 같은 offset)와 다르다
