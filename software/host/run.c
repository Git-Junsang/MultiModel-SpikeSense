/* run.c — 실행: 오디오 → offset에 맞춘 frame → 특징 추출 → 추론 요청 즉시 송신 → 결과 수신 → 판정·deadline 확인
 *
 * thread 3개: 계산(main, 입력·특징 추출·송신), 수신(결과·판정), 시각(1초마다 FPGA 시각과의 차이, 06 §5).
 * 입력: S16LE 16 kHz. WAV(RIFF)면 머리말을 읽고, 아니면 --channels 채널 raw. 트랙 i는 채널 i % C를 쓴다.
 * Frame 경계는 샘플 번호로 정한다(06 §2). 모델 m 주기 k의 frame = 샘플 [O_m + 512k, O_m + 512k + 1,024).
 * 그 frame의 마지막 샘플이 든 block이 들어온 시각이 t_host다. 모델 그룹은 트랙을 모두 계산한 뒤 23개씩 이어서 보낸다.
 * 판정은 트랙마다 결과 31개의 out0·out1 합(평균과 같은 비교)으로 한다(02 §5). 결과가 빠진 판정 주기는 판정하지 않는다.
 * --pace: block 도착 시각을 FPGA 주기 격자에 맞춘다(06 §5). 첫 block 시작 t0를 FPGA 주기 경계에 두고,
 *   실행 중 clock 차이가 변한 만큼 빼서 FPGA clock 속도로 보낸다. 그래서 모델 m의 t_host가 FPGA 위상 O_m 뒤 block 하나 안에 든다.
 * shortcut: 위상은 NOW_US mod 32,000으로 구한다. setup 뒤 71.6분(NOW_US 되감김) 안에 run을 시작해야 맞다. 넘으면 NOW_CYC로 구한다.
 * --mic: 장치 하나 = 채널 하나. 16 kHz 64샘플 block의 t_host = ALSA htstamp로 잡은 도착 시각(mic.c).
 *   장치마다 frame 끝 샘플 번호를 adj만큼 옮겨, 그 샘플의 도착이 FPGA 주기의 nominal frame 끝 시각에 오게 한다(06 §5).
 *   도착 추정 τ = (FPGA 시각 기준 block 도착 − 샘플 수 / 16 kHz)의 1초 창 최솟값(USB 지연 흔들림의 아래쪽). Mic clock drift(약 59 ppm)와
 *   Host–FPGA clock 차이가 τ에 함께 들어가 adj가 약 1초에 샘플 하나씩 바뀐다. 오디오 값은 고치지 않고 frame을 자르는 위치만 옮긴다.
 * --mic + --in WAV: 트랙 0~(mic 수 − 1)은 mic, 나머지 트랙 i는 파일 채널 (i − mic 수) % C(가상 트랙). 파일 전체를 채널마다 메모리에
 *   올리고 반복해 읽는다. 가상 트랙 i는 (i − mic 수) × VSTEP mod 파일 길이만큼 늦춰 읽어 트랙마다 위상이 다르다(같은 채널을 써도 같은
 *   소리를 동시에 듣지 않는다). 파일 위치 = (mic 0 샘플 번호 + 늦춤) mod 길이. 가상 트랙의 frame 경계(adj)와 t_host는 mic 0을 따른다.
 * shortcut: pipe 입력의 t_host는 read()가 돌아온 시각이다. 오디오 장치의 block 도착 시각은 아니다. Mic는 --mic로 받는다. */
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
#define VSTEP 104729u             /* 가상 트랙 사이 늦춤(샘플, 소수 = 6.5 s). demo.py VSTEP와 같아야 화면 정답이 맞다 */

typedef struct { _Atomic uint32_t kk; uint64_t t_host_ns; } pend_t;   /* kk = period + 1, 0이면 비어 있음 */

static pend_t pend[MAX_TRACKS][8];
static uint8_t model_of[MAX_TRACKS], has_ref[MAX_TRACKS];
static double floor_of[MAX_TRACKS];
static int n_tracks, n_of[N_MODELS], tracks_of[N_MODELS][MAX_TRACKS];
static double scale[N_MODELS];
static _Atomic uint32_t diff_us;
static atomic_int stop_rx, stop_sync;
static volatile sig_atomic_t stop_main;
static int fd_req;
static ctl_t ctl;
static FILE *f_res, *f_model_group;

