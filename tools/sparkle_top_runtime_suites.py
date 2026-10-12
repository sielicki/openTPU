"""Remaining original test_rtl regressions; exact static case inventory.

No tests are copied or downsized. Existing native-memory25/LDC3 and historical
nativeTop6 are partitioned explicitly. Standalone original-leaf/DDR-controller
checks remain external-reference categories, never counted as native Top proof.
"""

# Empty UL/VPU_CL overrides deliberately restore original geometry-dependent
# defaults for LANES4/8/16. OTPU_UARCH generic preserves WIN32/RPB4/WPB2; original
# tests that pass BOARD_UARCH continue to override those values explicitly.
BASE_ENVIRONMENT={
 'OTPU_MCOLS':'4','OTPU_LANES':'8','OTPU_ACT_ROWS':'4','OTPU_MXU':'systolic',
 'OTPU_MXU_CL':'16','OTPU_VPU_CL':'','OTPU_ULANES':'','OTPU_UARCH':'generic',
 'OTPU_NATIVE':'1','OTPU_PAIR':'0','OTPU_DSTEP':'0','OTPU_STREAM':'0',
 'OTPU_AXI':'0','OTPU_BOOT':'0','OTPU_LDC':'0','OTPU_LDC_MHZ':'0',
 'OTPU_STALL':'20','OTPU_SEED':'1','OTPU_BW':'100','OTPU_LAT':'20'}


def ids(name,suffixes):return [name+'['+suffix+']' for suffix in suffixes]

# mode, memory path, exact existing test names. Parametric defaults are literals,
# independent of the source AST/pytest enumeration used by guards.
GROUPS={
 'top-compiler-kernels':('top-test','behavioral',
   ids('test_mlp_rtl',('1','2','4'))+
   ids('test_attention_decode_rtl',('1-8-2-100','2-8-2-100','4-8-4-45'))+
   ids('test_attention_layer_rtl',('1','2'))+['test_design_size_block_128_rtl']),
 'top-fuzz-remaining':('top-test','behavioral',
   ids('test_fuzz_single_slice',('1','2','3','4','5','6','7'))+
   ids('test_fuzz_two_slices',('1','2','3'))),
 'top-scoreboard':('top-test','behavioral',
   ids('test_scoreboard_stress_single_slice',('0','1','2','3','4','5','6','7','8','9','10','11'))+
   ids('test_scoreboard_stress_two_slices',('0','1','2','3'))),
 'top-mxu-replay':('top-test','behavioral',
   ids('test_fuzz_mm_replay',('2-8-0','2-8-1','4-8-2','2-6-3','4-16-4'))),
 'top-fourbit-kernels':('top-test','behavioral',
   ids('test_mlp_4bit_rtl',('int4-2-32-False','fp4-2-32-False','fp4-1-128-False',
                          'int4-1-128-False','fp4-1-128-True','int4-1-128-True'))),
 'top-dma-behavioral':('top-test','behavioral',
   ids('test_dma_alignment_stress',('32-8-False-0','128-4-False-0','128-16-False-0'))),
 'top-dma-native':('top-test','native',
   ids('test_dma_alignment_stress',('128-8-True-0','128-8-True-50','128-8-True-85'))),
 'top-native-bursts':('top-test','native',
   ids('test_axi_read_bursts',('0','30','50'))+
   ids('test_axi_sw_write_gather',('0','40'))+
   ids('test_axi_write_bursts',('0-1','40-2','70-3','40-4','30-5'))),
 'top-native-scale-coherence':('top-test','native',
   ids('test_axi_scale_runs',('0-1','40-2','70-3'))+
   ids('test_axi_scale_runs_beside_dma_writes',('0-1','40-2','70-3'))),
 'top-native-host-coherence':('top-test','native',
   ids('test_porta_host_writes_between_runs',('False-reuse','False-run','True-reuse','True-run'))+
   ids('test_porta_host_writes_before_a_waitw',('reuse','run'))),
 'top-native-logit-fill':('top-test','native',ids('test_logits_fill_rtl',('0','60'))),
 'top-mask-behavioral':('top-test','behavioral',['test_additive_mask_block_rtl[False]']),
 'top-mask-native':('top-test','native',['test_additive_mask_block_rtl[True]']),
 'top-native-vt-throughput':('top-test','native',['test_axi_vt_append_throughput']),
 # These unchanged tests instantiate reference leaf benches directly and do not
 # use native Top. Keep separate, explicit external applicability records.
 'reference-tmem-bypass':('0','external-reference',['test_tmem_random_traffic']),
 'external-ldc-bist':('0','external-ldc',ids('test_ldc_sequential_is_the_card_bist',('read','write'))),
}

