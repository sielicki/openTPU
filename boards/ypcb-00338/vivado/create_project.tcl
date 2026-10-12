# Create the Vivado project for openTPU on the YPCB-00338: the LiteDRAM core
# (boards/ypcb-00338/litedram/), each channel behind otpu_mem_ch (bd_native.tcl, otpu_fpga_top_ld).
#   vivado -mode batch -source create_project.tcl -tclargs [DDR_SPEED] [OUT_DIR] [MCOLS] [CORE_MHZ] [BUILD_ID] [VPU_CL] [LANES] [ACT_ROWS] [DSTEP] [MXU] [PLATFORM] [ARCH_HASH]
# The defaults build MCOLS=4 and the systolic MXU.
# DDR_SPEED: 1066 only (the LiteDRAM core is generated for DDR3-1066: tools/litedram/gen_core.py).
# OUT_DIR: default ../../../build/vivado (repository build/).
# BUILD_ID: 8 hex digits for the BUILD_ID register (default: the first 8 hex digits of the
# repository's git commit, else 0).

set here [file normalize [file dirname [info script]]]
set root [file normalize $here/../../..]
set DDR_SPEED [expr {[llength $argv] > 0 ? [lindex $argv 0] : 1066}]
if {$DDR_SPEED != 1066} { error "DDR3-$DDR_SPEED: the LiteDRAM core is generated for DDR3-1066" }
set out [expr {[llength $argv] > 1 ? [file normalize [lindex $argv 1]] : "$root/build/vivado"}]
set MCOLS [expr {[llength $argv] > 2 ? [lindex $argv 2] : 4}]
set CORE_MHZ [expr {[llength $argv] > 3 ? [lindex $argv 3] : 133.33}]
set BUILD_ID ""
if {[llength $argv] > 4} { set BUILD_ID [lindex $argv 4] }
set VPU_CL [expr {[llength $argv] > 5 ? [lindex $argv 5] : 2}]
set LANES [expr {[llength $argv] > 6 ? [lindex $argv 6] : 8}]
set ACT_ROWS [expr {[llength $argv] > 7 ? [lindex $argv 7] : $MCOLS}]
# DSTEP 0: the DMA's DeltaNet head step left out (CAPS bit6 = 0; the compiler emits VOPs)
set DSTEP [expr {[llength $argv] > 8 ? [lindex $argv 8] : 1}]
# MXU: the MXU's dot product (docs/mxu_systolic.md): systolic (MXU_IMPL 2, the default) or tree (0)
set MXU [expr {[llength $argv] > 9 ? [lindex $argv 9] : "systolic"}]
set MXU_IMPL [expr {$MXU eq "tree" ? 0 : 2}]
# PLATFORM, ARCH_HASH: the CFG_PLATFORM / CFG_HASH registers (run_vivado.sh: the target file,
# targets/ypcb-00338.toml, through opentpu/target.py; ARCH_HASH 8 hex digits)
set PLATFORM [expr {[llength $argv] > 10 ? [lindex $argv 10] : 1}]
set ARCH_HASH [expr {[llength $argv] > 11 ? [lindex $argv 11] : 0}]
if {![regexp {^[0-9a-fA-F]{1,8}$} $ARCH_HASH]} { set ARCH_HASH 0 }
if {$BUILD_ID eq ""} {
  if {[catch {exec git -C $root rev-parse HEAD} BUILD_ID]} { set BUILD_ID 0 }
  set BUILD_ID [string range $BUILD_ID 0 7]
}
set build_id_invalid [expr {![regexp {^[0-9a-fA-F]{1,8}$} $BUILD_ID]}]
if {$build_id_invalid} { set BUILD_ID 0 }
# the core clock the block design makes (bd_native.tcl: CORE_MHZ rounded to the MMCM's 1/8
# divider steps of its 800 MHz VCO), for the CORE_KHZ register
set VCO 800
set CORE_KHZ [expr {round($VCO * 1000.0 / (round(double($VCO) / $CORE_MHZ * 8) / 8.0))}]
puts "CORE_KHZ $CORE_KHZ, BUILD_ID $BUILD_ID, MXU_IMPL $MXU_IMPL, PLATFORM $PLATFORM, ARCH_HASH $ARCH_HASH"

