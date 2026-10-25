/* ctl.c — 제어 packet(06 §7.6), FPGA 시각 맞추기(06 §5), 트랙 → 모델 대응
 * 제어 요청은 응답을 받은 뒤 다음을 보낸다. 응답이 없으면 같은 tag로 다시 보낸다(같은 주소에 같은 값이라 결과가 같다). */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#include "host.h"

uint64_t mono_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000u + (uint64_t)t.tv_nsec;
}

void put16(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
void put32(uint8_t *p, uint32_t v) { put16(p, v); put16(p + 2, v >> 16); }
uint32_t get16(const uint8_t *p) { return p[0] | (uint32_t)p[1] << 8; }
uint32_t get32(const uint8_t *p) { return get16(p) | get16(p + 2) << 16; }

int udp_open(const char *ip, int port)
{
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port)};
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0 || inet_pton(AF_INET, ip, &a.sin_addr) != 1 || connect(fd, (struct sockaddr *)&a, sizeof a) < 0) {
        fprintf(stderr, "UDP %s:%d를 열 수 없다\n", ip, port);
        if (fd >= 0)
            close(fd);
        return -1;
    }
    return fd;
}

int ctl_open(ctl_t *c, const char *ip, int timeout_ms, int retries)
{
    c->fd = udp_open(ip, CTL_PORT);
    c->tag = (uint16_t)(mono_ns() >> 10);
    c->timeout_ms = timeout_ms;
    c->retries = retries;
    return c->fd < 0 ? -1 : 0;
}

int ctl_rw(ctl_t *c, int op, uint32_t addr, int count, uint32_t *data)
{
    uint8_t req[12 + 1024], rsp[12 + 1024 + 16];
    int n = 12 + (op == 2 ? 4 * count : 0);
    req[0] = 0x5C;
    req[1] = (uint8_t)op;
    put16(req + 2, ++c->tag);
    put32(req + 4, addr);
    put16(req + 8, (uint32_t)count);
    put16(req + 10, 0);
    if (op == 2)
        for (int i = 0; i < count; i++)
            put32(req + 12 + 4 * i, data[i]);
    for (int t = 0; t <= c->retries; t++) {
        if (send(c->fd, req, n, 0) != n)
            return -1;
        uint64_t end = mono_ns() + (uint64_t)c->timeout_ms * 1000000u;
        for (;;) {
            uint64_t now = mono_ns();
            struct pollfd p = {.fd = c->fd, .events = POLLIN};
            if (now >= end || poll(&p, 1, (int)((end - now) / 1000000u) + 1) <= 0)
                break;
            ssize_t r = recv(c->fd, rsp, sizeof rsp, 0);
            if (r < 12 || memcmp(rsp, req, 10) != 0)
                continue;                      /* 늦게 온 이전 응답이나 다른 packet */
            int st = (int)get16(rsp + 10);
            if (st == 0 && op == 1) {
                if (r != 12 + 4 * count)
                    return 3;
                for (int i = 0; i < count; i++)
                    data[i] = get32(rsp + 12 + 4 * i);
            }
            return st;
        }
    }
    return -1;
}

int ctl_rd1(ctl_t *c, uint32_t addr, uint32_t *v) { return ctl_rw(c, 1, addr, 1, v); }
int ctl_wr1(ctl_t *c, uint32_t addr, uint32_t v) { return ctl_rw(c, 2, addr, 1, &v); }

/* clock_diff = f − (h1 + h2) / 2. 왕복을 tries번 재서 가장 짧은 것을 쓴다(06 §5). µs 32 bit라 차이도 2^32로 되감는다 */
int clock_diff(ctl_t *c, int tries, uint32_t *diff, uint32_t *rtt_us)
{
    uint64_t best = UINT64_MAX;
    for (int i = 0; i < tries; i++) {
        uint32_t f;
        uint64_t h1 = mono_ns();
        if (ctl_rd1(c, A_NOW_US, &f) != 0)
            continue;
        uint64_t h2 = mono_ns();
        if (h2 - h1 < best) {
            best = h2 - h1;
            *diff = f - (uint32_t)((h1 + h2) / 2000u);
        }
    }
    if (best == UINT64_MAX)
        return -1;
    *rtt_us = (uint32_t)(best / 1000u);
    return 0;
}

int load_map(const char *path, int n_tracks, uint8_t *model)
{
    if (!path || !*path) {
        for (int i = 0; i < n_tracks; i++)
            model[i] = (uint8_t)(i % N_MODELS);
        return n_tracks;
    }
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "map 파일 %s를 열 수 없다\n", path);
        return -1;
    }
    int n = 0, m;
    while (fscanf(f, "%d", &m) == 1) {
        if (m < 0 || m >= N_MODELS || n >= MAX_TRACKS) {
            fprintf(stderr, "map %s: 줄 %d의 model_id %d 또는 트랙 수가 범위 밖\n", path, n + 1, m);
            fclose(f);
            return -1;
        }
        model[n++] = (uint8_t)m;
    }
    fclose(f);
    if (n == 0)
        fprintf(stderr, "map %s에 트랙이 없다\n", path);
    return n ? n : -1;
}
