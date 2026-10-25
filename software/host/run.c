/* run.c — 실행: 오디오 → offset에 맞춘 frame → 특징 추출 → 추론 요청 즉시 송신 → 결과 수신 → 판정·deadline 확인
 *
 * thread 3개: 계산(main, 입력·특징 추출·송신), 수신(결과·판정), 시각(1초마다 FPGA 시각과의 차이, 06 §5).
 * 입력: S16LE 16 kHz. WAV(RIFF)면 머리말을 읽고, 아니면 --channels 채널 raw. 트랙 i는 채널 i % C를 쓴다.
 * frame 경계는 샘플 번호로 정한다(06 §2). 모델 m 주기 k의 frame = 샘플 [O_m + 512k, O_m + 512k + 1,024).
 * 그 frame의 마지막 샘플이 든 block이 들어온 시각이 t_host다. 모델 묶음은 트랙을 모두 계산한 뒤 23개씩 이어서 보낸다.
 * 판정은 트랙마다 결과 31개의 out0·out1 합(평균과 같은 비교)으로 한다(02 §5). 결과가 빠진 판정 주기는 판정하지 않는다.
 * shortcut: pipe 입력의 t_host는 read()가 돌아온 시각이다. 오디오 장치의 block 도착 시각은 아니다. mic를 붙이면 ALSA timestamp로 바꾼다. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <math.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#include "host.h"

#define RING 4096                 /* 채널마다 샘플 ring. block + frame ≤ RING */
#define MAX_BLOCK 2048

typedef struct { _Atomic uint32_t kk; uint64_t t_host_ns; } pend_t;   /* kk = epoch + 1, 0이면 비어 있음 */

static pend_t pend[MAX_TRACKS][8];
static uint8_t model_of[MAX_TRACKS];
static int n_tracks, n_of[N_MODELS], tracks_of[N_MODELS][MAX_TRACKS];
static double scale[N_MODELS];
static _Atomic uint32_t diff_us;
static atomic_int stop_rx, stop_sync;
static volatile sig_atomic_t stop_main;
static int fd_req;
static ctl_t ctl;
static FILE *f_res, *f_bun;

static struct { uint64_t recv, late, unmatched, judged; double resp_max, resp_sum; } rx;   /* 수신 thread만 쓴다 */
static struct { int32_t cycle, cnt; int64_t s0, s1; } jd[MAX_TRACKS];
static struct { uint64_t ok, fail; uint32_t rtt_max; } sy;

static void judge(int tr, uint32_t k, int out0, int out1)
{
    int32_t c = (int32_t)(k / SEG);
    if (c > jd[tr].cycle) {                    /* 새 판정 주기. 앞 주기가 31개를 못 채웠으면 버린다 */
        jd[tr].cycle = c;
        jd[tr].cnt = 0;
        jd[tr].s0 = jd[tr].s1 = 0;
    } else if (c < jd[tr].cycle)
        return;
    jd[tr].s0 += out0;
    jd[tr].s1 += out1;
    if (++jd[tr].cnt == SEG) {
        int m = model_of[tr];
        double z = (double)(jd[tr].s1 - jd[tr].s0) / SEG * scale[m];   /* softmax P(이상) = 1 / (1 + e^(l0 − l1)) */
        printf("%d,%d,%d,%d,%.9g\n", tr, c, m, jd[tr].s1 > jd[tr].s0, 1.0 / (1.0 + exp(-z)));
        rx.judged++;
    }
}

