/* mel.c — 특징 추출: frame 하나 → mel 40개 → 0~127 (02 §3·§4, 06 §2)
 *
 * 학습 특징(software/dataset/dcase_data.py, librosa melspectrogram power 2)을 frame 하나에 쓴 것이다.
 * p325_mel_load.py의 mel_db·SegNorm·quantize_input과 같은 식이다.
 *   periodic Hann 1,024 → FFT → |X|² → Slaney mel 40 → 10·log10(max(S, 1e-10))
 *   seg 정규화: 판정 주기 첫 frame부터 지금까지의 최대·최소 dB로 [0, 1]에 늘인다. 최소는 최대 − 80 dB 아래로 내려가지 않는다
 *   x_q = clip(rint(x × 127), 0, 127)
 * 실시간 정규화는 아직 정하지 않았다(02 §5, TASKS P2.9). seg는 P3.21에서 손실이 가장 적던 방식이다.
 * shortcut: 학습의 파일 단위 평균 빼기(DC 제거)는 하지 않는다. Slaney mel 첫 filter의 DC 칸 weight가 0이라 영향이 작다. */
#define _GNU_SOURCE
#include <math.h>
#include "host.h"

#define NH    (FRAME / 2)          /* 실수 FFT 1,024 = 복소 FFT 512 + 분리 */
#define NBIN  (FRAME / 2 + 1)
#define TOP_DB 80.0

static float win[FRAME];
static float cw[NH / 2], sw[NH / 2];          /* 복소 FFT 512 twiddle */
static float rw[NBIN], iw[NBIN];              /* 실수 분리 twiddle e^{-2πik/1,024} */
static uint16_t rev[NH];
static float fb[NMEL * NBIN];                 /* filter weight. filter i는 칸 lo[i]~hi[i]만 0이 아니다 */
static int fb_lo[NMEL], fb_hi[NMEL];

static double hz_to_mel(double f)              /* librosa 기본(htk = False): 1 kHz 아래 선형, 위 log */
{
    return f < 1000.0 ? f * 3.0 / 200.0 : 15.0 + log(f / 1000.0) / (log(6.4) / 27.0);
}

static double mel_to_hz(double m)
{
    return m < 15.0 ? m * 200.0 / 3.0 : 1000.0 * exp(log(6.4) / 27.0 * (m - 15.0));
}

void mel_init(void)
{
    for (int n = 0; n < FRAME; n++)
        win[n] = (float)(0.5 - 0.5 * cos(2.0 * M_PI * n / FRAME));
    for (int k = 0; k < NH / 2; k++) {
        cw[k] = (float)cos(2.0 * M_PI * k / NH);
        sw[k] = (float)-sin(2.0 * M_PI * k / NH);
    }
    for (int k = 0; k < NBIN; k++) {
        rw[k] = (float)cos(2.0 * M_PI * k / FRAME);
        iw[k] = (float)-sin(2.0 * M_PI * k / FRAME);
    }
    int bits = 0;
    while ((1 << bits) < NH)
        bits++;
    for (int i = 0; i < NH; i++) {
        int r = 0;
        for (int j = 0; j < bits; j++)
            r |= ((i >> j) & 1) << (bits - 1 - j);
        rev[i] = (uint16_t)r;
    }
    /* librosa.filters.mel(sr 16,000, n_fft 1,024, n_mels 40, norm 'slaney') */
    double mf[NMEL + 2], m0 = hz_to_mel(0.0), m1 = hz_to_mel(SR / 2.0);
    for (int i = 0; i < NMEL + 2; i++)
        mf[i] = mel_to_hz(m0 + (m1 - m0) * i / (NMEL + 1));
    for (int i = 0; i < NMEL; i++) {
        fb_lo[i] = NBIN;
        fb_hi[i] = -1;
        double enorm = 2.0 / (mf[i + 2] - mf[i]);
        for (int k = 0; k < NBIN; k++) {
            double f = (double)k * SR / FRAME;
            double lower = (f - mf[i]) / (mf[i + 1] - mf[i]), upper = (mf[i + 2] - f) / (mf[i + 2] - mf[i + 1]);
            double w = fmax(0.0, fmin(lower, upper));
            fb[i * NBIN + k] = (float)((float)w * enorm);
            if (w > 0) {
                if (k < fb_lo[i]) fb_lo[i] = k;
                fb_hi[i] = k;
            }
        }
    }
}

void mel_db(const float *x, float *db)
{
    float re[NH], im[NH], p[NBIN];
    for (int n = 0; n < NH; n++) {             /* z[n] = x[2n] + i·x[2n+1], bit 역순 자리에 */
        re[rev[n]] = x[2 * n] * win[2 * n];
        im[rev[n]] = x[2 * n + 1] * win[2 * n + 1];
    }
    for (int len = 2; len <= NH; len <<= 1) {
        int half = len >> 1, step = NH / len;
        for (int s = 0; s < NH; s += len)
            for (int j = 0; j < half; j++) {
                float wr = cw[j * step], wi = sw[j * step];
                int a = s + j, b = a + half;
                float tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
                re[b] = re[a] - tr; im[b] = im[a] - ti;
                re[a] += tr;        im[a] += ti;
            }
    }
    for (int k = 0; k < NBIN; k++) {           /* X[k] = E[k] + W^k·O[k] */
        int a = k % NH, b = (NH - k) % NH;
        float er = 0.5f * (re[a] + re[b]), ei = 0.5f * (im[a] - im[b]);
        float or_ = 0.5f * (im[a] + im[b]), oi = -0.5f * (re[a] - re[b]);
        float xr = er + rw[k] * or_ - iw[k] * oi, xi = ei + rw[k] * oi + iw[k] * or_;
        p[k] = xr * xr + xi * xi;
    }
    for (int i = 0; i < NMEL; i++) {
        float s = 0;
        for (int k = fb_lo[i]; k <= fb_hi[i]; k++)
            s += p[k] * fb[i * NBIN + k];
        db[i] = 10.0f * log10f(fmaxf(s, 1e-10f));
    }
}

void seg_norm_q(const float *db, double *hi, double *lo, int first, uint8_t *q)
{
    double h = db[0], l = db[0];
    for (int i = 1; i < NMEL; i++) {
        h = fmax(h, db[i]);
        l = fmin(l, db[i]);
    }
    if (!first) {
        h = fmax(h, *hi);
        l = fmin(l, *lo);
    }
    *hi = h;
    *lo = l;
    l = fmax(l, h - TOP_DB);
    double den = fmax(h - l, 1e-8);
    for (int i = 0; i < NMEL; i++) {
        double v = fmin(fmax((db[i] - l) / den, 0.0), 1.0);
        q[i] = (uint8_t)fmin(fmax(rint(v * 127.0), 0.0), 127.0);
    }
}
