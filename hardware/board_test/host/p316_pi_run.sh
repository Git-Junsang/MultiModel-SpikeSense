#!/usr/bin/env bash
# p316_pi_run.sh — 라즈베리파이 5 Host 측정(P3.16 측정 1·2). 보드는 eth0 직결(Pi 192.168.10.1, FPGA 192.168.10.2).
# 작업 폴더(저장소 root와 같은 상대 경로)에 software/host/build/mmss_host, hardware/data/models_l64,
#   run/xeon_model_group_delay.csv(PNU 표용, P3.25 m3_group_pin3_load0), 입력 wav를 두고 그 폴더에서 실행한다.
# 조건마다 setup → (부하 시작) → run --pace --loop 1,024트랙 → stop. 결과 CSV는 tmpfs(/tmp)에 쓰고 끝난 뒤 run/으로 gzip해 옮긴다.
#   bash p316_pi_run.sh                     6조건 × 300 s + tcpdump 1조건 × 120 s
#   CONDS="pin3_perf_load0" SEC=10 bash p316_pi_run.sh      일부만
set -u
cd "$(dirname "$(realpath "$0")")"
H=software/host/build/mmss_host
W=software/dataset/dcase/fan/train/normal_id_01_00000000.wav
E=/usr/sbin/ethtool
T=/tmp/p316
SEC=${SEC:-300}
CAP_SEC=${CAP_SEC:-120}
LOAD_N=3                                   # busy loop 수 = core 4개 − 계산 thread 1개
CONDS=${CONDS:-"pin-none_ondemand_load0 pin3_ondemand_load0 pin3_performance_load0 pin-none_ondemand_load3 pin3_ondemand_load3 pin3_performance_load3 cap_pin3_performance_load0"}
mkdir -p run "$T"

gov() { echo "$1" | sudo tee /sys/devices/system/cpu/cpufreq/policy0/scaling_governor > /dev/null; }
snap() {
    date -Is; uname -a; cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor
    vcgencmd measure_temp; vcgencmd get_throttled; vcgencmd measure_clock arm; cat /proc/loadavg
    cat /proc/sys/net/core/rmem_max; grep -E '^Udp:' /proc/net/snmp
    ip -s -s link show eth0; sudo "$E" eth0 | grep -E 'Speed|Duplex'; sudo "$E" --show-eee eth0 | grep 'EEE status'
    sudo "$E" -c eth0 | grep -E '^(rx|tx)-usecs:'; sudo "$E" -S eth0
}

one() {                                    # $1 = [cap_|rt_]pin<CPU|-none>_<governor>_load<N>. rt_ = 모든 thread SCHED_FIFO 50
    local n=$1 c=${1#cap_} cap=0 s=$SEC pin g L pids=() rt=()
    [ "$c" != "$n" ] && { cap=1; s=$CAP_SEC; }
    [ "${c#rt_}" != "$c" ] && { c=${c#rt_}; rt=(sudo chrt -f 50); }
    IFS=_ read -r pin g L <<< "$c"; pin=${pin#pin}; L=${L#load}
    echo "== $n ($(date +%T)) pin=$pin governor=$g load=$L ${s}s"
    gov "$g"; sleep 2
    $H stop > /dev/null 2>&1                # setup은 RUN = 0을 요구한다
    $H setup --tracks 1024 --models hardware/data/models_l64/models.ddr3.bin \
        --model-group-delay-trace run/xeon_model_group_delay.csv --jitter-us 800 > "run/$n.setup.log" 2>&1 \
        || { echo "setup 실패"; cat "run/$n.setup.log"; return 1; }
    for ((i = 0; i < L; i++)); do      # CPU를 고정하면 그 CPU는 피한다
        if [ "$pin" = -none ]; then sh -c 'while :; do :; done' & else taskset -c "$(seq -s, 0 3 | sed "s/\b$pin\b,\?//;s/,$//")" sh -c 'while :; do :; done' & fi
        pids+=($!)
    done
    snap > "run/$n.before.txt" 2>&1
    local TP=
    if [ $cap = 1 ]; then
        sudo taskset -c 0-2 tcpdump -i eth0 -j host --time-stamp-precision=nano -B 65536 -s 96 -w "$T/$n.pcap" \
            'udp port 5000 or udp port 5001' 2> "run/$n.tcpdump.log" & TP=$!
        sleep 2
    fi
    local cpu=(); [ "$pin" != -none ] && cpu=(--cpu "$pin")
    "${rt[@]}" $H run --tracks 1024 --in "$W" --pace --loop --seconds "$s" "${cpu[@]}" --log "$T/$n" > "$T/$n.judge.csv" 2> "run/$n.run.log"
    [ -n "$TP" ] && { sleep 1; sudo kill -INT "$TP"; wait "$TP"; }
    snap > "run/$n.after.txt" 2>&1
    for p in "${pids[@]}"; do kill "$p"; done; wait "${pids[@]}" 2> /dev/null
    $H stop > "run/$n.stop.log" 2>&1
    tail -1 "run/$n.run.log"; tail -3 "run/$n.stop.log"
    for f in "$T/$n"*; do gzip -1 -c "$f" > "run/$(basename "$f").gz" && rm "$f"; done   # 다음 조건 전에 tmpfs를 비운다
}

for n in $CONDS; do one "$n"; done
gov ondemand
echo "== 끝 $(date +%T)"
