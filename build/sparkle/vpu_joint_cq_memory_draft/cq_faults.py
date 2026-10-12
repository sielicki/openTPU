"""Actual original access-pin mutations, upstream of memory lowering and comparison."""
import copy
from physical_slices import require


class Overlay:
    def __init__(self, original, cells):
        self.original = original; self.cells = cells
        self.drivers = {b: (n, c) for n, c in cells.items() for pin, bs in c['connections'].items()
                        if c['port_directions'][pin] == 'output' for b in bs}
    def producer(self, bit): return self.drivers.get(bit) or self.original.producer(bit)
    def alias(self, name): return self.original.alias(name)


def mutate_access(original, accesses, contract, fault, fresh, occupied_names):
    require(fault in ('write_address', 'read_address', 'reset_write'), 'Unknown actual memory fault')
    require(type(fresh) is int and fresh > 0, 'Invalid fresh fault coordinate')
    changed = copy.deepcopy(accesses); cells = {}; name = 'actual_cq_fault_'+fault; changes = []
    if fault in ('write_address', 'read_address'):
        owner = contract['writer' if fault == 'write_address' else 'reader']
        old = list(changed[owner]['connections']['ADDR']); new = [fresh]
        require(len(old) == 1 and fresh not in old, 'Actual address mutation ineffective')
        cells[name] = {'type': '$not', 'attributes': {},
            'parameters': {'A_SIGNED': '0', 'A_WIDTH': '1', 'Y_WIDTH': '1'},
            'port_directions': {'A': 'input', 'Y': 'output'}, 'connections': {'A': old, 'Y': new}}
        changed[owner]['connections']['ADDR'] = new; pin = 'ADDR'
        changes.append({'pin': pin, 'old_bits': old, 'new_bits': new})
    else:
        owner = contract['writer']; old = list(changed[owner]['connections']['EN'])
        rst = original.alias('rst'); require(len(rst) == 1, 'Actual reset alias differs')
        new = list(range(fresh, fresh+240))
        cells[name] = {'type': '$mux', 'attributes': {}, 'parameters': {'WIDTH': format(240, '032b')},
            'port_directions': {'A': 'input', 'B': 'input', 'S': 'input', 'Y': 'output'},
            'connections': {'A': old, 'B': ['1']*240, 'S': rst, 'Y': new}}
        changed[owner]['connections']['EN'] = new; pin = 'EN'
        changes.append({'pin': pin, 'old_bits': old, 'new_bits': new})
        # A deliberately defined erroneous reset write: old inactive ADDR/DATA
        # may be X. Override them on rst as well, instead of assuming knownness.
        cmd = original.alias('cmd'); require(len(cmd) == 240, 'Actual command alias differs')
        for suffix, changed_pin, replacement, first in (
            ('address', 'ADDR', ['0'], fresh+240), ('data', 'DATA', cmd, fresh+241)):
            previous = list(changed[owner]['connections'][changed_pin]); width = len(previous)
            target = list(range(first, first+width))
            require(len(replacement) == width, 'Reset fault replacement width differs')
            cells[name+'_'+suffix] = {'type': '$mux', 'attributes': {}, 'parameters': {'WIDTH': format(width, '032b')},
                'port_directions': {'A': 'input', 'B': 'input', 'S': 'input', 'Y': 'output'},
                'connections': {'A': previous, 'B': list(replacement), 'S': rst, 'Y': target}}
            changed[owner]['connections'][changed_pin] = target
            changes.append({'pin': changed_pin, 'old_bits': previous, 'new_bits': target})
    # Verify the single intended original-owner delta; the extra real logic is
    # an upstream hardware mutation, never a comparison/proof output change.
    require(not set(cells) & set(occupied_names), 'Mutation owner collides with original hardware')
    restored = copy.deepcopy(changed)
    for delta in changes: restored[owner]['connections'][delta['pin']] = delta['old_bits']
    require(restored == accesses, 'Unintended original access-owner changes')
    require(all(original.producer(b) is None for c in cells.values() for p, bs in c['connections'].items()
                if c['port_directions'][p] == 'output' for b in bs), 'Fault wire collides with original driver')
    return Overlay(original, cells), changed, {'fault': fault, 'actual_owner': owner, 'pin': pin,
        'old_bits': old, 'new_bits': new, 'actual_added_cells': cells, 'before_memory_lowering': True,
        'all_original_pin_changes': changes,
        'reset_one_counterexample_required': fault == 'reset_write'}
