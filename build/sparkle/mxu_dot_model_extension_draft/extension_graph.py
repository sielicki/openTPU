"""Complete unchanged combinational graph audit for model-extension induction."""
import json
from collections import Counter
from dot_definedness_cones import Index
from dot_initial_store import need
from cascade_cones import cell_pins

TYPES={'$add','$and','$eq','$eqx','$logic_not','$logic_or','$mul','$mux',
       '$not','$or','$pmux','$shiftx','$sub','$xnor','$xor'}
UNARY={'$not','$logic_not'}


def number(parameters,name):
    value=parameters[name]
    need(type(value)is str and value and set(value)<=set('01'),'nonbinary primitive parameter')
    return int(value,2)


def schema(cell):
    typ=cell['type'];need(typ in TYPES,'unreviewed primitive '+typ)
    params=cell['parameters'];pins=cell['connections'];cell_pins(cell)
    need(set(cell)<= {'type','parameters','attributes','port_directions','connections','hide_name'},'unknown cell metadata')
    need('init' not in cell.get('attributes',{}),'initial constraint in combinational model')
    for bits in pins.values():
        need(type(bits)is list,'nonvector cell port')
        for bit in bits:
            need(type(bit)is int or type(bit)is str and bit in ('0','1','x'),'invalid/Z constant')
    if typ in ('$mux','$pmux'):
        need(set(params)==({'WIDTH'} if typ=='$mux' else {'WIDTH','S_WIDTH'}),'mux parameter inventory')
        width=number(params,'WIDTH');sw=1 if typ=='$mux' else number(params,'S_WIDTH')
        need(width>0 and sw>0,'zero mux dimensions')
        need(len(pins['A'])==len(pins['Y'])==width and len(pins['B'])==width*sw and len(pins['S'])==sw,'mux dimensions differ')
        return {'type':typ,'width':width,'select_width':sw}
    expected={'A_WIDTH','Y_WIDTH','A_SIGNED'}
    if typ not in UNARY:expected|={'B_WIDTH','B_SIGNED'}
    need(set(params)==expected,'arithmetic parameter inventory')
    dims={name:number(params,name) for name in sorted(params)}
    for port in ('A','Y') if typ in UNARY else ('A','B','Y'):
        need(dims[port+'_WIDTH']>0 and len(pins[port])==dims[port+'_WIDTH'],'arithmetic dimensions differ')
    need(all(dims[name] in (0,1) for name in dims if name.endswith('_SIGNED')),'invalid signedness')
    return {'type':typ,**dims}


class ExtensionIndex(Index):
    def __init__(self,path,graph,side,omitted_state=()):
        self.types=Counter()
        super().__init__(path,graph,side,omitted_state)

    def dependencies(self,name):
        cell=self.cell(name);schema(cell)
        ins,_=cell_pins(cell)
        return [bit for pin in sorted(ins) for bit in cell['connections'][pin]]

    def certificate(self,path):
        counts=Counter();parameters=Counter();aliases=0;x_uses=0;cells=0
        with path.open('w') as out:
            for name,data in self.db.execute("SELECT name,data FROM owner WHERE design='probe' AND module=? AND kind='cells' ORDER BY name",(self.side,)):
                cell=json.loads(data);rule=schema(cell);counts[cell['type']]+=1;cells+=1
                parameters[json.dumps(rule,sort_keys=True)]+=1
                ins,_=cell_pins(cell)
                x_uses+=sum(bit=='x' for pin in ins for bit in cell['connections'][pin])
                out.write(json.dumps({'cell':name,'schema':rule},sort_keys=True)+'\n')
            for kind,name,data in self.db.execute("SELECT kind,name,data FROM owner WHERE design='probe' AND module=? AND kind IN ('ports','netnames') ORDER BY kind,name",(self.side,)):
                owner=json.loads(data)
                need('init' not in owner.get('attributes',{}),'initial assumption in stepped aliases')
                for bit in owner['bits']:
                    need(type(bit)is int or type(bit)is str and bit in ('0','1','x'),'unsupported alias literal')
                    # Unused aliases may retain old physical Q IDs. They are not
                    # new inputs, drivers, or assumptions. All real cell inputs
                    # and observed output roots are checked separately.
                    if kind=='ports':self.driver(bit)
                aliases+=len(owner['bits'])
        done=self.db.execute('SELECT COUNT(*) FROM visited WHERE done=1').fetchone()[0]
        need(done==cells,'incomplete full-cell DAG traversal')
        return {'cell_count':cells,'cell_types':dict(sorted(counts.items())),
                'schemas':dict(sorted(parameters.items())),
                'alias_bit_occurrences':aliases,'literal_x_input_uses':x_uses,
                'omitted_original_q_roots':sorted(self.omitted_state),
                'all_cells_acyclic':True,'graph_modified':False,
                'per_use_literal_x_preserved':True,'new_inputs':[],
                'new_constraints':[],'quotient_D_equality_required':False}


def strict_probe(path,side):
    """Validate complete framing/metadata without retaining the module."""
    from audit_sparkle_rtlil_roundtrip import Owners
    root=set();modules=set()
    with path.open() as stream:
        reader=Owners(stream)
        for key in reader.object():
            need(key not in root and key=='modules','unknown/duplicate graph root');root.add(key)
            for module in reader.object():
                need(module==side and module not in modules,'extra/duplicate module');modules.add(module)
                groups=set()
                for group in reader.object():
                    need(group not in groups and group in {'attributes','parameter_default_values','ports','cells','netnames'},'unknown/duplicate module group');groups.add(group)
                    if group in ('attributes','parameter_default_values'):
                        metadata=reader.value();need(type(metadata)is dict,'invalid module metadata')
                        need(not any(k in metadata for k in ('init','blackbox','whitebox')),'constrained/opaque module')
                        continue
                    names=set()
                    for name in reader.object():
                        need(name not in names,'duplicate owner');names.add(name)
                        owner=reader.value();need(type(owner)is dict,'invalid owner')
                        need('init' not in owner.get('attributes',{}),'initial assumption in combinational graph')
                        if group=='cells':schema(owner)
                need({'attributes','ports','cells','netnames'}<=groups,'missing module group')
        reader.whitespace();need(reader.eof and reader.pos==len(reader.buf),'trailing JSON')
    need(root=={'modules'} and modules=={side},'incomplete graph')
