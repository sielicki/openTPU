# Architecture tournament (docs/tourney.md)
#   make tourney COMP=otpu_coll N=1 K=1 [AGENT=claude|codex] [EVAL=yosys|vivado-remote]
#                [MODEL_HYP=..] [MODEL_IMPL=..] [MODEL_SCRIBE=..]   (default claude-opus-5-5)
#                [EFFORT_HYP=high] [EFFORT_IMPL=high,xhigh] [EFFORT_SCRIBE=low] [ARGS=--keep]
#   make tourney-report [COMP=otpu_coll]
#   (any target: EXEC=remote (default) runs lint and the test gates on omarchy, EXEC=local here)
#   make tourney-fmax N=1 K=2 [TARGET_MHZ=133.33] [FMAX_COMPS="otpu_native_dram otpu_tmem ..."]
#        the whole-design fmax tournament: N passes over FMAX_COMPS, one round each, all on the
#        shared champion tourney/fmax, Vivado on the build host (EVAL=vivado-remote)
#   make tourney-fmax-baseline [TARGET_MHZ=133.33]   the champion's full build only
#   make tourney-units K=1 [UNIT_COMPS="otpu_tmem ..."]   the unit tournament, without end: each
#        unit alone out of context in Vivado, its own champion tourney/unit/<comp>, no full builds
PYTHON ?= python3
COMP   ?=
N      ?= 1
K      ?= 1
AGENT  ?= claude
EVAL   ?= yosys
BASE   ?= main
ARGS   ?=
# 133.33 MHz (800 / 6, an MMCM step): 128 B x f = 17.07 GB/s, both DDR3-1066 channels' peak
TARGET_MHZ ?= 133.33
# where lint and the test gates run: remote (omarchy, tools/omarchy_test.sh) or local
EXEC   ?= remote
export EXEC
# the units on the measured worst path families first (docs/tourney.md)
FMAX_COMPS ?= otpu_native_dram otpu_tmem otpu_mxu otpu_seq otpu_dma otpu_xunit otpu_vpu \
              otpu_quant otpu_coll otpu_actram otpu_fp
export MODEL_HYP MODEL_IMPL MODEL_SCRIBE EFFORT_HYP EFFORT_IMPL EFFORT_SCRIBE

# the unit tournament's components (the units with an out-of-context part) and build hosts
UNIT_COMPS ?= otpu_tmem otpu_quant otpu_seq otpu_actram otpu_coll otpu_vpu otpu_dma otpu_fp
UNIT_HOSTS ?= opentpu

.PHONY: tourney tourney-baseline tourney-report test-tourney tourney-fmax tourney-fmax-baseline \
        tourney-forever tourney-units

tourney:
	@test -n "$(COMP)" || (echo "COMP=<component> required; see tools/tourney/components/" && false)
	$(PYTHON) -m tools.tourney.orchestrator --comp $(COMP) --rounds $(N) --slots $(K) \
	  --agent $(AGENT) --eval $(EVAL) --base $(BASE) $(ARGS)

tourney-baseline:
	@test -n "$(COMP)" || (echo "COMP=<component> required" && false)
	$(PYTHON) -m tools.tourney.orchestrator --comp $(COMP) --eval $(EVAL) --base $(BASE) \
	  --baseline-only $(ARGS)

tourney-fmax:
	@for n in $$(seq 1 $(N)); do for c in $(FMAX_COMPS); do \
	  $(PYTHON) -m tools.tourney.orchestrator --objective fmax --target-mhz $(TARGET_MHZ) \
	    --comp $$c --rounds 1 --slots $(K) --agent $(AGENT) --eval vivado-remote --base $(BASE) \
	    $(ARGS) || exit $$?; done; done

# the fmax tournament without end: every component in turn, the whole-design component every
# WHOLE_EVERY rounds (tools/tourney/forever.sh; stop: touch /tmp/otpu-tourney-stop)
tourney-forever:
	K=$(K) TARGET_MHZ=$(TARGET_MHZ) bash tools/tourney/forever.sh

