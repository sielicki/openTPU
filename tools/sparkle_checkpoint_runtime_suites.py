"""Original real-checkpoint RTL workloads for the runtime qualifier.

All eighteen use RtlBackend -> native Top, including tests whose names say
'board'. None uses BoardBackend/SimTransport. No downloads, tokenizer inputs,
workload reductions, or checkpoint discovery happen in this inventory.
"""
from sparkle_top_runtime_suites import BASE_ENVIRONMENT

# name, module, original exact pytest suffix, canonical checkpoint, memory path.
CASES = (
 ('qwen3-int8','test_qwen3','int8-None-False','Qwen3-0.6B','behavioral'),
 ('qwen3-fp4-int8','test_qwen3','fp4-int8-False','Qwen3-0.6B','behavioral'),
 ('qwen3-fp4-pair','test_qwen3','fp4-None-True','Qwen3-0.6B','behavioral'),
 ('lfm2-int8','test_lfm2','int8-None-False-False','LFM2.5-230M','behavioral'),
 ('lfm2-fp4-int8','test_lfm2','fp4-int8-True-False','LFM2.5-230M','behavioral'),
 ('lfm2-fp4-int8-resident','test_lfm2','fp4-int8-True-True','LFM2.5-230M','behavioral'),
 ('qwen35-vop','test_qwen35','False','Qwen3.5-0.8B','behavioral'),
 ('qwen35-dstep','test_qwen35','True','Qwen3.5-0.8B','behavioral'),
)
FUNCTIONS = {
 'test_qwen3':'test_qwen3_0_6b_token_on_rtl_is_bit_exact',
 'test_lfm2':'test_lfm2_5_230m_token_on_rtl_is_bit_exact',
 'test_qwen35':'test_qwen35_0_8b_token_on_rtl_is_bit_exact',
 'test_models_on_board_rtl':'test_token_on_board_rtl_is_bit_exact',
}
BOARD_CASES=(('qwen3','Qwen3-0.6B'),('lfm2','LFM2.5-230M'),
 ('lfm2-resident','LFM2.5-230M'),('qwen35','Qwen3.5-0.8B'),
 ('qwen35-dstep','Qwen3.5-0.8B'))


def additions():
    cases=list(CASES)
    for label,model in BOARD_CASES:
        for cols in (2,4):
            cases.append((f'{label}-board-c{cols}','test_models_on_board_rtl',
                          f'{label}-{cols}',model,'native'))
    result={}
    for label,module,suffix,model,path in cases:
        node=FUNCTIONS[module]+'['+suffix+']'
        env=dict(BASE_ENVIRONMENT)
        if path=='native':env.update(OTPU_AXI='1',OTPU_BOOT='1')
        result['checkpoint-'+label]={
          'mode':'top-test','timeout':14400,'requires_dependency_manifest':True,
          'requires_checkpoint':True,'checkpoint_directory':'models/'+model,
          'checkpoint_required_files':['config.json'],
          'checkpoint_required_globs':{'*.safetensors':1},
          # Record presence AND absence; Qwen3/LFM load this when present.
          'checkpoint_optional_files':(['generation_config.json'] if model!='Qwen3.5-0.8B' else []),
          'checkpoint_file_policy':'all matching safetensors; no index or tokenizer required',
          'coverage_scope':'real_checkpoint_native_top','memory_path':path,
          'hardware_environment':env,
          'args':[f'tests/{module}.py::{node}']+(['--runslow'] if path=='native' else []),
          'cases':[(f'tests.{module}',node)],
        }
    return result