# Native bundles are elaborated for fixed parameters. Verify the actual files
# and every baked value before creating a project; Verilog initial assertions
# alone do not protect synthesis from a parameter mismatch.
set sparkle [expr {[info exists ::env(OTPU_SPARKLE_BUNDLE)] && $::env(OTPU_SPARKLE_BUNDLE) ne ""}]
if {$sparkle} {
  if {$build_id_invalid} { error "native FPGA: BUILD_ID must contain 1 to 8 hexadecimal digits" }
  if {$MXU ni {tree systolic}} { error "native FPGA: MXU must be tree or systolic" }
  if {$DSTEP ni {0 1}} { error "native FPGA: DSTEP must be 0 or 1" }
  set sparkle_bundle [file normalize $::env(OTPU_SPARKLE_BUNDLE)]
  set sparkle_pcie [expr {[info exists ::env(PCIE_GEN)] && $::env(PCIE_GEN) ne "" ? $::env(PCIE_GEN) : 2}]
  if {$sparkle_pcie ni {1 2}} { error "native FPGA: PCIE_GEN must be 1 or 2" }
  set ULANES [expr {[info exists ::env(ULANES)] ? $::env(ULANES) : 8}]
  scan $BUILD_ID %x sparkle_build_id
  set sparkle_parameters [list $MCOLS $ACT_ROWS $VPU_CL $MXU_IMPL $LANES $ULANES \
    $CORE_KHZ $sparkle_build_id $DDR_SPEED $DSTEP $sparkle_pcie]
  exec python3 $root/tools/prepare_sparkle_fpga_bundle.py verify \
    --bundle $sparkle_bundle --parameters {*}$sparkle_parameters
}

create_project -force otpu $out -part xc7k480tffg1156-2
if {$sparkle} {
  set_param general.maxThreads 1
  file copy -force $sparkle_bundle/manifest.json $out/sparkle-manifest.json
} elseif {[file exists $out/sparkle-manifest.json]} {
  file delete $out/sparkle-manifest.json
}
# The block design's IP synthesis (minutes: xdma above all) in a cache shared by every build on
# the host (OTPU_IP_CACHE, run_vivado.sh): each build is a fresh project, so the
# project's own cache never hit. Keyed on the IP's configuration, part and Vivado version.
if {[info exists ::env(OTPU_IP_CACHE)] && $::env(OTPU_IP_CACHE) ne ""} {
  file mkdir $::env(OTPU_IP_CACHE)
  config_ip_cache -use_cache_location $::env(OTPU_IP_CACHE)
}
set_property target_language Verilog [current_project]
set_property default_lib xil_defaultlib [current_project]

# ---- RTL (SystemVerilog): the accelerator (otpu_board, its DRAM adapter otpu_native_dram), the
# channels' native ports (one otpu_mem_ch per channel, XDMA's split: otpu_native_sys), the top and
# the generated LiteDRAM core (Verilog)
set rtl [list \
  rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/top/otpu_pkg.sv \
  rtl/mem/otpu_tmem.sv rtl/mem/otpu_actram.sv \
  rtl/seq/otpu_seq.sv rtl/vpu/otpu_vtree.sv rtl/dma/otpu_dma.sv \
  rtl/mxu/otpu_mxu.sv rtl/tech/xilinx7/otpu_tech_dsp.sv rtl/tech/generic/otpu_tech_ram.sv \
  rtl/vpu/otpu_quant.sv rtl/vpu/otpu_se_comp.sv rtl/vpu/otpu_se_tail.sv rtl/vpu/otpu_vpu.sv rtl/top/otpu_coll.sv \
  rtl/top/otpu_slice.sv \
  rtl/shell/otpu_ctrl.sv rtl/shell/otpu_trace.sv \
  rtl/shell/otpu_board.sv rtl/mem/otpu_native_dram.sv \
  rtl/shell/otpu_afifo.sv rtl/shell/otpu_mem_ch.sv \
  rtl/shell/otpu_axi_split2.sv rtl/boards/ypcb-00338/otpu_native_sys.sv \
  rtl/boards/ypcb-00338/otpu_fpga_top_ld.sv]
