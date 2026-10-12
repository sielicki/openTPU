"""Independent expected-case inventory for native Board runtime qualification.

The literal IDs below independently enumerate current op_checks(..., gen=True,
waitw=True) names. Fail the exact JUnit comparison if source enumeration changes.
Do not derive expected cases by collecting the same pytest invocation.

VPU edge cases use the ISA oracle and deliberately exclude NaN operands: the
original RTL and ISA have different NaN behavior. Native-versus-original FP
proofs and datapath comparisons cover those bit patterns separately.

The address suite combines a host SimTransport array/address-map check with an
RTL partial-write test. The former does not exercise hardware AXI/DDR address
lines. Native-memory cases exercise the direct native memory path with simulated
DRAM and stalls; neither suite qualifies physical DDR or clock-domain crossings.
"""

CONTROL_IDS = [
    'HALT', 'NOP', 'LI / ADDI (register offsets)', 'LOOP', 'LOOP nested',
    'LOOP count from a register (rcount)', 'LOOP count 0 (skips its body)', 'BAR',
    'LD / ST aligned', 'LD unaligned source', 'ST unaligned target',
    'LD / ST short (1..17 words)', 'LD / ST register offsets (ra dram, rb tmem)',
    'MM', 'MM UNIT', 'MM ACC', 'MM RMAX', 'MM ACC RMAX', 'MM UNIT ACC ASCALE',
    'MM M=1', 'MM ACT block ab=3', 'MM output row stride ors=40',
    'MM registers (ra sa, rb ssa, rc out)',
    'QACT ROW', 'QACT CSCALE', 'QACT RSCALE', 'QST dense',
    'QST strided (es=3)', 'QST ROW', 'GATHER',
    'RLD (truncation, inf, RAW, register offsets)',
    'RLD MUL (mod 2^32, negative, RAW)', 'RLD loop count, conditional HALT',
    'VOP ARGMAX rows, drs, index base', 'VOP ARGMAX edge values', 'HALT CHAIN',
    'WAITW EQ / NE / GE / mask', 'WAITW after a store',
]

# Actual VFUNCS order, with OUTER/ARGMAX handled separately. READS_B includes
# FILL and EXP2SUB as well as arithmetic and RDOT.
VPU_IDS = []
for function, reads_b in (
    ('ADD', True), ('SUB', True), ('RSUB', True), ('MUL', True), ('MAX', True),
    ('MIN', True), ('COPY', False), ('EXP2', False), ('RECIP', False),
    ('RSQRT', False), ('ABS', False), ('FILL', True), ('EXP2SUB', True),
    ('LOG2', False), ('RSUM', False), ('RMAX', False), ('RSSQ', False), ('RDOT', True),
):
    suffixes = (' FULL', ' ROW', ' COL', ' SCALAR') if reads_b else ('',)
    VPU_IDS += ['VOP ' + function + suffix for suffix in suffixes]
VPU_IDS += ['VOP OUTER ' + kind for kind in ('scalar', 'column', 'one')]
VPU_IDS += ['VOP ' + function + ' edge values' for function in (
    'EXP2', 'RECIP', 'RSQRT', 'EXP2SUB', 'LOG2', 'ADD', 'SUB', 'MUL',
    'MAX', 'MIN', 'ABS', 'COPY', 'RSUM', 'RMAX', 'RSSQ')]

assert len(CONTROL_IDS) == 38 and len(VPU_IDS) == 63
assert len(set(CONTROL_IDS + VPU_IDS)) == 101


def additions(board_environment):
    def suite(names, timeout=3600):
        return {
            'mode': 'board-native-test', 'timeout': timeout,
            'hardware_environment': dict(board_environment),
            'args': ['tests/test_board.py::' + name for name in names],
            'cases': [('tests.test_board', name) for name in names],
        }
    return {
        'board-op-control': suite(['test_op_check_on_board_model[' + name + ']'
                                   for name in CONTROL_IDS]),
        'board-op-vpu': suite(['test_op_check_on_board_model[' + name + ']'
                               for name in VPU_IDS]),
        'board-address': suite(['test_pattern_and_address_lines_on_board_model',
                                'test_partial_dram_writes_on_board_model'], 1800),
        'board-native-memory': suite(['test_program_on_native_board_model[3]',
                                      'test_program_on_native_board_model[4]'], 1800),
    }

# After installing these literals inside the qualifier:
# SUITES.update(additions(BOARD_ENVIRONMENT))
# All execution remains through sparkle_bounded.py, one suite at a time.
