"""Explicit proof owners; no imports of exploratory diagnostic programs."""
from pathlib import Path
from physical_slices import require

PINS = {
 'composition': ('vpu-joint-initialized-composition-first', 'cdf0d979476b12b4e37de7ed63538dbd2016d00bb056705e19b40e97760988cc'),
 'original': ('vpu-original-control-inventory-seventh', '1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'partition': ('vpu-joint-partition-first', '8c0374eaf99c809be8d64bd01ef126ac092f39fc3a825bf7fc75768db0e84a35'),
 'binding': ('vpu-control-initial-binding-second', '704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8')}
COMB = ('vpu-control-comb-third', '7271adaaafc7d1b53c1a4c1aa969a046d8efe1f369a465f5994805b8a76e1203')


def prepare_sources(session, modules, root, draft, physical_sha):
    """Register the exact prerequisite before its implementation is consumed."""
    path = root/'build/sparkle/vpu-joint-physical-proof-first/summary.json'
    require(session.maps['composition'].get(str(path)) == physical_sha, 'Exact model owner join absent')
    physical = session.record('physical', path, physical_sha)
    implementation = {}
    for module in modules:
        filename = getattr(module, '__file__', None)
        if not filename: continue
        p = Path(filename).resolve()
        if not (p.is_relative_to(root/'tools') or p.is_relative_to(root/'build/sparkle')): continue
        expected = [m[str(p)] for m in session.maps.values() if str(p) in m]
        require(len(set(expected)) <= 1, 'Imported historical source disagreement')
        require(p.parent == draft or expected, 'Imported helper absent from explicit owning closures: '+str(p))
        implementation[str(p)] = session.freeze(p, expected[0] if expected else None)
    return physical, implementation