static struct { uint64_t recv, late, unmatched, judged; double response_time_max, response_time_sum; } rx;   /* 수신 thread만 쓴다 */
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
        double response_time = (double)(t - p->t_host_ns) / 1e3;       /* Response time µs = t_recv − t_host */
        int out0 = (int16_t)get16(b + 24), out1 = (int16_t)get16(b + 26);
        rx.recv++;
        rx.late += response_time > PERIOD_US;
        rx.response_time_sum += response_time;
        rx.response_time_max = fmax(rx.response_time_max, response_time);
        if (f_res)
            fprintf(f_res, "%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%d,%d,%llu,%llu,%.1f\n", tr, seq, kk - 1, b[4], b[5], get16(b + 6),
                    get32(b + 8), get32(b + 12), get32(b + 16), get32(b + 20), out0, out1,
                    (unsigned long long)p->t_host_ns, (unsigned long long)t, response_time);
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

/* WAV면 fmt를 확인하고 데이터 첫 byte까지 읽는다. raw면 읽은 12 B를 pre에 남긴다. 반환 데이터 길이(모르면 −1), 오류 −2 */
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

/* --pace에서 샘플 n까지 든 block이 들어오는 Host 시각. FPGA 시각으로 t0 + n / SR이 되게 시작 뒤 clock 차이 변화를 뺀다 */
static uint64_t pace_arr(uint64_t t0, uint32_t d0, uint64_t n)
{
    int64_t drift_us = (int32_t)(atomic_load(&diff_us) - d0);
    return t0 + n * 1000000000u / SR - (uint64_t)(drift_us * 1000);
}

