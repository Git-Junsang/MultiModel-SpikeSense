/* setup.c — 시작 설정(06 §6 1~6)과 종료. PNU 표 값은 04 §3.1, 06 §7.4의 식이다.
 *
 * PNU 표(engine part_cache.PNURTL._tables와 같은 칸):
 *   LUT_G[i]     = δ_G((i + 0.5) × 256 µs) = G > e인 표본에서 구한 G − e의 평균, EG = δ_G(0) = G의 평균, TAU_G = G 최대(올림)
 *   LUT_U[i][rb] = (J − x) / (r + 1), x = (i + 0.5) × 256 µs < J, r = 남은 수 칸 대표값. TAU_U = J
 * G 표본은 묶음 지연 표(CSV의 delay_us 열)다. run의 --log가 만드는 <이름>_bundle.csv나 p326_m3_group.py 출력을 쓴다.
 * engine은 δ_G를 5 µs 칸 수치 적분으로 구해 몇 µs 다를 수 있다. 표 칸이 256 µs라 무시한다. */
#define _GNU_SOURCE
#include <getopt.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "host.h"

#define LUT_BINS 128
#define LUT_BIN_US 256
static const double REMAIN[6] = {1.0, 2.0, 3.5, 6.5, 12.5, 24.0};

static uint32_t u16(double v, const char *name)
{
    if (v > 65535.0) {
        fprintf(stderr, "경고: %s %.0f µs가 16 bit를 넘어 65,535로 둔다\n", name, v);
        return 65535;
    }
    return (uint32_t)v;
}

/* 반환 G 표본 수(없으면 0, 오류 −1). tau = {TAU_G, TAU_U, EG} */
static long pnu_tables(const char *trace, double J, uint32_t *tau, uint32_t *lut_g, uint32_t *lut_u)
{
    double *g = NULL, gmax = 0;
    long n = 0, cap = 0;
    if (trace && *trace) {
        FILE *f = fopen(trace, "r");
        char line[4096];
        int col = -1;
        if (!f || !fgets(line, sizeof line, f)) {
            fprintf(stderr, "묶음 지연 표 %s를 읽을 수 없다\n", trace);
            if (f)
                fclose(f);
            return -1;
        }
        char *tok = strtok(line, ",\r\n");
        for (int c = 0; tok; c++, tok = strtok(NULL, ",\r\n"))
            if (strcmp(tok, "delay_us") == 0)
                col = c;
        if (col < 0) {
            fprintf(stderr, "%s에 delay_us 열이 없다\n", trace);
            fclose(f);
            return -1;
        }
        while (fgets(line, sizeof line, f)) {
            char *p = line;
            for (int c = 0; c < col && p; c++)
                if ((p = strchr(p, ',')))
                    p++;
            if (!p)
                continue;
            if (n == cap)
                g = realloc(g, (size_t)(cap = cap ? 2 * cap : 4096) * sizeof *g);
            g[n] = strtod(p, NULL);
            gmax = fmax(gmax, g[n++]);
        }
        fclose(f);
    }
    for (int i = 0; i <= LUT_BINS; i++) {           /* i = LUT_BINS는 EG(e = 0) */
        double e = i < LUT_BINS ? (i + 0.5) * LUT_BIN_US : 0.0, s = 0;
        long c = 0;
        for (long t = 0; t < n; t++)
            if (g[t] > e) {
                s += g[t] - e;
                c++;
            }
        double d = c ? rint(s / c) : 0.0;
        if (i < LUT_BINS)
            lut_g[i] = u16(d, "LUT_G");
        else
            tau[2] = u16(d, "EG");
    }
    tau[0] = u16(ceil(gmax), "TAU_G");
    tau[1] = u16(ceil(J), "TAU_U");
    for (int i = 0; i < LUT_BINS; i++)
        for (int rb = 0; rb < 8; rb++) {
            double x = (i + 0.5) * LUT_BIN_US;
            lut_u[i * 8 + rb] = rb < 6 && x < J ? u16(rint((J - x) / (REMAIN[rb] + 1.0)), "LUT_U") : 0;
        }
    free(g);
    return n;
}

static int must(int st, const char *what)
{
    if (st != 0)
        fprintf(stderr, "%s 실패 (status %d%s)\n", what, st, st < 0 ? ", 응답 없음" : "");
    return st != 0;
}