# the unit tournament beside it (docs/tourney.md, "The unit tournament"): forever.sh with
# OBJECTIVE=unit and its own control files, /tmp/otpu-tourney-units-{stop,pause,comps,hosts}
tourney-units:
	OBJECTIVE=unit WHOLE_EVERY=0 K=$(K) TARGET_MHZ=$(TARGET_MHZ) FOREVER_COMPS="$(UNIT_COMPS)" \
	  FOREVER_COMPS_FILE=/tmp/otpu-tourney-units-comps FOREVER_STOP=/tmp/otpu-tourney-units-stop \
	  FOREVER_PAUSE=/tmp/otpu-tourney-units-pause OTPU_HOSTS_FILE=/tmp/otpu-tourney-units-hosts \
	  OTPU_BUILD_HOSTS=$(UNIT_HOSTS) bash tools/tourney/forever.sh

tourney-fmax-baseline:
	$(PYTHON) -m tools.tourney.orchestrator --objective fmax --target-mhz $(TARGET_MHZ) \
	  --comp otpu_xunit --eval vivado-remote --base $(BASE) --baseline-only $(ARGS)

tourney-report:
	$(PYTHON) -m tools.tourney.report $(if $(COMP),--comp $(COMP),)

test-tourney:
	$(PYTHON) -m pytest -q tests/test_tourney.py

# Native Sparkle port. The sibling ../sparkle checkout supplies the Lean hardware library.
SPARKLE_S ?= 1
SPARKLE_LANES ?= 8
SPARKLE_D ?= 32
SPARKLE_MCOLS ?= 8
SPARKLE_ROWS ?= $(SPARKLE_MCOLS)
SPARKLE_BLOCKS ?= 64
SPARKLE_TMEM_WORDS ?= 65536
SPARKLE_WPB ?= 1
SPARKLE_IMEM_WORDS ?= 65536
SPARKLE_WIN ?= 32
SPARKLE_DMA_DEPTH ?= 128
SPARKLE_DMA_STREAMS ?= 1
.PHONY: sparkle sparkle-rtl test-sparkle prove-sparkle prove-sparkle-seq check-sparkle-physical test-sparkle-dma test-sparkle-integration test-sparkle-se-composite test-sparkle-se-tail test-sparkle-dram test-sparkle-native-dram
sparkle:
	lake build OpenTPU opentpu-gen opentpu-test

sparkle-rtl: sparkle
	mkdir -p build/sparkle
	.lake/build/bin/opentpu-gen collective $(SPARKLE_S) $(SPARKLE_LANES) build/sparkle/collective.sv
	.lake/build/bin/opentpu-gen fpipe build/sparkle/fpipe.sv
	.lake/build/bin/opentpu-gen actram $(SPARKLE_D) $(SPARKLE_MCOLS) $(SPARKLE_ROWS) $(SPARKLE_BLOCKS) $(SPARKLE_LANES) build/sparkle/actram.sv
	.lake/build/bin/opentpu-gen tmem $(SPARKLE_TMEM_WORDS) $(SPARKLE_LANES) 8 4 $(SPARKLE_WPB) 1 2 1 160 build/sparkle/tmem.sv
	.lake/build/bin/opentpu-gen vtree $(SPARKLE_LANES) 4 build/sparkle/vtree.sv
	.lake/build/bin/opentpu-gen seq $(SPARKLE_IMEM_WORDS) $(SPARKLE_D) $(SPARKLE_S) $(SPARKLE_WIN) build/sparkle/seq.sv
	.lake/build/bin/opentpu-gen float-convert build/sparkle/float-convert.sv
	.lake/build/bin/opentpu-gen se-microcode 3 build/sparkle/se-microcode.sv
	.lake/build/bin/opentpu-gen se-helpers build/sparkle/se-helpers.sv
	.lake/build/bin/opentpu-gen se-comp $(SPARKLE_LANES) 21 3 2 1 build/sparkle/se-composite.sv
	.lake/build/bin/opentpu-gen se-tail 8 7 1 build/sparkle/se-tail.sv
	.lake/build/bin/opentpu-gen dma $(SPARKLE_D) $(SPARKLE_LANES) $(SPARKLE_DMA_DEPTH) $(SPARKLE_DMA_STREAMS) build/sparkle/dma.sv
	.lake/build/bin/opentpu-gen quant $(SPARKLE_D) $(SPARKLE_LANES) build/sparkle/quant.sv
	.lake/build/bin/opentpu-gen qscale 2 4 2 build/sparkle/qscale.sv
	.lake/build/bin/opentpu-gen qread $(SPARKLE_LANES) build/sparkle/qread.sv
	.lake/build/bin/opentpu-gen qwrite $(SPARKLE_LANES) build/sparkle/qwrite.sv

