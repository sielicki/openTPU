"""Preserve audited original undriven wires, never promote them to inputs.

Their independently unconstrained SAT value/undef pairs overapproximate source
unknowns. Every observable bit still must pass strong definedness and equality.
No claim of structural irrelevance is made.
"""
from streamlane_mux_adapter import SlicedIndex
from check_sparkle_fpga_top_complete import require

MISSING_SHA={
    'gold':'00b8f87320adedc5048894c4094596d8ca79969128bbb78d9da5a9a90b129ff7',
    'gate':'37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570'}

def inventory(store,side):
    driven=set();used=set()
    for name,p in store.rows(side,'ports'):
        require(p['direction'] in ('input','output'),'Unsupported port direction')
        if p['direction']=='input':driven.update(b for b in p['bits'] if type(b)is int)
        else:used.update(b for b in p['bits'] if type(b)is int)
    for name,c in store.rows(side,'cells'):
        require(set(c['connections'])==set(c['port_directions']),'Missing connection direction')
        for pin,bits in c['connections'].items():
            require(c['port_directions'][pin] in ('input','output'),'Unsupported cell direction')
            (driven if c['port_directions'][pin]=='output' else used).update(b for b in bits if type(b)is int)
    return driven,used

def audit_origin(parent,steps,side,expected):
    require(type(expected)is list and all(type(b)is int and b>=0 for b in expected) and expected==sorted(set(expected)),
            'Invalid pinned missing-wire inventory')
    step_driven,step_used=inventory(steps,side);missing=step_used-step_driven
    require(missing==set(expected),'Actual missing-wire inventory differs')
    del step_driven,step_used
    original_driven,original_used=inventory(parent,side)
    require(not missing&original_driven,'Missing wire was driven in original parent')
    require(missing<=original_used,'Missing wire absent from original parent')
    aliases={};aliased=set()
    for name,n in parent.rows(side,'netnames'):
        hits=[{'index_lsb':i,'bit':b} for i,b in enumerate(n['bits']) if type(b)is int and b in missing]
        if hits:
            require('init' not in n.get('attributes',{}),'Missing-wire alias carries initializer')
            aliases[name]=hits;aliased.update(h['bit'] for h in hits)
    require(aliased==missing,'Original missing-wire alias coverage incomplete')
    return {'missing_bits':sorted(missing),'original_aliases':aliases,'original_parent_drivers':[],
            'semantics':'original internal wires; independent unconstrained value/undef; no new primary inputs'}

class OriginalUndrivenIndex(SlicedIndex):
    def __init__(self,store,side,manifest,rule,missing):
        self.original_missing=frozenset(missing)
        super().__init__(store,side,manifest,rule)
        for bit in self.original_missing:
            require(self.db.execute('SELECT 1 FROM drivers WHERE side=? AND bit=?',(side,bit)).fetchone() is None,
                    'Approved original undriven wire now has driver')
    def driver(self,bit):
        if type(bit)is int and bit in self.original_missing:
            require(self.db.execute('SELECT 1 FROM drivers WHERE side=? AND bit=?',(self.side,bit)).fetchone() is None,
                    'Undriven identity conflicts with actual driver')
            return ('original_undriven',str(bit),0)
        return super().driver(bit)

WIRE_MODEL='''std::string wire_name = bit.wire->name.unescape();
std::string name = pf +
(bit.wire->width == 1 ? wire_name : stringf("%s [%d]", wire_name, bit.offset));
vec.push_back(ez->frozen_literal(name));
imported_signals[pf][bit] = vec.back();'''
UNDEF_MODEL='''std::string pf = "undef:" + prefix + (timestep == -1 ? "" : stringf("@%d:", timestep));
return importSigSpecWorker(sig, pf, true, false);'''
def audit_wire_model(text):
    for anchor in (WIRE_MODEL,UNDEF_MODEL):
        require(''.join(text.split()).count(''.join(anchor.split()))==1,'Installed undriven SAT model differs')
    return {'wire_values':'named frozen literals','wire_undef':'independent undef:-prefixed named literals',
            'constraint_policy':'no added constraints on original internal missing wires'}