int cmd_run(int argc, char **argv)
{
    const char *ip = "192.168.10.2", *in = "-", *map = NULL, *logp = NULL, *manifest = "hardware/data/models_l64/manifest.json";
    int C = 1, pace = 0, loop = 0, B = 64, cpu = -1, nmic = 0;
    char *mic_id[MAX_MIC];
    static mic_t mic[MAX_MIC];
    double seconds = 0, floor_db = FLOOR_DB;
    n_tracks = MAX_TRACKS;
    static struct option o[] = {{"fpga", 1, 0, 'f'}, {"in", 1, 0, 'i'}, {"channels", 1, 0, 'c'}, {"tracks", 1, 0, 'n'},
                                {"map", 1, 0, 'p'}, {"floor-db", 1, 0, 'F'}, {"pace", 0, 0, 'P'}, {"loop", 0, 0, 'L'}, {"block", 1, 0, 'b'},
                                {"seconds", 1, 0, 's'}, {"log", 1, 0, 'l'}, {"manifest", 1, 0, 'M'}, {"cpu", 1, 0, 'u'},
                                {"mic", 1, 0, 'm'}, {0}};
    for (int ch; (ch = getopt_long(argc, argv, "", o, NULL)) != -1;)
        switch (ch) {
        case 'f': ip = optarg; break;
        case 'i': in = optarg; break;
        case 'c': C = atoi(optarg); break;
        case 'n': n_tracks = atoi(optarg); break;
        case 'p': map = optarg; break;
        case 'F': floor_db = atof(optarg); break;
        case 'P': pace = 1; break;
        case 'L': loop = 1; break;
        case 'b': B = atoi(optarg); break;
        case 's': seconds = atof(optarg); break;
        case 'l': logp = optarg; break;
        case 'M': manifest = optarg; break;
        case 'u': cpu = atoi(optarg); break;
        case 'm':
            for (char *t = strtok(optarg, ","); t && nmic < MAX_MIC; t = strtok(NULL, ","))
                mic_id[nmic++] = t;
            break;
        default: return 2;
        }
    for (int i = 0; i < MAX_TRACKS; i++)
        floor_of[i] = floor_db;            /* map 둘째 칸이 있으면 트랙마다 바뀐다 */
    if (n_tracks < 1 || n_tracks > MAX_TRACKS || B < 1 || B > MAX_BLOCK || (n_tracks = load_map(map, n_tracks, model_of, floor_of)) < 0) {
        fprintf(stderr, "--tracks 1~%d, --block 1~%d\n", MAX_TRACKS, MAX_BLOCK);
        return 2;
    }
    for (int i = 0; i < n_tracks; i++)
        tracks_of[model_of[i]][n_of[model_of[i]]++] = i;
    load_scales(manifest);
    mel_init();

    int fd = -1, npre = 0;
    uint8_t *buf = malloc((size_t)MAX_BLOCK * 2 * 256 + 64);
    long data_len = -1;
    off_t data_off = -1;
    if (nmic) {                                /* block = ALSA period(16 kHz 64샘플) */
        B = MIC_BLOCK;
        pace = 0;
        mic_fir_init();
    }
    if (nmic && !strcmp(in, "-"))
        C = 0;                                 /* mic만. C = 파일 채널 수 */
    else {
        fd = strcmp(in, "-") ? open(in, O_RDONLY) : 0;
        data_len = fd < 0 ? -2 : open_audio(fd, &C, buf, &npre);
        data_off = lseek(fd, 0, SEEK_CUR);     /* --loop가 돌아갈 데이터 첫 byte. raw는 pre로 읽은 만큼 앞이다 */
        if (data_off >= 0)
            data_off -= npre;
        loop |= nmic > 0;                      /* 가상 트랙: 파일을 반복해 읽는다 */
    }
    if (data_len < -1 || C < (fd >= 0) || C > MAX_TRACKS || (size_t)B * (size_t)C > (size_t)MAX_BLOCK * 256) {   /* buf 크기 */
        fprintf(stderr, "입력 %s를 읽을 수 없다(채널 1~%d, block × 채널 ≤ %d)\n", in, MAX_TRACKS, MAX_BLOCK * 256);
        return 1;
    }
    if (loop && data_off < 0) {
        fprintf(stderr, "--loop는 파일 입력에서만 쓴다\n");
        return 2;
    }
    int16_t *vch = NULL;                       /* mic + 파일: 파일 전체를 채널마다 이어 붙여 둔다 [C][VL] */
    uint64_t VL = 0;
    static uint64_t voff[MAX_TRACKS];          /* 가상 트랙마다 파일을 늦춰 읽는 샘플 수(트랙마다 위상이 다르다) */
    if (nmic && fd >= 0) {
        if (data_len <= 0 || data_len % (2L * C)) {
            fprintf(stderr, "--mic와 함께 쓰는 --in은 WAV여야 한다\n");
            return 2;
        }
        int16_t *t = malloc((size_t)data_len);
        vch = malloc((size_t)data_len);
        for (size_t got = 0; t && vch && got < (size_t)data_len;) {
            ssize_t r = read(fd, (uint8_t *)t + got, (size_t)data_len - got);
            if (r <= 0) {
                fprintf(stderr, "입력 %s를 다 읽지 못했다\n", in);
                return 1;
            }
            got += (size_t)r;
        }
        if (!t || !vch) {
            fprintf(stderr, "입력 %s를 올릴 메모리가 없다\n", in);
            return 1;
        }
        VL = (uint64_t)data_len / (2u * (uint64_t)C);
        for (uint64_t s = 0; s < VL; s++)      /* S16LE → host(aarch64 LE) 그대로 */
            for (int c = 0; c < C; c++)
                vch[(uint64_t)c * VL + s] = t[s * (uint64_t)C + (uint64_t)c];
        free(t);
        close(fd);
        fd = -1;                               /* block마다 읽지 않는다 */
        for (int i = nmic; i < n_tracks; i++)
            voff[i] = (uint64_t)(i - nmic) * VSTEP % VL;
    }
    int16_t *ring = calloc((size_t)(nmic + C) * RING, sizeof *ring);   /* 채널: mic 0~nmic−1, 파일 0~C−1 */
    static double hi[MAX_TRACKS], lo[MAX_TRACKS];
    static uint8_t pkt[MAX_TRACKS * REQ_B];
    static int32_t last_k[MAX_TRACKS];
    static int ch_of[MAX_TRACKS], mic_of[MAX_TRACKS];   /* 트랙 → ring 채널, frame 경계·t_host를 따를 mic */
    for (int i = 0; i < n_tracks; i++) {
        last_k[i] = -1;
        jd[i].cycle = -1;
        ch_of[i] = i < nmic || !C ? i % nmic : nmic + (i - nmic) % C;
        mic_of[i] = ch_of[i] < nmic ? ch_of[i] : 0;
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
    d0 = atomic_load(&diff_us);
    ctl.timeout_ms = 20;
    ctl.retries = 0;

    if (logp) {
        char path[1024];
        snprintf(path, sizeof path, "%s_result.csv", logp);
        f_res = fopen(path, "w");
        snprintf(path, sizeof path, "%s_model_group.csv", logp);
        f_model_group = fopen(path, "w");
        if (!f_res || !f_model_group) {
            fprintf(stderr, "log %s_*.csv를 열 수 없다\n", logp);
            return 1;
        }
        setvbuf(f_res, NULL, _IOFBF, 1 << 20);
        setvbuf(f_model_group, NULL, _IOFBF, 1 << 20);
        fprintf(f_res, "track_id,seq,period,model_id,flags,batch_n,t_host_us,t_in_us,t_start_us,t_done_us,out0,out1,"
                       "t_host_ns,t_recv_ns,response_time_us\n");
        fprintf(f_model_group, "period,model_id,delay_us,n_req,t_host_ns,t_start_ns,t_ready_ns,t_send_ns\n");
    }
    printf("track_id,cycle,model_id,decision,score\n");
    struct sigaction sa = {.sa_handler = on_signal};
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    for (int c = 0; c < nmic; c++)             /* USB 장치 설정은 수십 ms 걸린다. 모두 연 뒤 첫 read 바로 전에 함께 시작한다 */
        if (mic_open(&mic[c], mic_id[c]) < 0)
            return 1;
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
    long left = data_len;                      /* WAV 데이터 남은 byte, raw면 −1 */
    uint64_t S = 0, n_ev = 0, limit = seconds > 0 ? (uint64_t)(seconds * SR) : UINT64_MAX;
    uint64_t sent = 0, send_err = 0, overrun = 0, t0 = mono_ns() + (nmic ? 1100000000u : 100000000u);   /* mic: τ를 1초 모은 뒤 */
    t0 += (uint64_t)((PERIOD_US - (uint32_t)(t0 / 1000u + d0) % PERIOD_US) % PERIOD_US) * 1000u - t0 % 1000u;   /* FPGA 위상 0 */
    static uint64_t tarr[MAX_MIC][RING / MIC_BLOCK];   /* mic block 도착 시각, block 번호 % 64 */
    int64_t adj[MAX_MIC] = {0}, lo_cur[MAX_MIC], lo_prev[MAX_MIC], adj_first = INT64_MIN;
    int win[MAX_MIC] = {0};
    for (int c = 0; c < MAX_MIC; c++)
        lo_cur[c] = lo_prev[c] = INT64_MAX;
    for (int c = 0; c < nmic; c++)
        if (mic_start(&mic[c]) < 0) {
            fprintf(stderr, "mic %s를 시작하지 못했다\n", mic_id[c]);
            stop_main = 1;
        }
    while (!stop_main && S < limit) {
        uint64_t t_arr = 0;
        size_t nfr = MIC_BLOCK;                /* 이번에 ring에 넣은 샘플 수 */
        int eof = 0;
        if (nmic) {
            int r = 0;
            for (int c = 0; c < nmic && r >= 0; c++) {
                int16_t y[MIC_BLOCK];
                uint64_t ta = 0;
                while ((r = mic_read(&mic[c], y, &ta)) == -1) {   /* xrun: 샘플이 빠졌으니 도착 추정을 새로 */
                    lo_cur[c] = lo_prev[c] = INT64_MAX, win[c] = 0;
                    fprintf(stderr, "mic %s xrun: 오디오 %.3f s\n", mic_id[c], (double)S / SR);
                }
                if (r < 0)
                    break;
                for (int s = 0; s < MIC_BLOCK; s++)
                    ring[(size_t)c * RING + ((S + (uint64_t)s) & (RING - 1))] = y[s];
                tarr[c][(S / MIC_BLOCK) % (RING / MIC_BLOCK)] = ta;
                int64_t o = (int64_t)(ta / 1000u) + (int32_t)(atomic_load(&diff_us) - d0) - (int64_t)((S + MIC_BLOCK) * 1000000u / SR);
                if (o < lo_cur[c])
                    lo_cur[c] = o;
                if (++win[c] == SR / MIC_BLOCK)        /* 1초 창 */
                    lo_prev[c] = lo_cur[c], lo_cur[c] = INT64_MAX, win[c] = 0;
                int64_t tau = lo_prev[c] != INT64_MAX ? lo_prev[c] : lo_cur[c];
                adj[c] = llround((double)((int64_t)(t0 / 1000u) - tau) * SR / 1e6);
            }
            if (r < 0)
                break;                         /* 신호(멈춤) 또는 장치 오류 */
        }
        if (fd >= 0) {                         /* 파일 입력. mic와 함께면 mic block 하나(64샘플)만큼 */
        if (pace) {                            /* block이 실시간으로 들어온다고 보고 그 도착 시각을 t_host로 쓴다 */
            t_arr = pace_arr(t0, d0, S + (uint64_t)B);
            struct timespec ts = {(time_t)(t_arr / 1000000000u), (long)(t_arr % 1000000000u)};
            while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) == EINTR && !stop_main) {}
        }
        while (have < (pace || nmic ? want : fb) && !stop_main) {
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
        nfr = have / fb;
        for (size_t s = 0; s < nfr; s++)
            for (int c = 0; c < C; c++)
                ring[(size_t)(nmic + c) * RING + ((S + s) & (RING - 1))] = (int16_t)get16(buf + s * fb + 2 * (size_t)c);
        memmove(buf, buf + nfr * fb, have - nfr * fb);
        have -= nfr * fb;
        }
        S += nfr;

        for (;;) {                             /* Frame 끝이 S 안에 든 모델 그룹을 offset 순서로 */
            int m = (int)(n_ev % N_MODELS);
            uint32_t k = (uint32_t)(n_ev / N_MODELS);
            uint64_t end = (uint64_t)OFFSET_SAMPLES(m) + (uint64_t)HOP * k + FRAME;   /* mic면 장치마다 + adj */
            int64_t amax = nmic ? INT64_MIN : 0;
            for (int c = 0; c < nmic; c++)
                amax = adj[c] > amax ? adj[c] : amax;
            if ((int64_t)end + amax > (int64_t)S)
                break;
            n_ev++;
            int cnt = n_of[m], first = k % SEG == 0;   /* 판정 주기 첫 frame */
            if (!cnt)
                continue;
            uint64_t ts = mono_ns(), thc[MAX_MIC];
            uint32_t dd = atomic_load(&diff_us);
            t_arr = nmic ? UINT64_MAX : t_arr;     /* mic: 모델 그룹 기록의 t_host = 그룹 추론 요청 중 가장 이른 것(다른 mic block을 기다린 시간이 G에 든다) */
            for (int c = 0; c < nmic; c++)           /* 장치마다 frame 끝 샘플이 든 block의 도착 = t_host */
                thc[c] = tarr[c][(((uint64_t)((int64_t)end + adj[c]) - 1) / MIC_BLOCK) % (RING / MIC_BLOCK)];
            if (nmic && adj_first == INT64_MIN) {    /* 첫 frame. 장치를 차례로 시작하는 동안(USB 하나에 16 ms 넘게) 난 xrun은 세지 않는다 */
                adj_first = adj[0];
                for (int c = 0; c < nmic; c++)
                    mic[c].xrun = 0;
            }
            for (int j = 0; j < cnt; j++) {
                int tr = tracks_of[m][j];
                const int16_t *rc = ring + (size_t)ch_of[tr] * RING;
                uint64_t e = nmic ? (uint64_t)((int64_t)end + adj[mic_of[tr]]) : end, th = nmic ? thc[mic_of[tr]] : t_arr;
                if (nmic && th < t_arr)
                    t_arr = th;
                float x[FRAME], db[NMEL];
                if (vch && ch_of[tr] >= nmic) {    /* 가상 트랙: 파일 위치 = (샘플 번호 + voff) mod VL */
                    const int16_t *vc = vch + (uint64_t)(ch_of[tr] - nmic) * VL;
                    uint64_t o = (e - FRAME + voff[tr]) % VL;
                    for (int n = 0; n < FRAME; n++, o = o + 1 == VL ? 0 : o + 1)
                        x[n] = vc[o] / 32768.0f;
                } else
                    for (int n = 0; n < FRAME; n++)
                        x[n] = rc[(e - FRAME + (uint64_t)n) & (RING - 1)] / 32768.0f;
                mel_db(x, db);
                uint8_t *p = pkt + (size_t)j * REQ_B;
                memset(p, 0, REQ_B);
                p[0] = 0xA5;
                p[1] = (uint8_t)first;         /* RESET_STATE: 판정 주기 첫 추론 요청 */
                put16(p + 2, (uint32_t)tr);
                put16(p + 4, k & 0xFFFF);
                p[6] = (uint8_t)m;
                put32(p + 8, (uint32_t)(th / 1000u) + dd);
                put32(p + 12, (uint32_t)cnt);  /* n_expect: 이 모델·주기의 추론 요청 수 */
                norm_q(db, floor_of[tr], &hi[tr], &lo[tr], &has_ref[tr], p + 16);
            }
            uint64_t tr_ns = mono_ns();
            for (int j = 0; j < cnt; j++) {
                int tr = tracks_of[m][j];
                pend[tr][k & 7].t_host_ns = nmic ? thc[mic_of[tr]] : t_arr;
                atomic_store_explicit(&pend[tr][k & 7].kk, k + 1, memory_order_release);
                last_k[tr] = (int32_t)k;
            }
            for (int j = 0; j < cnt; j += REQ_PER_DG) {
                size_t len = (size_t)(cnt - j < REQ_PER_DG ? cnt - j : REQ_PER_DG) * REQ_B;
                send_err += send(fd_req, pkt + (size_t)j * REQ_B, len, 0) != (ssize_t)len;
            }
            sent += (uint64_t)cnt;
            if (f_model_group)
                fprintf(f_model_group, "%u,%d,%.3f,%d,%llu,%llu,%llu,%llu\n", k, m, (double)(tr_ns - t_arr) / 1e3, cnt,
                        (unsigned long long)t_arr, (unsigned long long)ts, (unsigned long long)tr_ns,
                        (unsigned long long)mono_ns());
        }
        if (pace && mono_ns() > pace_arr(t0, d0, S + (uint64_t)B))
            overrun++;                         /* 다음 block이 들어올 때까지 계산을 못 끝냄 */
        if (eof)
            break;
    }

    usleep(2 * PERIOD_US);                     /* Deadline이 지날 때까지 남은 결과를 받는다 */
    atomic_store(&stop_rx, 1);
    atomic_store(&stop_sync, 1);
    pthread_join(th_rx, NULL);
    pthread_join(th_sy, NULL);
    uint64_t full = 0, mic_xrun = 0;
    for (int c = 0; c < nmic; c++)
        mic_xrun += mic[c].xrun;
    for (int i = 0; i < n_tracks; i++)
        full += (uint64_t)(last_k[i] + 1) / SEG;
    uint64_t lost = sent > rx.recv ? sent - rx.recv : 0;
    fflush(stdout);
    fprintf(stderr, "summary sent=%llu recv=%llu late=%llu lost=%llu deadline_miss=%llu judged=%llu missing_cycles=%llu "
                    "unmatched=%llu response_time_mean_us=%.1f response_time_max_us=%.1f overrun=%llu send_err=%llu sync_ok=%llu sync_fail=%llu "
                    "sync_rtt_max_us=%u audio_s=%.3f mic_xrun=%llu mic_adj_change=%lld\n",
            (unsigned long long)sent, (unsigned long long)rx.recv, (unsigned long long)rx.late, (unsigned long long)lost,
            (unsigned long long)(rx.late + lost), (unsigned long long)rx.judged, (unsigned long long)(full - rx.judged),
            (unsigned long long)rx.unmatched, rx.recv ? rx.response_time_sum / (double)rx.recv : 0.0, rx.response_time_max,
            (unsigned long long)overrun, (unsigned long long)send_err, (unsigned long long)sy.ok,
            (unsigned long long)sy.fail, sy.rtt_max, (double)S / SR, (unsigned long long)mic_xrun,
            (long long)(nmic && adj_first != INT64_MIN ? adj[0] - adj_first : 0));
    if (f_res)
        fclose(f_res);
    if (f_model_group)
        fclose(f_model_group);
    return 0;
}
