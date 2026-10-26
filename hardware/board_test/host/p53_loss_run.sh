#!/usr/bin/env bash
# p53_loss_run.sh — 결과 손실 조사(P5.3 결과 손실 보고서): P5.3 입력을 돌리며 eno1의 모든 frame(앞 96 B)을 잡고,
#   Host NIC·IP counter, FPGA 진단 counter(0x0440~), 보드 PHY·Host PHY register를 전후로 남긴다 (FPGA Host = sub1)
#   bash p53_loss_run.sh <작업 폴더> <결과 이름>
# 작업 폴더: p52_acc_run.sh와 같은 꼴(software/host 빌드, 모델 image, data/eval.s16·map.txt) + 이 폴더의 p53_hostphy.py.
# PT(기본 ~/mmss_jobs/p410_board)에는 program_fpga.tcl, p52_sys.py, p53_mdio.py.
# 환경 변수
#   BIT   bitstream(진단 counter·MDIO가 든 것)      TX    송신 위상 단계(수신 tap 8과 함께 LINK_TUNE에 쓴다)
#   MS    보드 PHY master/slave: master 또는 auto   MAP   트랙 → 모델 표(기본 data/map.txt)
#   BG=1  Host가 쓰지 않는 UDP port로 작은 packet을 계속 보낸다     BUSY=1  CPU 한 core를 계속 바쁘게 한다
set -euo pipefail
J=$(realpath "$1"); O=$J/$2; PT=${PT:-$HOME/mmss_jobs/p410_board}; MAP=${MAP:-data/map.txt}
cd "$J"; mkdir -p "$O"
H=software/host/build/mmss_host
( cd "$PT" && source /tools/Xilinx/2026.1/Vivado/settings64.sh &&
  vivado -mode batch -nojournal -nolog -source program_fpga.tcl -tclargs -bit "$BIT" | grep -E "INFO: DONE|ERROR" )
sleep 6
if [ -n "${TX:-}" ]; then
  ( cd "$PT" && python3 -c "
import p52_sys as p
c = p.Ctl(0.05); v = (($TX & 0xFFFF) << 16) | 8
for _ in range(60):
    try:
        c(2, 0x0318, 1, [v], name='lt')
        if c(1, 0x0318, 1, name='lt') == [v]: print('LINK_TUNE', hex(v)); break
    except SystemExit: pass
else: raise SystemExit('LINK_TUNE 실패')" ) > "$O/link_tune.log" 2>&1
fi
[ -n "${MS:-}" ] && ( cd "$PT" && python3 p53_mdio.py "$MS" ) > "$O/mdio.log" 2>&1
( cd "$PT" && python3 p53_mdio.py dump ) > "$O/phy_before.log" 2>&1
sudo -n python3 "$J/p53_hostphy.py" eno1 > "$O/host_phy_before.log" 2>&1
zcat hardware/board_test/p325_meas/result/m3_group_pin3_load0.csv.gz > "$O/model_group_delay.csv"
$H setup --map "$MAP" --models hardware/data/models_l64/models.ddr3.bin --model-group-delay-trace "$O/model_group_delay.csv" --jitter-us 800 > "$O/setup.log" 2>&1
snap() { ethtool -S eno1 > "$O/nic_$1.txt"; cat /proc/net/snmp /proc/net/netstat > "$O/snmp_$1.txt"; }
snap before
sudo -n tcpdump -i eno1 -B 262144 -s 96 -w "$O/all.pcap" "not udp port 9999" 2> "$O/tcpdump.log" & TP=$!
sleep 1
if [ "${BG:-0}" = 1 ]; then
  ( timeout 175 taskset -c 9 python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(('192.168.10.1', 0))
while True: s.sendto(bytes(18), ('192.168.10.2', 9999))" & ) 2>/dev/null
fi
[ "${BUSY:-0}" = 1 ] && ( timeout 175 taskset -c 9 python3 -c "while True: pass" & )
$H run --map "$MAP" --in data/eval.s16 --channels 1024 --pace --cpu 3 --log "$O/board" > "$O/board_judge.csv" 2> "$O/run.log"
sleep 1
sudo -n kill -INT "$TP"; wait "$TP" || true
snap after
( cd "$PT" && python3 -c "
import p52_sys as p
n = ['rs', 'udp_hdr', 'tx_good', 'tx_bad', 'tx_ovf', 'tx_unf', 'ip_early', 'arp_fail', 'udp_early', 'speed_chg', 'rx_fcs', 'rx_ovf']
print(' '.join(f'{a}={b}' for a, b in zip(n, p.Ctl(0.2).rd(0x0440, 12, 'link'))))" ) > "$O/link.log"
$H stop > "$O/stop.log" 2>&1
( cd "$PT" && python3 p53_mdio.py dump ) > "$O/phy_after.log" 2>&1
sudo -n python3 "$J/p53_hostphy.py" eno1 > "$O/host_phy_after.log" 2>&1
cat "$O/link.log"; tail -1 "$O/run.log"; grep -E "REQ_IN|RES_OUT|REQ_DROP" "$O/stop.log"; grep -E "captured|dropped" "$O/tcpdump.log"
