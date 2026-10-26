/* main.c — mmss_host: 라즈베리파이 5 Host program (06_HOST_INTERFACE.md)
 *
 *   mmss_host setup [--fpga IP] [--tracks N | --map FILE] [--models models.ddr3.bin] [--model-group-delay-trace CSV] [--jitter-us J]
 *                   [--margin-us M]
 *   mmss_host run   [--fpga IP] [--tracks N | --map FILE] [--in FILE|-] [--channels C] [--pace] [--loop] [--block B]
 *                   [--seconds S] [--log PREFIX] [--manifest FILE] [--cpu N] [--floor-db F]
 *   mmss_host stop  [--fpga IP]
 *
 * setup: 06 §6 1–6(설계 확인, 모델 image 적재·확인, 설정, PNU 표, SOFT_RESET, RUN = 1)
 * run:   stdout에 판정(track_id, cycle, model_id, decision, score), stderr 끝에 summary 한 줄.
 *        --log면 <PREFIX>_result.csv(결과마다)와 <PREFIX>_model_group.csv(모델 그룹마다, 모델 그룹 지연 표 형식)를 쓴다
 * stop:  IDLE = 1을 기다려 RUN = 0, counter와 첫 오류 출력
 * map 파일: 한 줄 = 트랙 하나, `model_id [dB 하한]`. 하한이 없으면 --floor-db(기본 −80 dB). Mic는 바닥 잡음 위로 정한다
 * 상대 경로는 저장소 root 기준이다(--manifest 기본값 hardware/data/models_l64/manifest.json). */
#include <stdio.h>
#include <string.h>
#include "host.h"

int main(int argc, char **argv)
{
    if (argc >= 2 && !strcmp(argv[1], "setup"))
        return cmd_setup(argc - 1, argv + 1);
    if (argc >= 2 && !strcmp(argv[1], "run"))
        return cmd_run(argc - 1, argv + 1);
    if (argc >= 2 && !strcmp(argv[1], "stop"))
        return cmd_stop(argc - 1, argv + 1);
    fprintf(stderr, "사용: %s setup|run|stop [옵션]  (main.c 첫머리 참고)\n", argv[0]);
    return 2;
}
