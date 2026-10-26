/* host.h — Host program 공통 값과 함수 (라즈베리파이 5, 06_HOST_INTERFACE.md)
 * 값은 design_references를 따른다: 16 kHz, frame 1,024샘플, hop 512(주기 32 ms), mel 40, 판정 주기 31 frame,
 * 모델 40개, offset 간격 0.8 ms. packet은 06 §4, 주소 공간은 06 §7. */
#ifndef HOST_H
#define HOST_H
#include <stdint.h>

#define SR          16000
#define FRAME       1024
#define HOP         512
#define NMEL        40
#define SEG         31            /* 판정 주기 = frame 31개. 첫 추론 요청에 RESET_STATE */
#define N_MODELS    40
#define MAX_TRACKS  1024
#define PERIOD_US   32000         /* 주기 = deadline */
#define REQ_B       64
#define RES_B       32
#define REQ_PER_DG  23            /* datagram 하나에 추론 요청 최대 23개 (MTU 1,500 B) */
#define REQ_PORT    5000
#define CTL_PORT    5001

/* 06 §7 주소 */
#define A_ID        0x0000
#define A_STATUS    0x0100
#define A_CTRL      0x0104
#define A_NOW_US    0x0200
#define A_CONFIG    0x0300
#define A_CNT       0x0400
#define A_ERR       0x0500
#define A_OFFSET    0x1000
#define A_NREG      0x1100
#define A_TAU       0x1200
#define A_LUT_G     0x1400
#define A_LUT_U     0x2000
#define A_DDR3       0x80000000u
#define FPGA_ID     0x534E4E58u
#define SLOT_B      262144        /* 모델 slot 256 KiB */
#define SLOT_USED   131648        /* slot 앞의 유효 데이터 (02 §6) */
#define STATE_BASE  0x02000000u

/* 모델 m의 offset을 샘플로. O_m = m × 0.8 ms = 12.8m 샘플이라 가장 가까운 샘플로 둔다(오차 25 µs 이하) */
#define OFFSET_SAMPLES(m) (((m) * HOP + N_MODELS / 2) / N_MODELS)

/* mel.c */
void mel_init(void);
void mel_db(const float *x, float *db);                               /* Frame 1,024 → mel dB 40 */
#define NORM_TAU_S  5.0           /* 정규화 기준을 잊는 시간 상수 τ (s), P2.9 */
#define FLOOR_DB    (-80.0)       /* mel dB 하한 기본값. Mic마다 바닥 잡음 위로 정한다(map 둘째 칸, --floor-db) */
#define GATE_DB     6.0           /* Frame 최대가 하한 + 6 dB 이하면 무음: 정규화 기준을 갱신하지 않는다 */
#define QUIET_DB    15.0          /* frame 최대가 기준 최대 − 15 dB보다 작으면 조용한 frame: 최소를 갱신하지 않는다 */
void norm_q(const float *db, double floor_db, double *hi, double *lo, uint8_t *has, uint8_t *q);   /* → 0~127 */

/* ctl.c: 제어 packet(06 §7.6)과 시각(06 §5) */
typedef struct { int fd; uint16_t tag; int timeout_ms, retries; } ctl_t;
uint64_t mono_ns(void);
void put16(uint8_t *p, uint32_t v);
void put32(uint8_t *p, uint32_t v);
uint32_t get16(const uint8_t *p);
uint32_t get32(const uint8_t *p);
int  udp_open(const char *ip, int port);                              /* connect한 UDP socket */
int  ctl_open(ctl_t *c, const char *ip, int timeout_ms, int retries);
int  ctl_rw(ctl_t *c, int op, uint32_t addr, int count, uint32_t *data);   /* 응답 status, 응답 없음 −1 */
int  ctl_rd1(ctl_t *c, uint32_t addr, uint32_t *v);
int  ctl_wr1(ctl_t *c, uint32_t addr, uint32_t v);
int  clock_diff(ctl_t *c, int tries, uint32_t *diff, uint32_t *rtt_us);  /* FPGA µs − Host µs */

/* 트랙 → 모델 대응. map 파일 한 줄 = 트랙 하나(줄 번호 = track_id): model_id [dB 하한]. 없으면 track % 40.
 * 둘째 칸이 있으면 floor_db[트랙]에 쓴다(floor_db가 NULL이면 무시) */
int  load_map(const char *path, int n_tracks, uint8_t *model, double *floor_db);

int  cmd_setup(int argc, char **argv);
int  cmd_run(int argc, char **argv);
int  cmd_stop(int argc, char **argv);

#endif
