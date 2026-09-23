# ============================================================
# create_project.tcl — AX7A200B용 Vivado 프로젝트 생성 (재생성 가능)
# ============================================================
# 대상 : ALINX AX7A200B, XC7A200T-2FBG484I (Vivado 파트 xc7a200tfbg484-2)
# 도구 : Vivado 2026.1
#
# 실행 (저장소 루트에서):
#   vivado -mode batch -source hardware/vivado/create_project.tcl -tclargs [옵션]
#
# 옵션:
#   -name <이름>      프로젝트 이름 (기본: mmss)
#   -top  <모듈>      합성 탑 모듈. 생략하면 Vivado가 자동으로 고른다.
#   -xdc  <목록>      hardware/constraints/ax7a200b_<이름>.xdc 중 넣을 파일,
#                     쉼표로 구분 (기본: base,io). 예: -xdc base,io,pcie
#                     ddr3는 MIG가 자체 XDC를 만들므로 보통 넣지 않는다.
#   -src  <디렉터리>  hardware/src 외에 추가할 RTL 디렉터리 (여러 번 가능)
#   -proj_dir <경로>  프로젝트 위치 (기본: hardware/vivado/build/<이름>)
#   -run  <단계>      synth | impl | bit — 생성 후 해당 단계까지 실행
#   -jobs <N>         병렬 작업 수 (기본: 4)
#
# 소스 규칙:
#   hardware/src/**/*.{v,sv,vh,mem,hex} → sources_1 (재귀)
#   hardware/testbench/**/*.{v,sv}      → sim_1
#   프로젝트는 매번 -force로 다시 만든다. 설계 변경은 이 스크립트와
#   저장소 소스에 반영하고, 생성된 프로젝트 폴더는 산출물로 취급한다.
#
# 참고: 선행 저장소(Windows, SMB 경로)에서는 한글 경로에서 launch_runs 합성이
#   크래시했다. 이 서버(Linux, Vivado 2026.1)에서는 2026-09-22 한글 저장소 경로에서
#   프로젝트 모드 합성이 정상 완료됨을 확인했다. IP 생성에서 문제가 생기면
#   -proj_dir로 ASCII 경로를 지정한다.
# ============================================================

set script_dir [file normalize [file dirname [info script]]]
set repo_root  [file normalize "$script_dir/../.."]
set part       "xc7a200tfbg484-2"

# ---- 인자 처리 ----
set opt(name)     "mmss"
set opt(top)      ""
set opt(xdc)      "base,io"
set opt(src)      {}
set opt(proj_dir) ""
set opt(run)      ""
set opt(jobs)     4

set i 0
while { $i < [llength $argv] } {
    set key [lindex $argv $i]
    set val [lindex $argv [expr {$i + 1}]]
    switch -- $key {
        -name     { set opt(name) $val }
        -top      { set opt(top) $val }
        -xdc      { set opt(xdc) $val }
        -src      { lappend opt(src) [file normalize $val] }
        -proj_dir { set opt(proj_dir) [file normalize $val] }
        -run      { set opt(run) $val }
        -jobs     { set opt(jobs) $val }
        default   { error "알 수 없는 옵션: $key" }
    }
    incr i 2
}
if { $opt(proj_dir) eq "" } {
    set opt(proj_dir) "$repo_root/hardware/vivado/build/$opt(name)"
}
if { $opt(run) ni {"" synth impl bit} } {
    error "-run 값은 synth | impl | bit 중 하나여야 한다: $opt(run)"
}

puts "INFO: repo_root = $repo_root"
puts "INFO: proj_dir  = $opt(proj_dir)"

# ---- 재귀 파일 탐색 ----
proc find_files { dir patterns } {
    set out {}
    if { ![file isdirectory $dir] } { return $out }
    foreach p $patterns {
        foreach f [glob -nocomplain -types f -directory $dir $p] { lappend out $f }
    }
    foreach sub [glob -nocomplain -types d -directory $dir *] {
        set out [concat $out [find_files $sub $patterns]]
    }
    return [lsort -unique $out]
}

