/* ============================================================
 * pcie_lat.c — P3.3 PCIe Host↔FPGA 지연·지터 측정 (FPGA Host, root 권한)
 * ============================================================
 * 대상 설계: p3_top (XDMA Gen2 ×2, BAR0 = AXI-Lite 레지스터 64 KiB, 설정 BAR =
 * XDMA 레지스터, DMA 주소 0x0001_0000 = BRAM 64 KiB, 0x8000_0000 = DDR3 1 GiB).
 * 필요한 장치 파일: /dev/xdma0_user, /dev/xdma0_control, /dev/xdma0_h2c_0, /dev/xdma0_c2h_0
 *
 * 빌드: gcc -O2 -Wall -o pcie_lat pcie_lat.c
 * 사용: sudo ./pcie_lat <시험> [-n 횟수] [-s 크기 B] [-a AXI 주소] [-p 주기 µs] [-w 워드 수]
 *                        [-f 파일] [-o 출력 파일]
 * 시험:
 *   mmio_rd     BAR0 SCRATCH 32 bit 읽기 1회 왕복 (레지스터 블록까지: SmartConnect·CDC 포함)
 *   mmio_cfg    설정 BAR(XDMA 내부 레지스터 0x0) 읽기 1회 왕복 (사용자 로직 없음)
 *   mmio_wr     SCRATCH에 32 bit 쓰기 w회 + 읽기 1회(쓰기 완료 보장)까지의 시간
 *   ts_sync     (호스트 t0, FPGA TS, 호스트 t1) 표본 — 시계 오프셋·드리프트 추정용
 *   h2c         write(): 호스트 → FPGA DMA, 크기 s, 1회 시간
 *   c2h         read():  FPGA → 호스트 DMA
 *   rt          h2c 후 c2h 후 비교, 왕복 시간
 *   load        파일을 H2C로 쓰고 C2H로 읽어 비교, 처리량 (모델 이미지 적재)
 * 출력: 표본마다 한 줄. 기본은 지연(ns). ts_sync는 "t0_ns ts_cycles t1_ns".
 * -p를 주면 각 표본을 주기 경계(CLOCK_MONOTONIC 절대 시각)에 맞춰 시작한다.
 * 시각은 CLOCK_MONOTONIC_RAW(NTP 보정 없음)로 잰다.
 * ============================================================ */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define REG_SCRATCH 0x000C
#define REG_TS_LO   0x0010
#define REG_TS_HI   0x0014
#define REG_DDR_SEL 0x0044

static inline uint64_t now_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC_RAW, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + t.tv_nsec;
}

static void die(const char *m)
{
    fprintf(stderr, "오류: %s (%s)\n", m, strerror(errno));
    exit(1);
}

static volatile uint32_t *map_bar(const char *path, size_t len)
{
    int fd = open(path, O_RDWR | O_SYNC);
    if (fd < 0) die(path);
    void *p = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED) die("mmap");
    return (volatile uint32_t *)p;
}

static void wait_period(uint64_t period_ns, struct timespec *next)
{
    if (!period_ns) return;
    next->tv_nsec += period_ns;
    while (next->tv_nsec >= 1000000000L) { next->tv_nsec -= 1000000000L; next->tv_sec++; }
    clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, next, NULL);
}