/* 같은 주소로 1 KiB씩 쓰고 다시 읽어 비교 */
static int write_verify(ctl_t *c, uint32_t addr, const uint8_t *src, int bytes, const char *what)
{
    uint32_t w[256], r[256];
    for (int off = 0; off < bytes; off += 1024) {
        int cnt = (bytes - off < 1024 ? bytes - off : 1024) / 4;
        for (int i = 0; i < cnt; i++)
            w[i] = get32(src + off + 4 * i);
        if (must(ctl_rw(c, 2, addr + (uint32_t)off, cnt, w), what) || must(ctl_rw(c, 1, addr + (uint32_t)off, cnt, r), what))
            return -1;
        if (memcmp(w, r, (size_t)cnt * 4) != 0) {
            fprintf(stderr, "%s: 0x%08X 다시 읽은 값이 다르다\n", what, addr + (uint32_t)off);
            return -1;
        }
    }
    return 0;
}

int cmd_setup(int argc, char **argv)
{
    const char *ip = "192.168.10.2", *map = NULL, *models = NULL, *trace = NULL;
    int n_tracks = MAX_TRACKS;
    double J = 0, margin = 0;
    static struct option o[] = {{"fpga", 1, 0, 'f'}, {"tracks", 1, 0, 'n'}, {"map", 1, 0, 'p'}, {"models", 1, 0, 'm'},
                                {"group-trace", 1, 0, 'g'}, {"jitter-us", 1, 0, 'j'}, {"margin-us", 1, 0, 'r'}, {0}};
    for (int ch; (ch = getopt_long(argc, argv, "", o, NULL)) != -1;)
        switch (ch) {
        case 'f': ip = optarg; break;
        case 'n': n_tracks = atoi(optarg); break;
        case 'p': map = optarg; break;
        case 'm': models = optarg; break;
        case 'g': trace = optarg; break;
        case 'j': J = atof(optarg); break;
        case 'r': margin = atof(optarg); break;
        default: return 2;
        }
    uint8_t model[MAX_TRACKS];
    if (n_tracks < 1 || n_tracks > MAX_TRACKS || (n_tracks = load_map(map, n_tracks, model)) < 0)
        return 2;
    ctl_t c;
    if (ctl_open(&c, ip, 100, 5) < 0)
        return 1;

    /* 1~2. 설계 확인, MIG 보정, 합성 parameter */
    uint32_t info[4], st;
    if (must(ctl_rw(&c, 1, A_ID, 4, info), "정보 읽기") || must(ctl_rd1(&c, A_STATUS, &st), "STATUS 읽기"))
        return 1;
    printf("ID 0x%08X, VERSION 0x%08X, N_ENTRY %u, N_ONCHIP %u, STATUS 0x%X\n", info[0], info[1], info[2], info[3], st);
    if (info[0] != FPGA_ID || !(st & 4) || (st & 1)) {
        fprintf(stderr, "ID가 다르거나 MIG 보정 전이거나 RUN = 1이다(먼저 stop)\n");
        return 1;
    }

    /* 3. 모델 image: slot마다 앞 131,648 B */
    if (models) {
        FILE *f = fopen(models, "rb");
        uint8_t *img = malloc((size_t)N_MODELS * SLOT_B);
        size_t sz = f ? fread(img, 1, (size_t)N_MODELS * SLOT_B, f) : 0;
        if (f)
            fclose(f);
        if (sz == 0 || sz % SLOT_B) {
            fprintf(stderr, "모델 image %s 크기 %zu B가 slot(256 KiB)의 배수가 아니다\n", models, sz);
            return 1;
        }
        uint64_t t0 = mono_ns();
        for (size_t m = 0; m < sz / SLOT_B; m++)
            if (write_verify(&c, A_DDR + (uint32_t)(m * SLOT_B), img + m * SLOT_B, SLOT_USED, "모델 적재"))
                return 1;
        printf("모델 %zu개 적재·확인 %.2f s\n", sz / SLOT_B, (mono_ns() - t0) / 1e9);
        free(img);
    }

    /* 4. 설정 블록, PNU 표 */
    uint32_t cfg[6] = {(uint32_t)n_tracks, N_MODELS, 0, STATE_BASE, PERIOD_US, (uint32_t)margin}, rb[6];
    if (must(ctl_rw(&c, 2, A_CONFIG, 6, cfg), "설정 쓰기") || must(ctl_rw(&c, 1, A_CONFIG, 6, rb), "설정 읽기"))
        return 1;
    if (memcmp(cfg, rb, sizeof cfg) != 0) {
        fprintf(stderr, "설정 다시 읽은 값이 다르다\n");
        return 1;
    }
    uint32_t off[N_MODELS], nreg[N_MODELS] = {0}, tau[3], lut_g[LUT_BINS], lut_u[LUT_BINS * 8];
    for (int m = 0; m < N_MODELS; m++)
        off[m] = (uint32_t)m;                      /* offset 배정: 모델 m → offset 번호 m */
    for (int i = 0; i < n_tracks; i++)
        nreg[model[i]]++;
    long ns = pnu_tables(trace, J, tau, lut_g, lut_u);
    if (ns < 0)
        return 1;
    if (must(ctl_rw(&c, 2, A_OFFSET, N_MODELS, off), "OFFSET_TABLE") || must(ctl_rw(&c, 2, A_NREG, N_MODELS, nreg), "N_REG") ||
        must(ctl_rw(&c, 2, A_TAU, 3, tau), "TAU_G·TAU_U·EG") || must(ctl_rw(&c, 2, A_LUT_G, LUT_BINS, lut_g), "LUT_G"))
        return 1;
    for (int k = 0; k < 4; k++)
        if (must(ctl_rw(&c, 2, A_LUT_U + 1024u * k, 256, lut_u + 256 * k), "LUT_U"))
            return 1;
    printf("트랙 %d, PNU 표: G 표본 %ld개, TAU_G %u µs, EG %u µs, J %u µs\n", n_tracks, ns, tau[0], tau[2], tau[1]);

    /* 5~6. SOFT_RESET, RUN */
    if (must(ctl_wr1(&c, A_CTRL, 2), "SOFT_RESET") || must(ctl_wr1(&c, A_CTRL, 1), "RUN") || must(ctl_rd1(&c, A_STATUS, &st), "STATUS"))
        return 1;
    printf("RUN, STATUS 0x%X\n", st);
    return (st & 1) ? 0 : 1;
}

