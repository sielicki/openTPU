"""Reviewed finite value/undef formulas; supporting checks, not a kernel proof.

The caller must separately authenticate the source-to-executable build closure.
Exact source snapshots fail closed on drift; matching them alone is not that join.
"""
from hashlib import sha256
from itertools import product
from pathlib import Path
from physical_slices import require

STATES = tuple(product((0, 1), repeat=2))  # (value, undefined), including both X values


def snapshot_model(source_dir):
    here = Path(__file__).resolve().parent
    records = {}
    for filename in ('satgen.cc', 'satgen.h'):
        actual = Path(source_dir) / 'kernel' / filename
        expected = here / (filename + '.snapshot')
        a, b = sha256(), sha256()
        with actual.open('rb') as left, expected.open('rb') as right:
            while True:
                x, y = left.read(65536), right.read(65536)
                require(x == y, 'Actual SatGen source differs from reviewed complete snapshot')
                if not x:
                    break
                a.update(x); b.update(y)
        records[filename] = {'actual_path': str(actual), 'snapshot_path': str(expected),
                             'actual_sha256': a.hexdigest(), 'snapshot_sha256': b.hexdigest()}
    return {'sources': records, 'source_snapshot_equal': True,
            'executable_source_link_verified': False, 'formal_kernel_certificate': False}


def import_token(token, identity):
    """Pinned importSigSpecWorker token branch AFTER SigMap; identities, not constraints.

    Call identity is (owner,pin,position); distinct literal-X imports remain fresh.
    Named wire value/undef identities are shared. Z treatment is the literal
    worker's actual comparison behavior, not a claim about frontend Z handling.
    The eventual graph driver must establish JSON-to-post-SigMap identity or
    absence of additional aliases before using this token model.
    """
    if type(token) is int and token >= 0:
        return ('wire_value', token), ('wire_undef', token)
    require(type(token) is str and token in ('0', '1', 'x', 'z'), 'Invalid import token')
    if token == 'x':
        return ('literal_x_value', identity), 1
    return int(token == '1'), 0


def permitted(value, undefined):
    return frozenset(((0, 1), (1, 1))) if undefined else frozenset(((value, 0),))


def coordinate(kind, a, branches=(), selectors=()):
    """Set of permitted Y(value,undef) after actual undefGating."""
    require(a in STATES and all(x in STATES for x in (*branches, *selectors)),
            'Invalid Boolean value/undef pair')
    if kind == '$buf':
        require(not branches and not selectors, 'Buffer has extra model inputs')
        return permitted(*a)
    require(kind in ('$mux', '$pmux') and len(branches) == len(selectors) > 0,
            'Model branch/selector schema differs')
    if kind == '$mux':
        require(len(selectors) == 1, 'Mux selector is not scalar')
        b, (s, su) = branches[0], selectors[0]
        v = b[0] if s else a[0]
        u = ((a[0] != b[0]) or a[1] or b[1]) if su else (b[1] if s else a[1])
        return permitted(v, u)
    v, u = a
    found, all_undef = 0, 0
    for b, (s, su) in zip(branches, selectors):
        if s:
            v, u = b
        all_undef = all_undef or su or (s and found)
        found = found or s
    return permitted(v, u or all_undef)


def vector_model(kind, a, b=(), s=()):
    """Independent vector transcription of the pinned cell branch equations."""
    w = len(a)
    require(w > 0, 'Empty model vector')
    if kind == '$buf':
        require(not b and not s, 'Buffer vectors differ')
        values, undefs = zip(*a)
    elif kind == '$mux':
        require(len(b) == w and len(s) == 1, 'Mux vectors differ')
        sel, usel = s[0]
        values = [bv[0] if sel else av[0] for av, bv in zip(a, b)]
        undefs = [(av[0] != bv[0] or av[1] or bv[1]) if usel
                  else (bv[1] if sel else av[1]) for av, bv in zip(a, b)]
    else:
        require(kind == '$pmux' and s and len(b) == w*len(s), 'Pmux vectors differ')
        values, undefs = [x[0] for x in a], [x[1] for x in a]
        found, all_undef = 0, 0
        for j, (sel, usel) in enumerate(s):
            if sel:
                values = [x[0] for x in b[j*w:(j+1)*w]]
                undefs = [x[1] for x in b[j*w:(j+1)*w]]
            all_undef |= bool(usel or (sel and found))
            found |= sel
        undefs = [u or all_undef for u in undefs]
    return tuple(permitted(v, u) for v, u in zip(values, undefs))


def check_finite_model(kind, width, selector_count):
    """Exhaustive small relation check; no bounded-width extrapolation theorem."""
    require(type(width) is int and 1 <= width <= 2, 'Fixture width limit')
    require((kind, selector_count) in (('$buf', 0), ('$mux', 1), ('$pmux', 2)),
            'Unsupported fixture geometry')
    cases = 0
    for assignment in product(STATES, repeat=width*(1+selector_count)+selector_count):
        a = assignment[:width]
        b = assignment[width:width*(1+selector_count)]
        s = assignment[width*(1+selector_count):]
        outputs = vector_model(kind, a, b, s)
        for i in range(width):
            branches = tuple(b[j*width+i] for j in range(selector_count))
            require(outputs[i] == coordinate(kind, a[i], branches, s), 'Formula mismatch')
            # Existentially forgetting other independently gated outputs leaves
            # exactly this coordinate relation, since every output set is nonempty.
            require(all(outputs), 'Projection discarded an unsatisfiable output')
        cases += 1
    return {'kind': kind, 'width': width, 'selectors': selector_count,
            'exhaustive_assignments': cases, 'small_model_only': True,
            'arbitrary_width_kernel_proof': False}