test-sparkle:
	$(PYTHON) -m pytest -q tests/test_sparkle_generation.py tests/test_simtmp.py
	$(PYTHON) tools/test_sparkle.py
	$(PYTHON) tools/test_sparkle_qscale.py
	$(PYTHON) tools/test_sparkle_qread.py
	$(PYTHON) tools/test_sparkle_qwrite.py
	$(PYTHON) tools/test_sparkle_quant.py
	$(PYTHON) tools/check_sparkle_dram.py
	$(PYTHON) tools/check_sparkle_native_dram.py
	$(MAKE) test-sparkle-dma
	$(MAKE) test-sparkle-se-composite
	$(MAKE) test-sparkle-se-tail
	$(MAKE) test-sparkle-integration
	$(MAKE) test-sparkle-native-dram

test-sparkle-dma:
	OTPU_SPARKLE=dma $(PYTHON) -m pytest -q tests/test_rtl.py::test_dma_alignment_stress tests/test_waitw_rtl.py tests/test_stream_rtl.py tests/test_vops.py::test_dstep_rtl_bit_exact

test-sparkle-se-composite:
	OTPU_SPARKLE=secomp $(PYTHON) -m pytest -q tests/test_se_comp.py tests/test_se_vpu.py

test-sparkle-se-tail:
	OTPU_SPARKLE=setail $(PYTHON) -m pytest -q tests/test_se_vpu.py tests/test_stream_rtl.py

.PHONY: test-sparkle-vpu
test-sparkle-vpu:
	OTPU_SPARKLE=vpu-test $(PYTHON) -m pytest -q tests/test_se_vpu.py tests/test_rtl.py::test_lane_count_does_not_change_results 'tests/test_rtl.py::test_fuzz_single_slice[0]' 'tests/test_rtl.py::test_fuzz_two_slices[0]'

.PHONY: test-sparkle-dma-split
test-sparkle-dma-split:
	$(PYTHON) tools/check_sparkle_dma_split.py

.PHONY: test-sparkle-async-fifo
test-sparkle-async-fifo:
	$(PYTHON) tools/check_sparkle_async_fifo.py

.PHONY: test-sparkle-mem-channel
test-sparkle-mem-channel:
	$(PYTHON) -m pytest -q tests/test_sparkle_mem_channel.py

.PHONY: test-sparkle-board-assembly test-sparkle-board-native
test-sparkle-board-assembly:
	OTPU_SPARKLE=board-assembly-test $(PYTHON) -m pytest -q tests/test_observability.py

test-sparkle-board-native:
	OTPU_SPARKLE=board-native-test $(PYTHON) -m pytest -q tests/test_observability.py tests/test_sparkle_mem_channel.py -k 'not mem-channel-test'

.PHONY: test-sparkle-top
test-sparkle-top:
	$(PYTHON) -m pytest -q tests/test_sparkle_top_sources.py
	OTPU_SPARKLE=top-test $(PYTHON) -m pytest -q 'tests/test_rtl.py::test_fuzz_single_slice[0]' 'tests/test_rtl.py::test_fuzz_two_slices[0]' tests/test_rtl.py::test_lane_count_does_not_change_results tests/test_rtl.py::test_run_arguments_start_in_r8_to_r15
	OTPU_SPARKLE=top-test $(PYTHON) -m pytest -q tests/test_rtl.py::test_ldc_memory_path

