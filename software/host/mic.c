/* mic.c — USB mic 입력(P4.8, 06 §2·§5). libasound 없이 ALSA 커널 interface(ioctl)로 열어 정적 링크를 유지한다.
 *
 * 48 kHz S16_LE mono, period 192 frame(4 ms = 16 kHz 64샘플 block), buffer 4 period(16 ms). P3.16 §3.7에서 buffer 8 ms 이상은 부하에서도 xrun 0.
 * Block 도착 시각 = htstamp(마지막 hw_ptr 갱신, CLOCK_MONOTONIC) − avail / 48 kHz. read()가 돌아온 시각이 아니다.
 * Resampler: scipy.signal.resample_poly(x, 1, 3) 기본값과 같은 61 tap Kaiser(β 5) FIR을 지난 샘플만 써서(causal) 계산한다.
 *   16 kHz 출력 j = Σ h[i] x[3j − i]라 resample_poly 출력보다 10샘플(0.625 ms) 늦다. 이 group delay는 t_host 앞, mic–Host 지연 쪽이다. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <sound/asound.h>
#include "host.h"

static float fir[MIC_TAPS];

static double bessel_i0(double x)
{
    double s = 1, t = 1;
    for (int k = 1; k < 50; k++) {
        t *= (x / (2 * k)) * (x / (2 * k));
        s += t;
    }
    return s;
}

/* scipy.signal.firwin(61, 1/3, window=('kaiser', 5.0)): sinc × Kaiser, 합 1로 정규화 */
void mic_fir_init(void)
{
    double s = 0, v[MIC_TAPS], a = (MIC_TAPS - 1) / 2.0;
    for (int n = 0; n < MIC_TAPS; n++) {
        double t = (n - a) / 3, r = 2.0 * n / (MIC_TAPS - 1) - 1;
        v[n] = (t == 0 ? 1.0 : sin(M_PI * t) / (M_PI * t)) * bessel_i0(5.0 * sqrt(1 - r * r));
        s += v[n];
    }
    for (int n = 0; n < MIC_TAPS; n++)
        fir[n] = (float)(v[n] / s);
}

/* 48 kHz 192샘플 → 16 kHz 64샘플. hist = 앞 block의 마지막 60샘플(처음엔 0) */
void mic_resample(float *hist, const int16_t *x48, int16_t *y16)
{
    float b[MIC_TAPS - 1 + MIC_PERIOD];
    memcpy(b, hist, sizeof(float) * (MIC_TAPS - 1));
    for (int q = 0; q < MIC_PERIOD; q++)
        b[MIC_TAPS - 1 + q] = x48[q];
    for (int j = 0; j < MIC_BLOCK; j++) {
        const float *p = b + MIC_TAPS - 1 + 3 * j;
        float acc = 0;
        for (int i = 0; i < MIC_TAPS; i++)
            acc += fir[i] * p[-i];
        long r = lrintf(acc);
        y16[j] = (int16_t)(r > 32767 ? 32767 : r < -32768 ? -32768 : r);
    }
    memcpy(hist, b + MIC_PERIOD, sizeof(float) * (MIC_TAPS - 1));
}

static void set_mask(struct snd_pcm_hw_params *p, int n, unsigned bit)
{
    struct snd_mask *m = &p->masks[n - SNDRV_PCM_HW_PARAM_FIRST_MASK];
    memset(m->bits, 0, sizeof m->bits);
    m->bits[bit >> 5] = 1u << (bit & 31);
}

static struct snd_interval *iv(struct snd_pcm_hw_params *p, int n) { return &p->intervals[n - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL]; }

static void set_int(struct snd_pcm_hw_params *p, int n, unsigned v)
{
    struct snd_interval *i = iv(p, n);
    i->min = i->max = v;
    i->integer = 1;
}

int mic_start(mic_t *m) { return ioctl(m->fd, SNDRV_PCM_IOCTL_PREPARE) < 0 || ioctl(m->fd, SNDRV_PCM_IOCTL_START) < 0 ? -1 : 0; }