if {$sparkle} {
  set rtl [list rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv $sparkle_bundle/native.sv]
}
add_files -norecurse $root/boards/ypcb-00338/litedram/otpu_litedram.v
# the core's identifier ROM ("openTPU LiteDRAM"), which the Verilog $readmemh's by file name:
# synthesis finds it as a project file
add_files -norecurse $root/boards/ypcb-00338/litedram/otpu_litedram_mem.init
set_property FILE_TYPE {Memory Initialization Files} [get_files otpu_litedram_mem.init]
foreach f $rtl {
  set rtl_path [file join $root $f]
  add_files -norecurse $rtl_path
  set_property file_type SystemVerilog [get_files $rtl_path]
}
# SYNTHESIS removes the simulation-only checks and dumps
set_property verilog_define {SYNTHESIS} [get_filesets sources_1]

# ---- block design
source $here/bd_native.tcl   ;# sets PCIE_GEN (environment, run_vivado.sh) for the generics
if {$sparkle && $PCIE_GEN != $sparkle_pcie} { error "native FPGA: block design PCIe generation changed" }
make_wrapper -files [get_files otpu_bd.bd] -top
add_files -norecurse [glob $out/otpu.gen/sources_1/bd/otpu_bd/hdl/otpu_bd_wrapper.v]
set_property top otpu_fpga_top_ld [current_fileset]
set_property generic "MCOLS=$MCOLS ACT_ROWS=$ACT_ROWS VPU_CL=$VPU_CL LANES=$LANES CORE_KHZ=$CORE_KHZ BUILD_ID=32'h$BUILD_ID DDR_MTS=$DDR_SPEED DSTEP=1'b$DSTEP MXU_IMPL=$MXU_IMPL PCIE_GEN=$PCIE_GEN" [current_fileset]
if {$sparkle} {
  set_property generic "[get_property generic [current_fileset]] ULANES=$ULANES" [current_fileset]
} else {
  set_property generic "[get_property generic [current_fileset]] PLATFORM=$PLATFORM ARCH_HASH=32'h$ARCH_HASH" [current_fileset]
}

# ---- constraints: the board (otpu_top_ld.xdc) and the core's pads, VREF and synchronizers
# (otpu_litedram.xdc); then, after the IP's constraints, as unmanaged Tcl on the implemented
# netlist, each otpu_mem_ch's crossings (scoped to the module) and the top's (otpu_top_native.tcl)
set cons $root/boards/ypcb-00338/constraints
set board_xdc $cons/otpu_top_ld.xdc
set channel_tcl $cons/otpu_mem_ch.tcl
set top_tcl $cons/otpu_top_native.tcl
if {$sparkle} {
  set board_xdc $sparkle_bundle/board.xdc
  set channel_tcl $sparkle_bundle/mem_channel.tcl
  set top_tcl $sparkle_bundle/top.tcl
}
add_files -fileset constrs_1 -norecurse [list $board_xdc \
  $root/boards/ypcb-00338/litedram/otpu_litedram.xdc]
set late [list $channel_tcl $top_tcl]
add_files -fileset constrs_1 -norecurse $late
set_property SCOPED_TO_REF otpu_mem_ch [get_files $channel_tcl]
set_property PROCESSING_ORDER LATE [get_files $late]
set_property USED_IN_SYNTHESIS false [get_files $late]
foreach f $late {
  if {![string match -nocase *tcl* [get_property FILE_TYPE [get_files $f]]]} {
    error "$f: FILE_TYPE [get_property FILE_TYPE [get_files $f]], expected TCL (unmanaged)"
  }
}

# ---- strategies: timing-driven, the accelerator is the critical part. OTPU_FAST=1 (run_vivado.sh
# FAST=1): a development build at a relaxed clock (CORE_MHZ 100), with Vivado's default synthesis
# (no retiming) and implementation (build.tcl: no post-route phys_opt, no impl_directives.tcl)
if {[info exists ::env(OTPU_FAST)] && $::env(OTPU_FAST) eq "1"} {
  set_property strategy {Vivado Synthesis Defaults} [get_runs synth_1]
  set_property strategy {Vivado Implementation Defaults} [get_runs impl_1]
} else {
  set_property strategy Flow_PerfOptimized_high [get_runs synth_1]
  set_property STEPS.SYNTH_DESIGN.ARGS.RETIMING true [get_runs synth_1]
  set_property strategy Performance_ExplorePostRoutePhysOpt [get_runs impl_1]
}
# build.tcl writes its own reports from the opened runs: none inside the runs
set_property report_strategy {No Reports} [get_runs synth_1]
set_property report_strategy {No Reports} [get_runs impl_1]

puts "project created in $out (DDR3-$DDR_SPEED, LiteDRAM)"