.PHONY: check-sparkle-board-native check-sparkle-native-sys-complete
check-sparkle-board-native:
	$(PYTHON) tools/check_sparkle_board_native_abi.py

check-sparkle-native-sys-complete:
	$(PYTHON) tools/check_sparkle_native_sys_complete.py

.PHONY: check-sparkle-fpga-top-complete check-sparkle-fpga-cli
check-sparkle-fpga-top-complete:
	$(PYTHON) tools/check_sparkle_fpga_top_complete.py

check-sparkle-fpga-cli:
	$(PYTHON) tools/check_sparkle_fpga_cli.py

.PHONY: test-sparkle-vivado-project check-sparkle-board-constraints
test-sparkle-vivado-project:
	$(PYTHON) -m pytest -q tools/test_sparkle_board_constraints.py tools/test_sparkle_vivado_project.py

check-sparkle-board-constraints:
	$(PYTHON) tools/generate_sparkle_board_constraints.py

.PHONY: check-sparkle-slice-physical
check-sparkle-slice-physical:
	lake build OpenTPU.SlicePhysicalABI
	$(PYTHON) tools/check_sparkle_slice_physical_abi.py

.PHONY: test-sparkle-board-channel check-sparkle-mxu-selective
test-sparkle-board-channel:
	OTPU_SPARKLE=board-channel-test $(PYTHON) -m pytest -q tests/test_observability.py

check-sparkle-mxu-selective:
	$(PYTHON) tools/synth_sparkle_mxu_selective.py --matrix --keep-fp-hierarchy

test-sparkle-native-dram:
	OTPU_SPARKLE=all $(PYTHON) -m pytest -q tests/test_rtl.py::test_native_memory_path tests/test_waitw_rtl.py::test_waitw_after_a_store_on_the_board_memory_path

test-sparkle-dram:
	OTPU_SPARKLE=dram $(PYTHON) -m pytest -q tests/test_rtl.py::test_fuzz_single_slice tests/test_rtl.py::test_fuzz_two_slices tests/test_waitw_rtl.py

test-sparkle-integration:
	OTPU_SPARKLE=all $(PYTHON) -m pytest -q tests/test_rtl.py::test_fuzz_single_slice tests/test_rtl.py::test_fuzz_two_slices tests/test_rtl.py::test_design_size_block_128_rtl tests/test_stream_rtl.py tests/test_waitw_rtl.py::test_waitw_holds_at_once tests/test_waitw_rtl.py::test_waitw_waits_for_the_host tests/test_se_vpu.py