static void *rx_main(void *arg)
{
    (void)arg;
    uint8_t b[256];
    while (!atomic_load(&stop_rx)) {
        ssize_t r = recv(fd_req, b, sizeof b, 0);
        uint64_t t = mono_ns();
        if (r < 0)
            continue;                          /* 수신 timeout(50 ms)마다 멈춤 확인 */
        unsigned tr = get16(b), seq = get16(b + 2);
        pend_t *p = &pend[tr % MAX_TRACKS][seq & 7];
        uint32_t kk = r == RES_B && tr < (unsigned)n_tracks ? atomic_load_explicit(&p->kk, memory_order_acquire) : 0;
        if (!kk || ((kk - 1) & 0xFFFF) != seq) {
            rx.unmatched++;
            continue;
        }
        double resp = (double)(t - p->t_host_ns) / 1e3;       /* 응답 시간 µs = t_recv − t_host */
        int out0 = (int16_t)get16(b + 24), out1 = (int16_t)get16(b + 26);
        rx.recv++;
        rx.late += resp > PERIOD_US;
        rx.resp_sum += resp;
        rx.resp_max = fmax(rx.resp_max, resp);
        if (f_res)
            fprintf(f_res, "%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%d,%d,%llu,%llu,%.1f\n", tr, seq, kk - 1, b[4], b[5], get16(b + 6),
                    get32(b + 8), get32(b + 12), get32(b + 16), get32(b + 20), out0, out1,
                    (unsigned long long)p->t_host_ns, (unsigned long long)t, resp);
        judge((int)tr, kk - 1, out0, out1);
    }
    return NULL;
}

static void *sync_main(void *arg)
{
    (void)arg;
    while (!atomic_load(&stop_sync)) {
        for (int i = 0; i < 20 && !atomic_load(&stop_sync); i++)
            usleep(50000);
        uint32_t d, rtt;
        if (clock_diff(&ctl, 5, &d, &rtt) == 0) {
            atomic_store(&diff_us, d);
            sy.ok++;
            if (rtt > sy.rtt_max)
                sy.rtt_max = rtt;
        } else
            sy.fail++;
    }
    return NULL;
}

/* layer 4 scale(이상 점수용) = manifest의 모델별 weight_scales[3]. model_id 순서로 들어 있다 */
static void load_scales(const char *path)
{
    for (int m = 0; m < N_MODELS; m++)
        scale[m] = NAN;
    FILE *f = fopen(path, "r");
    static char buf[1 << 20];
    size_t n = f ? fread(buf, 1, sizeof buf - 1, f) : 0;
    if (f)
        fclose(f);
    buf[n] = 0;
    int m = 0;
    for (char *p = buf; m < N_MODELS && (p = strstr(p, "\"weight_scales\"")); m++) {
        double v[4];
        p = strchr(p, '[');
        if (p && sscanf(p, "[ %lf , %lf , %lf , %lf", &v[0], &v[1], &v[2], &v[3]) == 4)
            scale[m] = v[3];
    }
    if (m != N_MODELS)
        fprintf(stderr, "경고: %s에서 모델 scale %d개만 읽었다. 없는 모델의 이상 점수는 nan\n", path, m);
}

/* WAV면 fmt를 확인하고 data 첫 byte까지 읽는다. raw면 읽은 12 B를 pre에 남긴다. 반환 data 길이(모르면 −1), 오류 −2 */
static long open_audio(int fd, int *ch, uint8_t *pre, int *npre)
{
    uint8_t h[16];
    *npre = 0;
    ssize_t r = read(fd, h, 12);
    if (r < 12 || memcmp(h, "RIFF", 4) || memcmp(h + 8, "WAVE", 4)) {
        if (r > 0)
            memcpy(pre, h, (size_t)(*npre = (int)r));
        return -1;
    }
    for (;;) {
        if (read(fd, h, 8) != 8)
            return -2;
        uint32_t sz = get32(h + 4);
        if (!memcmp(h, "data", 4))
            return sz;
        uint8_t body[64];
        for (uint32_t left = sz + (sz & 1); left;) {
            ssize_t g = read(fd, body, left < sizeof body ? left : sizeof body);
            if (g <= 0)
                return -2;
            if (!memcmp(h, "fmt ", 4) && left == sz + (sz & 1)) {
                unsigned fmt = get16(body), c = get16(body + 2), rate = get32(body + 4), bits = get16(body + 14);
                if ((fmt != 1 && fmt != 0xFFFE) || rate != SR || bits != 16) {
                    fprintf(stderr, "WAV 형식이 16 kHz 16 bit PCM이 아니다 (format %u, %u Hz, %u bit)\n", fmt, rate, bits);
                    return -2;
                }
                *ch = (int)c;
            }
            left -= (uint32_t)g;
        }
    }
}

static void on_signal(int s) { (void)s; stop_main = 1; }