static void xfer_all(int fd, void *buf, size_t sz, uint64_t addr, int wr)
{
    size_t done = 0;
    while (done < sz) {
        if (lseek(fd, (off_t)(addr + done), SEEK_SET) < 0) die("lseek");
        ssize_t r = wr ? write(fd, (char *)buf + done, sz - done)
                       : read(fd, (char *)buf + done, sz - done);
        if (r <= 0) die(wr ? "write" : "read");
        done += (size_t)r;
    }
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "사용: %s <mmio_rd|mmio_cfg|mmio_wr|ts_sync|h2c|c2h|rt|load> [옵션]\n", argv[0]);
        return 1;
    }
    const char *test = argv[1];
    long n = 10000, words = 12;
    size_t size = 64;
    uint64_t addr = 0x10000, period_ns = 0;
    const char *file = NULL, *outp = NULL;
    int c;
    optind = 2;
    while ((c = getopt(argc, argv, "n:s:a:p:w:f:o:")) != -1) {
        switch (c) {
        case 'n': n = strtol(optarg, NULL, 0); break;
        case 's': size = strtoul(optarg, NULL, 0); break;
        case 'a': addr = strtoull(optarg, NULL, 0); break;
        case 'p': period_ns = (uint64_t)(strtod(optarg, NULL) * 1000.0); break;
        case 'w': words = strtol(optarg, NULL, 0); break;
        case 'f': file = optarg; break;
        case 'o': outp = optarg; break;
        default: return 1;
        }
    }
    FILE *out = outp ? fopen(outp, "w") : stdout;
    if (!out) die("출력 파일");

    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);

    if (!strcmp(test, "mmio_rd") || !strcmp(test, "mmio_cfg") || !strcmp(test, "mmio_wr") ||
        !strcmp(test, "ts_sync")) {
        int cfg = !strcmp(test, "mmio_cfg");
        volatile uint32_t *bar = map_bar(cfg ? "/dev/xdma0_control" : "/dev/xdma0_user", 0x10000);
        uint64_t *t = malloc(sizeof(uint64_t) * 3 * n);
        if (!t) die("malloc");
        volatile uint32_t sink = 0;
        for (long i = 0; i < 1000; i++) sink += bar[cfg ? 0 : REG_SCRATCH / 4];  /* 예열 */
        for (long i = 0; i < n; i++) {
            wait_period(period_ns, &next);
            if (!strcmp(test, "ts_sync")) {
                uint64_t t0 = now_ns();
                uint32_t lo = bar[REG_TS_LO / 4];
                uint64_t t1 = now_ns();
                uint32_t hi = bar[REG_TS_HI / 4];
                t[3 * i] = t0;
                t[3 * i + 1] = ((uint64_t)hi << 32) | lo;
                t[3 * i + 2] = t1;
            } else if (!strcmp(test, "mmio_wr")) {
                uint64_t t0 = now_ns();
                for (long k = 0; k < words; k++) bar[REG_SCRATCH / 4] = (uint32_t)(i * words + k);
                sink += bar[REG_SCRATCH / 4];
                t[i] = now_ns() - t0;
            } else {
                uint64_t t0 = now_ns();
                sink += bar[cfg ? 0 : REG_SCRATCH / 4];
                t[i] = now_ns() - t0;
            }
        }
        if (!strcmp(test, "ts_sync"))
            for (long i = 0; i < n; i++)
                fprintf(out, "%lu %lu %lu\n", t[3 * i], t[3 * i + 1], t[3 * i + 2]);
        else
            for (long i = 0; i < n; i++) fprintf(out, "%lu\n", t[i]);
        (void)sink;
        return 0;
    }

    if (!strcmp(test, "h2c") || !strcmp(test, "c2h") || !strcmp(test, "rt")) {
        int fh = open("/dev/xdma0_h2c_0", O_RDWR);
        int fc = open("/dev/xdma0_c2h_0", O_RDWR);
        if (fh < 0 || fc < 0) die("xdma 장치 파일");
        void *tx, *rx;
        if (posix_memalign(&tx, 4096, size) || posix_memalign(&rx, 4096, size)) die("memalign");
        for (size_t k = 0; k < size; k++) ((uint8_t *)tx)[k] = (uint8_t)rand();
        uint64_t *t = malloc(sizeof(uint64_t) * n);
        long bad = 0;
        for (long i = 0; i < 20; i++) xfer_all(fh, tx, size, addr, 1);    /* 예열 */
        for (long i = 0; i < n; i++) {
            wait_period(period_ns, &next);
            if (!strcmp(test, "rt")) ((uint32_t *)tx)[0] = (uint32_t)i;
            uint64_t t0 = now_ns();
            if (strcmp(test, "c2h")) xfer_all(fh, tx, size, addr, 1);
            if (strcmp(test, "h2c")) xfer_all(fc, rx, size, addr, 0);
            t[i] = now_ns() - t0;
            if (!strcmp(test, "rt") && memcmp(tx, rx, size)) bad++;
        }
        for (long i = 0; i < n; i++) fprintf(out, "%lu\n", t[i]);
        if (!strcmp(test, "rt")) fprintf(stderr, "rt 비교 불일치 %ld / %ld\n", bad, n);
        return bad ? 2 : 0;
    }

    if (!strcmp(test, "load")) {
        if (!file) { fprintf(stderr, "-f 파일 필요\n"); return 1; }
        int ff = open(file, O_RDONLY);
        if (ff < 0) die(file);
        struct stat st;
        fstat(ff, &st);
        size_t sz = ((size_t)st.st_size + 31) & ~(size_t)31;
        void *tx, *rx;
        if (posix_memalign(&tx, 4096, sz) || posix_memalign(&rx, 4096, sz)) die("memalign");
        memset(tx, 0, sz);
        if (read(ff, tx, st.st_size) != st.st_size) die("파일 읽기");
        int fh = open("/dev/xdma0_h2c_0", O_RDWR);
        int fc = open("/dev/xdma0_c2h_0", O_RDWR);
        if (fh < 0 || fc < 0) die("xdma 장치 파일");
        for (long i = 0; i < n; i++) {
            memset(rx, 0xEE, sz);
            uint64_t t0 = now_ns();
            xfer_all(fh, tx, sz, addr, 1);
            uint64_t t1 = now_ns();
            xfer_all(fc, rx, sz, addr, 0);
            uint64_t t2 = now_ns();
            int ok = !memcmp(tx, rx, sz);
            fprintf(out, "load %zu B h2c %lu ns (%.1f MB/s) c2h %lu ns (%.1f MB/s) %s\n", sz,
                    t1 - t0, sz * 1e3 / (double)(t1 - t0), t2 - t1, sz * 1e3 / (double)(t2 - t1),
                    ok ? "MATCH" : "MISMATCH");
            if (!ok) return 2;
        }
        return 0;
    }
    fprintf(stderr, "알 수 없는 시험: %s\n", test);
    return 1;
}
