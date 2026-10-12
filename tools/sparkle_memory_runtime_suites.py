"""Original Top native-memory stress regressions, without copied/downsized tests.

The first13 cases retain the generic default Top microarchitecture. The last12
explicitly select rtlsim.BOARD_UARCH in the original tests. All retain original
S1/D128/C8/R8/ACT16/L8 geometry. This is not production C4/R4 geometry coverage.
"""

MEMORY_ENVIRONMENT = {
    'OTPU_MCOLS':'8', 'OTPU_LANES':'8', 'OTPU_ACT_ROWS':'8',
    'OTPU_MXU':'systolic', 'OTPU_MXU_CL':'16', 'OTPU_VPU_CL':'2',
    'OTPU_ULANES':'8', 'OTPU_UARCH':'generic', 'OTPU_NATIVE':'1',
    'OTPU_PAIR':'0', 'OTPU_DSTEP':'0', 'OTPU_STREAM':'0',
    'OTPU_AXI':'1', 'OTPU_BOOT':'1', 'OTPU_LDC':'0', 'OTPU_LDC_MHZ':'0',
    'OTPU_STALL':'20', 'OTPU_SEED':'1', 'OTPU_BW':'100', 'OTPU_LAT':'20',
}

# Literal parameter IDs, independent of pytest collection and source decorators.
CASES = {
    'top-native-memory-latency': ('test_native_memory_path', (
        'hazard-0-0-20', 'hazard-1-50-20', 'hazard-2-80-120',
        'random-3-40-20', 'random-4-70-400')),
    'top-native-memory-scoreboard': ('test_board_memory_path_stress', (
        '0-0', '1-30', '2-60', '3-30', '4-80', '5-50')),
    'top-native-memory-fuzz': ('test_board_memory_path_fuzz', ('0-40', '1-70')),
    'top-native-memory-partial-order': ('test_axi_sw_partial_beat_order', (
        '0-1', '30-2', '60-3', '80-4')),
    'top-native-memory-rmw-fuzz': ('test_axi_sw_rmw_fuzz', (
        '0', '1', '2', '3', '4', '5', '6', '7')),
}


def additions():
    result={}
    for suite,(function,parameters) in CASES.items():
        names=[function+'['+suffix+']' for suffix in parameters]
        result[suite]={'mode':'top-test','timeout':3600,
            'hardware_environment':dict(MEMORY_ENVIRONMENT),
            'args':['tests/test_rtl.py::'+name for name in names],
            'cases':[('tests.test_rtl',name) for name in names]}
    return result

# Integration into tools/qualify_sparkle_runtime_refresh.py, after existing additions:
# from sparkle_memory_runtime_suites import additions as memory_additions
# SUITES.update(memory_additions())
