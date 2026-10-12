"""Finite random-model runtime cases; exact inventories from test decorators.

Requires a qualified CPU Torch/Transformers environment. No imports of tests.
Zero skips required, including all --runslow cases explicitly selected below.
"""

def additions(board_environment):
    def suite(module, names, mode='board-native-test', slow=False, env=None, timeout=7200):
        return {'mode': mode, 'timeout': timeout, 'requires_dependency_manifest': True,
                'hardware_environment': dict(board_environment if env is None else env),
                'args': [f'tests/{module}.py::{name}' for name in names] + (['--runslow'] if slow else []),
                'cases': [(f'tests.{module}', name) for name in names]}

    def ids(function, suffixes):
        return [function + '[' + suffix + ']' for suffix in suffixes]

    top_environment = dict(board_environment, OTPU_AXI='1', OTPU_BOOT='1',
                           OTPU_LDC='0', OTPU_STALL='20', OTPU_SEED='1')
    # This existing resident test uses the Engine's default design configuration.
    design_environment = dict(top_environment, OTPU_AXI='0', OTPU_BOOT='0')
    return {
        'model-qwen35-moe-board': suite('test_qwen35_moe', ['test_moe_on_board_rtl_logits_and_state']),
        'model-gemma4-moe-board': suite('test_gemma4_moe', ['test_moe_on_board_rtl_logits_and_state']),
        'model-qwen3-board': suite('test_board', ids('test_tiny_qwen3_on_board_model', (
            '', 'attn=fp4,down=int4,head=fp4', 'attn@0=fp4,mlp@1=fp4')) +
            ['test_tiny_qwen3_generate_on_board_model']),
        'model-lfm2-board': suite('test_lfm2', ids('test_tiny_lfm2_on_board_model', (
            'False-', 'True-', 'True-conv=fp4,attn=int4,down=fp4',
            'True-mlp@0=fp4,conv@1-4=fp4,attn@1-4=int4'))),
        'model-lfm2-moe-board': suite('test_lfm2_moe', ['test_moe_on_board_model']),
        'model-qwen35-board': suite('test_qwen35', ids('test_tiny_qwen35_on_board_model', (
            fixture + '-' + parameters for fixture in ('kh8', 'kh4') for parameters in (
                'False-False-', 'True-False-', 'True-True-', 'stream-False-',
                'True-True-delta=fp4,attn=int4,gateup=fp4',
                'True-True-mlp@0-2=fp4,delta@3-5=fp4,attn@3-5=int4')))),
        'model-qwen35-groups-board': suite('test_qwen35', ids('test_group_major_on_board_model', (
            fixture + '-' + flag for fixture in ('h16', 'h18') for flag in ('False', 'True')))),
        'model-qwen35-no-dstep-board': suite('test_qwen35', ids(
            'test_tiny_qwen35_on_a_board_without_dstep', ('kh8', 'kh4')),
            # This test discovers capabilities with device_config(). DSTEP=0
            # also disables STREAM, while column reuse remains present.
            env=dict(board_environment, OTPU_PAIR='1', OTPU_DSTEP='0', OTPU_STREAM='0')),
        'model-gemma4-top': suite('test_gemma4', ids('test_token_on_board_rtl_is_bit_exact', (
            'per-position', 'resident', 'resident-ple-host')),
            mode='top-test', slow=True, env=top_environment, timeout=14400),
        'model-qwen3-prefill-top': suite('test_qwen3', ids(
            'test_tiny_prefill_chunk_with_mm_replay_on_rtl', ('2-int8', '4-int8', '2-fp4')),
            mode='top-test', env=top_environment),
        'model-qwen35-prefill-top': suite('test_qwen35', ids(
            'test_tiny_prefill_rows_dstep_on_rtl', ('kh8', 'kh4')) + ['test_prefill_rows_pipeline_on_rtl'],
            mode='top-test', env=top_environment),
        'model-lfm2-mlp-top': suite('test_lfm2', ['test_tiny_mlp_loop_on_rtl'],
            mode='top-test', env=top_environment),
        'model-lfm2-resident-design-top': suite('test_lfm2', ['test_tiny_resident_decode_on_rtl'],
            mode='top-test', env=design_environment),
    }