/* id = ALSA card 이름(/proc/asound/<id> → cardN, 예: Microphone) 또는 card 번호. capture device 0을 연다. 시작은 mic_start */
int mic_open(mic_t *m, const char *id)
{
    char path[256], link[64] = "";
    int card = atoi(id);
    snprintf(path, sizeof path, "/proc/asound/%s", id);
    ssize_t r = readlink(path, link, sizeof link - 1);
    if (r > 4 && !strncmp(link, "card", 4))
        card = atoi(link + 4);
    else if (id[0] < '0' || id[0] > '9') {
        fprintf(stderr, "mic %s: /proc/asound/%s가 없다\n", id, id);
        return -1;
    }
    snprintf(path, sizeof path, "/dev/snd/pcmC%dD0c", card);
    memset(m, 0, sizeof *m);
    if ((m->fd = open(path, O_RDWR)) < 0) {
        fprintf(stderr, "mic %s: %s를 열 수 없다(%s)\n", id, path, strerror(errno));
        return -1;
    }
    struct snd_pcm_hw_params hw;
    memset(&hw, 0, sizeof hw);
    for (int n = SNDRV_PCM_HW_PARAM_FIRST_MASK; n <= SNDRV_PCM_HW_PARAM_LAST_MASK; n++)
        memset(hw.masks[n - SNDRV_PCM_HW_PARAM_FIRST_MASK].bits, 0xFF, sizeof hw.masks[0].bits);
    for (int n = SNDRV_PCM_HW_PARAM_FIRST_INTERVAL; n <= SNDRV_PCM_HW_PARAM_LAST_INTERVAL; n++)
        iv(&hw, n)->max = ~0u;
    hw.rmask = ~0u;
    hw.info = ~0u;
    set_mask(&hw, SNDRV_PCM_HW_PARAM_ACCESS, SNDRV_PCM_ACCESS_RW_INTERLEAVED);
    set_mask(&hw, SNDRV_PCM_HW_PARAM_FORMAT, SNDRV_PCM_FORMAT_S16_LE);
    set_mask(&hw, SNDRV_PCM_HW_PARAM_SUBFORMAT, SNDRV_PCM_SUBFORMAT_STD);
    set_int(&hw, SNDRV_PCM_HW_PARAM_SAMPLE_BITS, 16);
    set_int(&hw, SNDRV_PCM_HW_PARAM_FRAME_BITS, 16);
    set_int(&hw, SNDRV_PCM_HW_PARAM_CHANNELS, 1);
    set_int(&hw, SNDRV_PCM_HW_PARAM_RATE, MIC_RATE);
    set_int(&hw, SNDRV_PCM_HW_PARAM_PERIOD_SIZE, MIC_PERIOD);
    set_int(&hw, SNDRV_PCM_HW_PARAM_PERIODS, MIC_PERIODS);
    struct snd_pcm_sw_params sw;
    memset(&sw, 0, sizeof sw);
    sw.tstamp_mode = SNDRV_PCM_TSTAMP_ENABLE;
    sw.tstamp_type = SNDRV_PCM_TSTAMP_TYPE_MONOTONIC;   /* mono_ns()와 같은 clock */
    sw.proto = SNDRV_PCM_VERSION;
    sw.period_step = 1;
    sw.avail_min = MIC_PERIOD;
    sw.start_threshold = 1;
    sw.stop_threshold = MIC_PERIOD * MIC_PERIODS;    /* buffer가 차면 xrun */
    if (ioctl(m->fd, SNDRV_PCM_IOCTL_HW_PARAMS, &hw) < 0 || ioctl(m->fd, SNDRV_PCM_IOCTL_SW_PARAMS, &sw) < 0) {
        fprintf(stderr, "mic %s: 48 kHz mono S16_LE, period %d × %d 설정 실패(%s)\n", id, MIC_PERIOD, MIC_PERIODS, strerror(errno));
        close(m->fd);
        return -1;
    }
    return 0;
}

/* Block 하나(48 kHz 192샘플 → 16 kHz 64샘플). 0 성공, −1 xrun(다시 시작함, 그 사이 샘플은 빠진다), −2 신호·오류 */
int mic_read(mic_t *m, int16_t *y16, uint64_t *t_arr_ns)
{
    int16_t x[MIC_PERIOD];
    struct snd_xferi xf = {.buf = x, .frames = MIC_PERIOD};
    if (ioctl(m->fd, SNDRV_PCM_IOCTL_READI_FRAMES, &xf) < 0) {
        if (errno != EPIPE)
            return -2;
        m->xrun++;
        return mic_start(m) < 0 ? -2 : -1;
    }
    if (xf.result != MIC_PERIOD)                   /* 신호로 중간에 끊김 */
        return -2;
    struct snd_pcm_status st;
    memset(&st, 0, sizeof st);
    if (ioctl(m->fd, SNDRV_PCM_IOCTL_STATUS, &st) < 0)
        return -2;
    *t_arr_ns = (uint64_t)st.tstamp.tv_sec * 1000000000u + (uint64_t)st.tstamp.tv_nsec - (uint64_t)st.avail * 1000000000u / MIC_RATE;
    mic_resample(m->hist, x, y16);
    return 0;
}

/* 시험용(verify_host.py): stdin 48 kHz S16LE mono → stdout 16 kHz S16LE mono, run의 mic 입력과 같은 resampler */
int cmd_resample(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    mic_fir_init();
    float hist[MIC_TAPS - 1] = {0};
    int16_t x[MIC_PERIOD], y[MIC_BLOCK];
    while (fread(x, sizeof x, 1, stdin) == 1) {
        mic_resample(hist, x, y);
        fwrite(y, sizeof y, 1, stdout);
    }
    return 0;
}
