# C26: Informed Prefetching and Caching (TIP)

원문: `C26_TIP_SOSP1995.pdf`
R. Hugo Patterson, Garth A. Gibson, Eka Ginting, Daniel Stodolsky, Jim Zelenka, ACM SOSP 1995(PDF 표기 SIGOPS '95, 12/95, CO), pp. 79–95, PDF에 DOI 표기 없음(ISBN 0-89791-715-4)
읽은 범위: 원문 전체. Fig. 6, 11–16의 막대 값과 Eq. 17은 글자 추출이 깨져 본문에 적힌 수치만 옮겼다

## 한 줄 요약

응용이 앞으로 읽을 file과 순서를 hint로 알려 주면 file system이 비용-이득 추정으로 buffer를 prefetch, hinted block cache, LRU cache에 나눈다. OSF/1에 구현한 TIP에서 hint를 준 응용 5개의 실행 시간이 disk 4개 이상일 때 20–85% 줄었다(§10).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 기존 file cache는 응용이 읽을 때가 되어서야 disk를 읽는다. 순차가 아닌 직렬 접근은 disk array의 병렬성을 쓰지 못한다. Cache보다 큰 file을 반복해 읽으면 LRU는 hit를 내지 못한다(§1, §7.1) |
| 방법 | hint(disclosure): 응용이 ioctl로 file과 접근 pattern(처음부터 끝까지 순차, 또는 순서 있는 <offset, length> 목록)을 알린다. Hint를 준 순서가 접근 순서다. 정책을 권하는 advice가 아니라 응용이 할 일을 밝힌다(§3, Fig. 1) |
| 방법 | 비용-이득: buffer 하나를 접근 간격 하나 동안 쓰는 것(buffer-access)당 I/O service time 변화를 공통 단위로 둔다. Prefetch 이득(Eq. 9), LRU buffer를 뺄 때 비용(hit ratio 기울기, Eq. 11), hinted block을 내보낼 때 비용(Eq. 14)을 접근 비율로 정규화하고 가치가 가장 낮은 buffer를 내준다(global min-max, §4.2–4.5, Fig. 7) |
| 방법 | hinted cache에서 가치가 가장 낮은 block은 다음 hint 접근이 가장 먼 block이다. Disk 접근 시간이 모두 같다고 보기 때문이다(§5). Prefetch는 prefetch horizon P = T_disk/(T_cpu + T_hit + T_driver)(Eq. 7)보다 앞서 하지 않는다. 반복 접근에서는 따로 짜지 않아도 MRU 같은 교체가 나온다(§4.6, Fig. 8) |
| 방법 | TIP-2는 OSF/1 v2.0A의 unified buffer cache를 바꿨다. LRU 쪽 hit ratio H(n)은 ghost buffer와 100 buffer 단위 segment로 추정한다. T_cpu = 0으로 두어 prefetch horizon 상한을 고정한다. 내보낸 block을 곧 다시 읽는 thrashing을 막으려 비용에 T_hit를 더한다(§5.1–5.3). TIP-1은 prefetch만 하고 아직 읽지 않은 hinted block을 buffer 62개까지 둔다(§6) |
| 가정·조건 | 접근은 모두 block 하나, T_disk는 상수, disk queue 없음(§4.1). 시험기는 Digital 3000/500(150 MHz Alpha, 메모리 128 MB), disk 15개 중 1–10개, cache 12 MB(8 KB buffer 1,536개), T_disk 15 ms, T_hit 243 µs, T_driver 580 µs다(§6). Hint가 맞다고 가정하고 틀린 hint는 평가하지 않았다 |

## 결론

- Informed prefetching(TIP-1)은 disk 4개 이상에서 응용 5개(XDataSlice, Sphinx, Agrep, Gnuld, Postgres)의 실행 시간을 20–85% 줄였다(§10). Agrep은 disk 4개에서 73%, 10개에서 83% 줄었다(§7.4). XDataSlice는 disk 10개에서 slice 하나를 그리는 시간이 약 1/6(약 2초)이 됐다(§7.2)
- Informed caching(TIP-2)은 16.3 MB 행렬을 반복해 순차로 읽는 Davidson에서 disk 읽기를 125,340 block에서 53,200 block으로 줄였다. Disk 1개에서 실행 시간이 30% 넘게 줄었고 cache 16 MB에서는 42% 줄었다. LRU는 데이터 전체가 cache에 들어갈 때까지 buffer를 늘려도 이득이 없었다(§7.1, Fig. 11)
- 응용 둘을 함께 돌린 세 쌍(TIP-2)에서 hint를 주면 둘 다 끝나는 시간이 줄었다. 응용 6개 중 2개는 상대가 hint를 줄 때 오히려 느려졌다(§8, Fig. 14–16)
- 평가 방식: OSF/1 kernel에 구현해 잰 실측(Digital 3000/500). 측정 표준편차는 평균의 3% 미만이다(§7)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 앞으로 쓸 쪽(응용, Host)이 미래 사용 정보를 cache에 알려 주고 cache가 그 정보로 교체한다. 이 연구의 Host도 추론 요청 packet의 `n_expect`에 이 모델·주기의 예상 추론 요청 수를 싣고 PNU-Count가 이를 쓴다(06 §4.1) | TIP의 hint는 읽을 block과 순서를 모두 담고 시각은 담지 않는다. 거리는 몇 번째 뒤 접근인지(y)로 센다(Eq. 14). `n_expect`는 개수 하나다. PNU-Count는 도착 시각을 nominal offset, 모델 그룹 지연 분포, 추론 요청별 지연 분포로 예측하고 남은 추론 요청 수 r은 δ_j(x, r) = (J − x)/(r + 1)에만 쓴다(04 §3.1). 첫 추론 요청 전에는 직전 주기 값을 쓴다 | [구조] hint가 개수 하나라 Host가 접근 목록을 만들 일이 없다. Host는 모델 그룹을 한 번에 계산하므로 이 수를 이미 안다(06 §2). TIP는 응용 code를 고쳐 hint를 만들었다(§7.2, §7.6의 loop splitting) |
| 다음 사용이 가장 먼 대상을 내보낸다. 대상마다 적재 비용이 같다는 전제도 같다(TIP는 disk 접근 시간, 이 연구는 모델 크기 131,648 B와 적재 시간 43.91 µs, 04 §3) | TIP는 prefetch, hinted cache, LRU cache가 나눠 갖는 buffer 수를 비용-이득으로 계속 바꾼다. 이 연구는 entry 4개를 모두 weight cache로 쓰고 다음 batch의 모델 하나만 prefetch한다 | 없음. 이 연구에는 TIP의 비용-이득 배분이 없다 |

## 인용할 때

- Patterson 등이 먼저 했다: 응용이 앞으로의 접근을 hint로 알려 주고 OS가 그 hint를 prefetch와 cache 교체에 함께 쓰는 것, hint로 다음 접근이 가장 먼 block을 내보내는 것. Host가 추론 요청 packet에 미래 사용 정보를 실어 cache가 쓰게 하는 것 자체는 신규성으로 주장하지 않는다. 다음 사용 시점 교체와 prefetch도 주장하지 않는 범위다(09 §3)
- 근거 위치: hint 형식 §3과 Fig. 1, 비용-이득 식 §4(Eq. 7, 9, 11, 14, Fig. 7), 가장 먼 다음 접근 교체 Fig. 2 설명과 §5 첫머리, MRU 예 §4.6과 Fig. 8, 구현 §5, 시험기와 부담 §6, 단일 응용 결과 §7(Fig. 11–13), 여러 응용 §8(Fig. 14–16)
- 주의: 초록은 20–83%, 결론(§10)은 disk 4개 이상에서 20–85%라고 적었다. 수치마다 disk 수와 비교 대상(OSF/1 readahead, TIP-1, TIP-2)이 다르다
- 주의: TIP-2의 informed caching은 재사용이 적은 XDataSlice, Sphinx, Agrep에서 TIP-1보다 낫지 않았다(Fig. 12 설명). 42%는 Davidson, disk 1개, cache 16 MB 조건이다(Fig. 11(b))
- 주의: TIP-2 부담은 kernel build에서 CPU 2.4%, 실행 시간 2.8%였고 시험 응용에서는 CPU 1.8–13%였다(§6)
- 비교군: 옮기지 않았다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