# ---- 프로젝트 생성 ----
create_project $opt(name) $opt(proj_dir) -part $part -force
set_property target_language Verilog [current_project]
set_property default_lib xil_defaultlib [current_project]

# ---- RTL 소스 ----
#   경로에 공백·한글이 있으므로 파일을 하나씩 [list]로 감싸 넘긴다.
set src_dirs [concat [list "$repo_root/hardware/src"] $opt(src)]
set n_src 0
foreach d $src_dirs {
    foreach f [find_files $d {*.v *.sv *.vh *.mem *.hex}] {
        add_files -norecurse -fileset sources_1 [list $f]
        incr n_src
    }
}
foreach f [get_files -quiet -of_objects [get_filesets sources_1] *.vh] {
    set_property file_type {Verilog Header} $f
}
puts "INFO: RTL 파일 $n_src 개 추가"

# ---- 제약 ----
foreach x [split $opt(xdc) ","] {
    set x [string trim $x]
    if { $x eq "" } { continue }
    set f "$repo_root/hardware/constraints/ax7a200b_$x.xdc"
    if { ![file exists $f] } { error "XDC 없음: $f" }
    add_files -norecurse -fileset constrs_1 [list $f]
    puts "INFO: XDC 추가 → ax7a200b_$x.xdc"
}

# ---- 시뮬레이션 소스 ----
#   프로젝트 내 xsim은 <proj>.sim/sim_1/behav/xsim에서 실행된다. $readmemh를
#   저장소 루트 기준 상대경로로 쓰는 testbench는 저장소 루트에서 xvlog/xelab/xsim을
#   직접 실행해 검증한다(AGENTS.md 규칙).
set n_tb 0
foreach f [find_files "$repo_root/hardware/testbench" {*.v *.sv}] {
    add_files -norecurse -fileset sim_1 [list $f]
    incr n_tb
}
puts "INFO: testbench 파일 $n_tb 개 추가"

# ---- 탑 모듈 ----
if { $opt(top) ne "" } {
    set_property top $opt(top) [get_filesets sources_1]
}
update_compile_order -fileset sources_1
if { $n_tb > 0 } { update_compile_order -fileset sim_1 }

puts "INFO: 프로젝트 생성 완료 → $opt(proj_dir)/$opt(name).xpr"

# ---- 선택: 합성/구현/비트스트림 실행 ----
if { $opt(run) ne "" } {
    launch_runs synth_1 -jobs $opt(jobs)
    wait_on_run synth_1
    if { [get_property PROGRESS [get_runs synth_1]] ne "100%" } {
        error "합성 실패 — $opt(proj_dir)/$opt(name).runs/synth_1/runme.log 확인"
    }
    puts "INFO: 합성 완료"

    if { $opt(run) in {impl bit} } {
        set to_step [expr { $opt(run) eq "bit" ? "write_bitstream" : "route_design" }]
        launch_runs impl_1 -to_step $to_step -jobs $opt(jobs)
        wait_on_run impl_1
        if { [get_property PROGRESS [get_runs impl_1]] ne "100%" } {
            error "구현 실패 — $opt(proj_dir)/$opt(name).runs/impl_1/runme.log 확인"
        }
        open_run impl_1
        set rpt "$opt(proj_dir)/reports"
        file mkdir $rpt
        report_utilization    -file "$rpt/utilization.rpt"
        report_timing_summary -file "$rpt/timing_summary.rpt" -max_paths 10
        report_drc            -file "$rpt/drc.rpt"
        set wns [get_property SLACK [get_timing_paths -setup -max_paths 1 -nworst 1]]
        puts "INFO: WNS = $wns ns (>= 0 이면 setup 타이밍 통과)"
        puts "INFO: 리포트 → $rpt"
        if { $opt(run) eq "bit" } {
            set bits [glob -nocomplain "$opt(proj_dir)/$opt(name).runs/impl_1/*.bit"]
            puts "INFO: 비트스트림 → $bits"
        }
    }
}
