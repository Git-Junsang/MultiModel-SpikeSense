# verilog-ethernet 가져온 버전

- 원본: <https://github.com/alexforencich/verilog-ethernet> (MIT, 더 관리되지 않는 저장소)
- commit: `77320a9471d19c7dd383914bc049e02d9f4f1ffb` (2025-02-27, "Add deprecation notice")
- 가져온 날: 2026-10-24
- 파일은 고치지 않았다. 원본과 같은 상대 경로에 둔다. 라이선스는 `COPYING`, `lib/axis/COPYING`이다.

## 쓰는 곳

`hardware/src/eth_link.v`가 `eth_mac_1g_rgmii_fifo`와 `udp_complete`, `eth_axis_rx`, `eth_axis_tx`, `sync_reset`을 쓴다. 나머지는 이 module들이 부른다. `tb_eth.sv`의 Host 쪽 network stack도 같은 파일로 만든다.

`udp_complete`의 UDP checksum 생성기(`udp_checksum_gen.v`)는 eth_link에서 끈다. header FIFO가 찬 때 들어온 header를 버려 payload와 짝이 어긋나는 결함이 있다. Host 쪽 testbench stack만 이 생성기를 쓴다.

## 파일

| 경로 | 파일 |
|---|---|
| `rtl/` | `arp.v`, `arp_cache.v`, `arp_eth_rx.v`, `arp_eth_tx.v`, `axis_gmii_rx.v`, `axis_gmii_tx.v`, `eth_arb_mux.v`, `eth_axis_rx.v`, `eth_axis_tx.v`, `eth_mac_1g.v`, `eth_mac_1g_rgmii.v`, `eth_mac_1g_rgmii_fifo.v`, `iddr.v`, `ip.v`, `ip_arb_mux.v`, `ip_complete.v`, `ip_eth_rx.v`, `ip_eth_tx.v`, `lfsr.v`, `oddr.v`, `rgmii_phy_if.v`, `ssio_ddr_in.v`, `ssio_ddr_out.v`, `udp.v`, `udp_checksum_gen.v`, `udp_complete.v`, `udp_ip_rx.v`, `udp_ip_tx.v` |
| `lib/axis/rtl/` | `arbiter.v`, `axis_async_fifo.v`, `axis_async_fifo_adapter.v`, `axis_fifo.v`, `priority_encoder.v`, `sync_reset.v` |
| `syn/vivado/` | `eth_mac_1g_rgmii.tcl`, `eth_mac_fifo.tcl`, `rgmii_phy_if.tcl` |
| `lib/axis/syn/vivado/` | `axis_async_fifo.tcl`, `sync_reset.tcl` |
| 최상위 | `AUTHORS`, `COPYING`, `lib/axis/COPYING` |

`syn/vivado/*.tcl`은 clock 경계와 RGMII 제약을 거는 Vivado script다. board top을 만들 때(P4.10) 원본 예제(`example/NexysVideo/fpga/fpga/Makefile`)처럼 XDC 목록에 넣는다.
