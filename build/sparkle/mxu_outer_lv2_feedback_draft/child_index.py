"""Local structural graph index; global arithmetic model extension is NOT proved."""
from child_valid import ROOT
from observation_queries import PairedIndex
from ownership_cones import cell_pins,UNARY,BINARY
from dot_initial_store import need


def structural_schema(cell):
    need(set(cell)<={'type','parameters','attributes','port_directions','connections','hide_name'},'unknown structural cell owner')
    need('init' not in cell.get('attributes',{}),'structural cell initializer unsupported')
    typ=cell['type'];need(typ.startswith('$') and typ!='$dff','state/opaque primitive in stepped graph')
    inputs,outputs=cell_pins(cell);params=cell['parameters'];pins=cell['connections']
    need(all(type(v)is list and v for v in pins.values()),'empty/nonvector structural primitive pin')
    need(all(type(b)is int and b>=0 or type(b)is str and b in ('0','1','x','z') for bits in pins.values() for b in bits),
        'invalid structural bit token')
    def number(name):
        v=params[name];need(type(v)is str and v and set(v)<=set('01'),'unresolved structural parameter');return int(v,2)
    if typ in UNARY|BINARY:
        expected={'A_WIDTH','A_SIGNED','Y_WIDTH'}|({'B_WIDTH','B_SIGNED'} if typ in BINARY else set())
        need(set(params)==expected,'structural arithmetic parameter inventory')
        for pin in inputs|outputs:need(number(pin+'_WIDTH')==len(pins[pin])>0,'structural arithmetic width mismatch')
        for pin in inputs:need(number(pin+'_SIGNED') in (0,1),'structural sign parameter')
    elif typ in ('$mux','$pmux'):
        need(set(params)==({'WIDTH'} if typ=='$mux' else {'WIDTH','S_WIDTH'}),'structural mux parameter inventory')
        w=number('WIDTH');s=1 if typ=='$mux' else number('S_WIDTH')
        need(w>0 and s>0 and len(pins['A'])==len(pins['Y'])==w and len(pins['S'])==s and
            len(pins['B'])==w*(1 if typ=='$mux' else s),'structural mux width mismatch')
    else:
        need(typ in ('$bmux','$bwmux','$demux'),'unreviewed structural cell')
        # Existing cell_pins above checks every selector dimension/parameter.
    return inputs,outputs


class StructuralChildIndex(PairedIndex):
    def dependencies(self,name):
        cell=self.cell(name);inputs,_=structural_schema(cell)
        return [b for pin in sorted(inputs) for b in cell['connections'][pin]]
