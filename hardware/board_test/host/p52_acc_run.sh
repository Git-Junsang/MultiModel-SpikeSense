#!/usr/bin/env bash
# p52_acc_run.sh — FPGA Host(sub1)에서 정확도·속도 시험: bitstream → mmss_host setup → run(실시간, 추론 요청 tcpdump) → stop (P5.2)
# 작업 폴더(저장소 root와 같은 상대 경로)에 software/host(빌드), hardware/data/models_l64, p325 묶음 지연 표,
#   data/eval.s16·map.txt(p52_acc.py prep)를 둔다. 결과는 run/. eno1 = 192.168.10.1/24, 보드 직결.
#   bash p52_acc_run.sh <작업 폴더> <bitstream> [program_fpga.tcl 폴더]
set -euo pipefail
J=$(realpath "$1"); BIT=$(realpath "$2"); PT=${3:-$HOME/mmss_jobs/p410_board}
cd "$J"; mkdir -p run
H=software/host/build/mmss_host
( cd "$PT" && source /tools/Xilinx/2026.1/Vivado/settings64.sh &&
  vivado -mode batch -nojournal -nolog -source program_fpga.tcl -tclargs -bit "$BIT" | grep -E "INFO: DONE|ERROR" )
sleep 6                                                  # PHY reset, auto-negotiation, MIG 보정
zcat hardware/board_test/p325_meas/result/m3_group_pin3_load0.csv.gz > run/group.csv   # setup은 gzip을 읽지 않는다
$H setup --map data/map.txt --models hardware/data/models_l64/models.ddr.bin --group-trace run/group.csv --jitter-us 800 \
    > run/setup.log 2>&1
sudo -n tcpdump -i eno1 -B 131072 -s 1600 -w run/req.pcap 'udp dst port 5000' 2> run/tcpdump.log & TP=$!
sleep 1
$H run --map data/map.txt --in data/eval.s16 --channels 1024 --pace --cpu 3 --log run/board > run/board_judge.csv 2> run/run.log
sleep 1
sudo -n kill -INT "$TP"; wait "$TP" || true
$H stop > run/stop.log 2>&1
tail -1 run/run.log; cat run/stop.log; grep -E "captured|dropped" run/tcpdump.log