int cmd_stop(int argc, char **argv)
{
    static const char *names[] = {"REQ_IN", "REQ_DROP", "RES_OUT", "LATE", "MAX_PENDING", "BATCHES", "MODEL_LOADS",
                                  "SAT_COUNT", "WEIGHT_BYTES", NULL, "STATE_BYTES", NULL, "CMP_BUSY", NULL, "CMP_STALL", NULL};
    const char *ip = "192.168.10.2";
    static struct option o[] = {{"fpga", 1, 0, 'f'}, {0}};
    for (int ch; (ch = getopt_long(argc, argv, "", o, NULL)) != -1;)
        if (ch == 'f')
            ip = optarg;
        else
            return 2;
    ctl_t c;
    uint32_t st = 0, cnt[16], err[2];
    if (ctl_open(&c, ip, 100, 5) < 0)
        return 1;
    /* 추론 요청을 멈춘 뒤 IDLE = 1을 기다린다 */
    for (int i = 0; i < 200 && ctl_rd1(&c, A_STATUS, &st) == 0 && !(st & 2); i++)
        usleep(10000);
    if (!(st & 2))
        fprintf(stderr, "경고: IDLE = 1이 되지 않았다 (STATUS 0x%X)\n", st);
    if (must(ctl_wr1(&c, A_CTRL, 0), "RUN = 0") || must(ctl_rw(&c, 1, A_CNT, 16, cnt), "counter") ||
        must(ctl_rw(&c, 1, A_ERR, 2, err), "오류"))
        return 1;
    for (int i = 0; i < 16; i++)
        if (names[i])
            printf("%s %llu\n", names[i], i >= 8 ? (unsigned long long)cnt[i] | (unsigned long long)cnt[i + 1] << 32
                                                 : (unsigned long long)cnt[i]);
    printf("ERR_CODE %u\nERR_INFO %u\n", err[0], err[1]);
    return 0;
}
