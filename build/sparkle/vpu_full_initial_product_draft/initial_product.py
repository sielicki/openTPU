"""Initial-predicate implication for an explicit namespaced state relation."""

def require(ok, message):
    if not ok:
        raise ValueError(message)


def implication(pairs, original_all, original_initial, native_all, native_initial):
    original = [a for a, _ in pairs]
    native = [b for _, b in pairs]
    require(len(set(original)) == len(original), 'Original relation is not injective')
    require(len(set(native)) == len(native), 'Native relation is not injective')
    require(set(original) <= original_all and set(native) == native_all,
            'Incomplete or foreign state coordinates')
    require(set(original_initial) <= original_all and set(native_initial) <= native_all,
            'Initializer outside state')
    require(all(v in ('0', '1') for v in list(original_initial.values()) + list(native_initial.values())),
            'Defined initial predicate must use binary constraints')
    for a, b in pairs:
        require(a not in original_initial or native_initial.get(b) == original_initial[a],
                'Native initial predicate does not imply paired original constraint')
    return {
        'quantifier': 'for_every_defined_native_product_initial_state_exists_original_initial_state',
        'related_assignment': 'assign_each_original_coordinate_its_paired_native_value',
        'complement_assignment': 'choose_once_obeying_all_original_initial_constraints_otherwise_arbitrary',
        'related_bits': len(pairs),
        'original_defined_constraints': len(original_initial),
        'native_defined_constraints': len(native_initial),
        'unconstrained_related_memory_bits': sum(a[0] == 'memory' and a not in original_initial and b not in native_initial for a,b in pairs),
        'sampled_reset_assumed': False,
        'zero_filled_memory_assumed': False,
        'transition_or_layout_correspondence_proven': False,
    }


def namespace(unit, bits, values):
    require(set(values) <= set(bits), 'Native initializer outside unit state')
    return {(unit, b) for b in bits}, {(unit, b):v for b,v in values.items()}