prove-sparkle:
	$(PYTHON) tools/prove_sparkle_slice.py --matrix
	$(PYTHON) tools/prove_sparkle_top_composition.py
	$(PYTHON) tools/prove_sparkle_slice_ports.py
	$(PYTHON) tools/prove_sparkle_slice_perf.py
	$(PYTHON) tools/check_sparkle_slice_perf_abi.py
	$(PYTHON) tools/prove_sparkle_board_composition.py
	$(PYTHON) tools/prove_sparkle_native_sys.py
	$(PYTHON) tools/prove_sparkle_slice_loader.py
	$(PYTHON) tools/prove_sparkle_slice_rld.py
	$(PYTHON) tools/prove_sparkle_slice_arbiter.py
	$(PYTHON) tools/prove_sparkle_board_signals.py
	$(PYTHON) tools/prove_sparkle_control.py
	$(PYTHON) tools/prove_sparkle_trace.py
	$(PYTHON) tools/prove_sparkle_async_fifo.py
	$(PYTHON) tools/prove_sparkle_dma_split.py
	$(PYTHON) tools/prove_sparkle_axi_split.py
	$(PYTHON) tools/prove_sparkle_dram.py
	$(PYTHON) tools/prove_sparkle_dram.py --config 4 8 1 --mutation
	$(PYTHON) tools/prove_sparkle_native_dram.py
	$(PYTHON) tools/prove_sparkle_native_dram.py --config 128 2 2 0 0 2 2 1 --mutation
	$(PYTHON) tools/prove_sparkle.py --self-test
	$(PYTHON) tools/check_actram_index_frontends.py
	$(PYTHON) tools/prove_sparkle_actram.py --self-test
	$(PYTHON) tools/prove_sparkle_actram_ports.py --self-test
	$(PYTHON) tools/prove_sparkle_actram_ports.py --config 128 2 2 128 8
	$(PYTHON) tools/prove_sparkle_float_convert.py --self-test
	$(PYTHON) tools/prove_sparkle_qscale.py --self-test
	$(PYTHON) tools/prove_sparkle_qread.py --self-test
	$(PYTHON) tools/prove_sparkle_qwrite.py --self-test
	$(PYTHON) tools/prove_sparkle_quant.py --self-test
	$(PYTHON) tools/qualify_sparkle_quant_board.py
	$(PYTHON) tools/prove_sparkle_dma_setup.py --self-test
	$(PYTHON) tools/prove_sparkle_dma.py --self-test
	$(PYTHON) tools/prove_sparkle_se_microcode.py --self-test
	$(PYTHON) tools/prove_sparkle_se_helpers.py --self-test
	$(PYTHON) tools/prove_sparkle_se_composite.py --self-test
	$(PYTHON) tools/prove_sparkle_se_composite.py --internal --self-test
	$(PYTHON) tools/prove_sparkle_se_tail.py --self-test
	$(PYTHON) tools/check_sparkle_se_tail.py
	$(PYTHON) tools/prove_sparkle_tmem.py --self-test
	$(PYTHON) tools/prove_sparkle_tmem_ports.py --self-test
	$(PYTHON) tools/prove_sparkle_vtree.py --self-test
	$(PYTHON) tools/prove_sparkle_vpu_decode.py
	$(PYTHON) tools/prove_sparkle_vpu_issue.py
	$(PYTHON) tools/prove_sparkle_vpu_command.py
	$(PYTHON) tools/prove_sparkle_vpu_sequence.py
	$(PYTHON) tools/prove_sparkle_vpu_write_buffer.py
	$(PYTHON) tools/prove_sparkle_vpu_write_select.py
	$(PYTHON) tools/prove_sparkle_vpu_stream.py
	$(PYTHON) tools/check_sparkle_vpu_control.py
	$(PYTHON) tools/prove_sparkle_board_fifo.py
	$(PYTHON) tools/prove_sparkle_axi_slice.py
	$(MAKE) prove-sparkle-seq
	$(PYTHON) tools/check_sparkle_physical.py

prove-sparkle-seq:
	$(PYTHON) tools/prove_sparkle_seq_logic.py --self-test
	$(PYTHON) tools/prove_sparkle_seq_schedule.py --self-test
	$(PYTHON) tools/prove_sparkle_seq_dispatch.py --self-test
	$(PYTHON) tools/prove_sparkle_seq_window.py --self-test
	$(PYTHON) tools/prove_sparkle_seq.py --self-test
	$(PYTHON) tools/prove_sparkle_seq_depth.py

check-sparkle-physical:
	$(PYTHON) tools/check_sparkle_trace_physical.py
	$(PYTHON) tools/check_sparkle_physical.py
	$(PYTHON) tools/check_sparkle_board_split_physical.py
	$(PYTHON) tools/check_sparkle_async_fifo_physical.py

.PHONY: test-sparkle-trace
test-sparkle-trace:
	$(PYTHON) tools/check_sparkle_trace.py

.PHONY: test-sparkle-mxu
test-sparkle-mxu:
	OTPU_SPARKLE=mxu-test $(PYTHON) -m pytest -q tests/test_rtl.py::test_lane_count_does_not_change_results 'tests/test_rtl.py::test_fuzz_single_slice[0]' 'tests/test_rtl.py::test_fuzz_two_slices[0]'

.PHONY: test-sparkle-board-support test-sparkle-control
test-sparkle-board-support:
	OTPU_SPARKLE=board-test $(PYTHON) -m pytest -q tests/test_observability.py

test-sparkle-control:
	$(PYTHON) tools/check_sparkle_control.py