int cmd_run(int argc, char **argv)
{
    const char *ip = "192.168.10.2", *in = "-", *map = NULL, *logp = NULL, *manifest = "hardware/data/models_l64/manifest.json";
    int C = 1, pace = 0, loop = 0, B = 64, cpu = -1;
    double seconds = 0;
    n_tracks = MAX_TRACKS;
    static struct option o[] = {{"fpga", 1, 0, 'f'}, {"in", 1, 0, 'i'}, {"channels", 1, 0, 'c'}, {"tracks", 1, 0, 'n'},
                                {"map", 1, 0, 'p'}, {"pace", 0, 0, 'P'}, {"loop", 0, 0, 'L'}, {"block", 1, 0, 'b'},
                                {"seconds", 1, 0, 's'}, {"log", 1, 0, 'l'}, {"manifest", 1, 0, 'M'}, {"cpu", 1, 0, 'u'}, {0}};
    for (int ch; (ch = getopt_long(argc, argv, "", o, NULL)) != -1;)
        switch (ch) {
        case 'f': ip = optarg; break;
        case 'i': in = optarg; break;
        case 'c': C = atoi(optarg); break;
        case 'n': n_tracks = atoi(optarg); break;
        case 'p': map = optarg; break;
        case 'P': pace = 1; break;
        case 'L': loop = 1; break;
        case 'b': B = atoi(optarg); break;
        case 's': seconds = atof(optarg); break;
        case 'l': logp = optarg; break;
        case 'M': manifest = optarg; break;
        case 'u': cpu = atoi(optarg); break;
        default: return 2;
        }
    if (n_tracks < 1 || n_tracks > MAX_TRACKS || B < 1 || B > MAX_BLOCK || (n_tracks = load_map(map, n_tracks, model_of)) < 0) {
        fprintf(stderr, "--tracks 1~%d, --block 1~%d\n", MAX_TRACKS, MAX_BLOCK);
        return 2;
    }
    for (int i = 0; i < n_tracks; i++)
        tracks_of[model_of[i]][n_of[model_of[i]]++] = i;
    load_scales(manifest);
    mel_init();

    int fd = strcmp(in, "-") ? open(in, O_RDONLY) : 0, npre = 0;
    uint8_t *buf = malloc((size_t)MAX_BLOCK * 2 * 256 + 64);
    long data_len = fd < 0 ? -2 : open_audio(fd, &C, buf, &npre);
    off_t data_off = lseek(fd, 0, SEEK_CUR);  /* --loop가 돌아갈 data 첫 byte. raw는 pre로 읽은 만큼 앞이다 */
    if (data_off >= 0)
        data_off -= npre;
    if (data_len < -1 || C < 1 || C > MAX_TRACKS || (size_t)B * (size_t)C > (size_t)MAX_BLOCK * 256) {   /* buf 크기 */
        fprintf(stderr, "입력 %s를 읽을 수 없다(채널 1~%d, block × 채널 ≤ %d)\n", in, MAX_TRACKS, MAX_BLOCK * 256);
        return 1;
    }
    if (loop && data_off < 0) {
        fprintf(stderr, "--loop는 파일 입력에서만 쓴다\n");
        return 2;
    }
    int16_t *ring = calloc((size_t)C * RING, sizeof *ring);
    static double hi[MAX_TRACKS], lo[MAX_TRACKS];
    static uint8_t pkt[MAX_TRACKS * REQ_B];
    static int32_t last_k[MAX_TRACKS];
    for (int i = 0; i < n_tracks; i++) {
        last_k[i] = -1;
        jd[i].cycle = -1;
    }

    if ((fd_req = udp_open(ip, REQ_PORT)) < 0 || ctl_open(&ctl, ip, 100, 2) < 0)
        return 1;
    int rcvbuf = 4 << 20;
    struct timeval tv = {0, 50000};
    setsockopt(fd_req, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof rcvbuf);
    setsockopt(fd_req, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    uint32_t d0, rtt;
    if (clock_diff(&ctl, 5, &d0, &rtt) == 0) {
        atomic_store(&diff_us, d0);
        fprintf(stderr, "FPGA 시각 차이 %u µs, 왕복 %u µs\n", d0, rtt);
    } else
        fprintf(stderr, "경고: FPGA 시각을 읽지 못해 차이를 0으로 둔다(t_host_us와 LATE flag가 틀린다)\n");
    ctl.timeout_ms = 20;
    ctl.retries = 0;

    if (logp) {
        char path[1024];
        snprintf(path, sizeof path, "%s_result.csv", logp);
        f_res = fopen(path, "w");
        snprintf(path, sizeof path, "%s_bundle.csv", logp);
        f_bun = fopen(path, "w");
        if (!f_res || !f_bun) {
            fprintf(stderr, "log %s_*.csv를 열 수 없다\n", logp);
            return 1;
        }
        setvbuf(f_res, NULL, _IOFBF, 1 << 20);
        setvbuf(f_bun, NULL, _IOFBF, 1 << 20);
        fprintf(f_res, "track_id,seq,epoch,model_id,flags,batch_n,t_host_us,t_in_us,t_start_us,t_done_us,out0,out1,"
                       "t_host_ns,t_recv_ns,resp_us\n");
        fprintf(f_bun, "epoch,model_id,delay_us,n_req,t_host_ns,t_start_ns,t_ready_ns,t_send_ns\n");
    }
    printf("track_id,cycle,model_id,decision,score\n");
    struct sigaction sa = {.sa_handler = on_signal};
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    pthread_t th_rx, th_sy;
    pthread_create(&th_rx, NULL, rx_main, NULL);
    pthread_create(&th_sy, NULL, sync_main, NULL);
    if (cpu >= 0) {                            /* 계산 thread만 고정한다(06 §2 가정 1). 수신·시각 thread는 따라가지 않는다 */
        cpu_set_t s;
        CPU_ZERO(&s);
        CPU_SET(cpu, &s);
        if (sched_setaffinity(0, sizeof s, &s) < 0)
            fprintf(stderr, "경고: CPU %d에 고정하지 못했다\n", cpu);
    }

    const size_t fb = 2u * (size_t)C, want = (size_t)B * fb;
    size_t have = (size_t)npre;
    long left = data_len;                      /* WAV data 남은 byte, raw면 −1 */
    uint64_t S = 0, n_ev = 0, limit = seconds > 0 ? (uint64_t)(seconds * SR) : UINT64_MAX;
    uint64_t sent = 0, send_err = 0, overrun = 0, t0 = mono_ns() + 100000000u;
    while (!stop_main && S < limit) {
        uint64_t t_arr = 0;
        if (pace) {                            /* block이 실시간으로 들어온다고 보고 그 도착 시각을 t_host로 쓴다 */
            t_arr = t0 + (S + (uint64_t)B) * 1000000000u / SR;
            struct timespec ts = {(time_t)(t_arr / 1000000000u), (long)(t_arr % 1000000000u)};
            while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) == EINTR && !stop_main) {}
        }
        int eof = 0;
        while (have < (pace ? want : fb) && !stop_main) {
            size_t ask = want - have;
            if (left >= 0 && (size_t)left < ask)
                ask = (size_t)left;
            ssize_t r = ask ? read(fd, buf + have, ask) : 0;
            if (r < 0 && errno == EINTR)
                continue;
            if (r <= 0) {
                if (!loop || lseek(fd, data_off, SEEK_SET) < 0) {
                    eof = 1;
                    break;
                }
                left = data_len;
                continue;
            }
            have += (size_t)r;
            if (left >= 0)
                left -= r;
        }
        if (!pace)
            t_arr = mono_ns();
        size_t nfr = have / fb;
        for (size_t s = 0; s < nfr; s++)
            for (int c = 0; c < C; c++)
                ring[(size_t)c * RING + ((S + s) & (RING - 1))] = (int16_t)get16(buf + s * fb + 2 * (size_t)c);
        memmove(buf, buf + nfr * fb, have - nfr * fb);
        have -= nfr * fb;
        S += nfr;

        for (;;) {                             /* frame 끝이 S 안에 든 모델 묶음을 offset 순서로 */
            int m = (int)(n_ev % N_MODELS);
            uint32_t k = (uint32_t)(n_ev / N_MODELS);
            uint64_t end = (uint64_t)OFFSET_SAMPLES(m) + (uint64_t)HOP * k + FRAME;
            if (end > S)
                break;
            n_ev++;
            int cnt = n_of[m], first = k % SEG == 0;
            if (!cnt)
                continue;
            uint64_t ts = mono_ns();
            uint32_t th_us = (uint32_t)(t_arr / 1000u) + atomic_load(&diff_us);
            for (int j = 0; j < cnt; j++) {
                int tr = tracks_of[m][j];
                const int16_t *rc = ring + (size_t)(tr % C) * RING;
                float x[FRAME], db[NMEL];
                for (int n = 0; n < FRAME; n++)
                    x[n] = rc[(end - FRAME + (uint64_t)n) & (RING - 1)] / 32768.0f;
                mel_db(x, db);
                uint8_t *p = pkt + (size_t)j * REQ_B;
                memset(p, 0, REQ_B);
                p[0] = 0xA5;
                p[1] = (uint8_t)first;         /* RESET_STATE: 판정 주기 첫 추론 요청 */
                put16(p + 2, (uint32_t)tr);
                put16(p + 4, k & 0xFFFF);
                p[6] = (uint8_t)m;
                put32(p + 8, th_us);
                put32(p + 12, (uint32_t)cnt);  /* n_expect: 이 모델·주기의 추론 요청 수 */
                seg_norm_q(db, &hi[tr], &lo[tr], first, p + 16);
            }
            uint64_t tr_ns = mono_ns();
            for (int j = 0; j < cnt; j++) {
                int tr = tracks_of[m][j];
                pend[tr][k & 7].t_host_ns = t_arr;
                atomic_store_explicit(&pend[tr][k & 7].kk, k + 1, memory_order_release);
                last_k[tr] = (int32_t)k;
            }
            for (int j = 0; j < cnt; j += REQ_PER_DG) {
                size_t len = (size_t)(cnt - j < REQ_PER_DG ? cnt - j : REQ_PER_DG) * REQ_B;
                send_err += send(fd_req, pkt + (size_t)j * REQ_B, len, 0) != (ssize_t)len;
            }
            sent += (uint64_t)cnt;
            if (f_bun)
                fprintf(f_bun, "%u,%d,%.3f,%d,%llu,%llu,%llu,%llu\n", k, m, (double)(tr_ns - t_arr) / 1e3, cnt,
                        (unsigned long long)t_arr, (unsigned long long)ts, (unsigned long long)tr_ns,
                        (unsigned long long)mono_ns());
        }
        if (pace && mono_ns() > t0 + (S + (uint64_t)B) * 1000000000u / SR)
            overrun++;                         /* 다음 block이 들어올 때까지 계산을 못 끝냄 */
        if (eof)
            break;
    }

    usleep(2 * PERIOD_US);                     /* deadline이 지날 때까지 남은 결과를 받는다 */
    atomic_store(&stop_rx, 1);
    atomic_store(&stop_sync, 1);
    pthread_join(th_rx, NULL);
    pthread_join(th_sy, NULL);
    uint64_t full = 0;
    for (int i = 0; i < n_tracks; i++)
        full += (uint64_t)(last_k[i] + 1) / SEG;
    uint64_t lost = sent > rx.recv ? sent - rx.recv : 0;
    fflush(stdout);
    fprintf(stderr, "summary sent=%llu recv=%llu late=%llu lost=%llu deadline_miss=%llu judged=%llu missing_cycles=%llu "
                    "unmatched=%llu resp_mean_us=%.1f resp_max_us=%.1f overrun=%llu send_err=%llu sync_ok=%llu sync_fail=%llu "
                    "sync_rtt_max_us=%u audio_s=%.3f\n",
            (unsigned long long)sent, (unsigned long long)rx.recv, (unsigned long long)rx.late, (unsigned long long)lost,
            (unsigned long long)(rx.late + lost), (unsigned long long)rx.judged, (unsigned long long)(full - rx.judged),
            (unsigned long long)rx.unmatched, rx.recv ? rx.resp_sum / (double)rx.recv : 0.0, rx.resp_max,
            (unsigned long long)overrun, (unsigned long long)send_err, (unsigned long long)sy.ok,
            (unsigned long long)sy.fail, sy.rtt_max, (double)S / SR);
    if (f_res)
        fclose(f_res);
    if (f_bun)
        fclose(f_bun);
    return 0;
}