HISTORICAL_TOP6=(ids('test_fuzz_single_slice',('0',))+ids('test_fuzz_two_slices',('0',))+
 ids('test_lane_count_does_not_change_results',('4','16'))+
 ids('test_run_arguments_start_in_r8_to_r15',('False','True')))
CATALOGUED_LDC3=ids('test_ldc_memory_path',('hazard-0-1066-133.33','random-1-1066-100','dma-2-1066-200'))
EXCLUDED_INFRASTRUCTURE=['test_simulator_child_dies_with_its_parent']


def additions():
    suites={}
    for name,(mode,path,tests) in GROUPS.items():
        env=dict(BASE_ENVIRONMENT)
        if path=='native':env.update(OTPU_AXI='1',OTPU_BOOT='1')
        suites[name]={'mode':mode,'timeout':7200,'hardware_environment':env,
            'coverage_scope':path,'qualification_state':'pending_current_audited_runtime',
            'args':['tests/test_rtl.py::'+test for test in tests],
            'cases':[('tests.test_rtl',test) for test in tests]}
    suites['top-baseline-refresh']={'mode':'top-test','timeout':7200,
      'hardware_environment':dict(BASE_ENVIRONMENT),'coverage_scope':'behavioral',
      'qualification_state':'pending_current_audited_runtime',
      'args':['tests/test_rtl.py::'+test for test in HISTORICAL_TOP6],
      'cases':[('tests.test_rtl',test) for test in HISTORICAL_TOP6]}
    return suites

# Related original whole-Top integration programs. Pure ISA unit tests in these
# files are outside this RTL inventory, not silently counted as hardware runs.
RELATED_GROUPS={
 'top-vops-composites':('tests.test_vops','behavioral',
   ids('test_vops_rtl_bit_exact',('8-uarch0-0','8-uarch1-1','8-board4-2','16-uarch3-3','4-uarch4-4'))+
   ids('test_many_small_composites_rtl_bit_exact',('uarch0-0','board-1'))),
 'top-vops-direct':('tests.test_vops','behavioral',
   ids('test_direct_vops_rtl_bit_exact',('8-uarch0-0','8-board-1','8-board4-2','16-uarch3-3','4-uarch4-4'))),
 'top-dstep-programs':('tests.test_vops','behavioral',
   ids('test_dstep_rtl_bit_exact',('uarch0-0','board-1','board-2'))),
 'top-stream-descriptors':('tests.test_stream_rtl','behavioral',
   ids('test_stream_rtl_bit_exact',('uarch0-0','board-1','board-2'))),
 'top-stream-mixed-programs':('tests.test_stream','behavioral',
   ids('test_stream_rtl_bit_exact',('uarch0-0','board-1','board-2','board-3'))),
 'top-waitw-basic':('tests.test_waitw_rtl','behavioral',
   ['test_waitw_holds_at_once','test_waitw_waits_for_the_host','test_waitw_times_out']),
 'top-waitw-native-board-memory':('tests.test_waitw_rtl','native',
   ['test_waitw_after_a_store_on_the_board_memory_path','test_the_waitw_op_checks_on_the_board_config_rtl']+
   ids('test_the_card_check_waits_for_the_host',('0','1','2','3'))),
}


def related_additions():
    suites={}
    for name,(module,path,tests) in RELATED_GROUPS.items():
        env=dict(BASE_ENVIRONMENT)
        if path=='native':env.update(OTPU_AXI='1',OTPU_BOOT='1')
        suites[name]={'mode':'top-test','timeout':7200,'hardware_environment':env,
          'coverage_scope':path,'qualification_state':'pending_current_audited_runtime',
          'args':[module.replace('.','/')+'.py::'+test for test in tests],
          'cases':[(module,test) for test in tests]}
    return suites
