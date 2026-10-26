/* mel.c — 특징 추출: frame 하나 → mel 40개 → 0–127 (02 §3·§4, 06 §2)
 *
 * 학습 특징(software/dataset/dcase_data.py, librosa melspectrogram power 2)을 frame 하나에 쓴 것이다.
 * p325_mel_load.py의 mel_db·TrackNorm·quantize_input과 같은 식이다.
 *   periodic Hann 1,024 → FFT → |X|² → Slaney mel 40 → 10·log10(max(S, 1e-10))
 *   정규화(02 §5, P2.9): mel dB를 트랙의 하한 아래로 자른다. 트랙마다 기준(최대·최소 dB)을 이어 간다. Frame의 최대·최소가
 *   기준을 넘으면 바로 받고, 아니면 기준을 그 값 쪽으로 frame마다 1 − e^(−32 ms / τ)만큼 돌린다(τ = NORM_TAU_S).
 *   Frame 최대가 하한 + GATE_DB 이하인 무음 frame은 기준을 그대로 둔다. Frame 최대가 기준 최대 − QUIET_DB보다 작은 조용한
 *   Frame(소리와 0이 섞인 경계 frame 등)은 최소를 그대로 두고 최대만 잊는다. 최소는 최대 − 80 dB 아래로 내려가지 않는다
 *   x_q = clip(rint(x × 127), 0, 127)
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
static double keep;                           /* 정규화 기준이 frame 하나 뒤에 남기는 몫 e^(−32 ms / τ) */

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
    keep = exp(-(double)HOP / SR / NORM_TAU_S);
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

/* has: 이 트랙에 기준이 있는지. 처음 소리가 난 frame에서 기준을 시작한다. 그 전 무음 frame은 x = 0 */
void norm_q(const float *db, double floor_db, double *hi, double *lo, uint8_t *has, uint8_t *q)
{
    double d[NMEL], m, n;
    for (int i = 0; i < NMEL; i++)
        d[i] = fmax(db[i], floor_db);
    m = n = d[0];
    for (int i = 1; i < NMEL; i++) {
        m = fmax(m, d[i]);
        n = fmin(n, d[i]);
    }
    if (m > floor_db + GATE_DB) {
        if (!*has) {
            *hi = m;
            *lo = n;
            *has = 1;
        } else {
            int quiet = m < *hi - QUIET_DB;
            *hi = fmax(m, keep * *hi + (1.0 - keep) * m);
            if (!quiet)
                *lo = fmin(n, keep * *lo + (1.0 - keep) * n);
        }
    }
    double h = *has ? *hi : m, l = fmax(*has ? *lo : n, h - TOP_DB);
    double den = fmax(h - l, 1e-8);
    for (int i = 0; i < NMEL; i++) {
        double v = fmin(fmax((d[i] - l) / den, 0.0), 1.0);
        q[i] = (uint8_t)fmin(fmax(rint(v * 127.0), 0.0), 127.0);
    }
}
