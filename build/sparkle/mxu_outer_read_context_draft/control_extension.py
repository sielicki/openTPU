"""Unexecuted constructive-extension audit for the auxiliary read-cut graph.

The DAG is only the structural half. Authentication binds the reviewed actual
SatGen rules; arbitrary input value/undef pairs extend through each accepted
cell, including intermediate mux outputs and per-use literal-X imports.
"""
from pathlib import Path
import sys
from outer_memory_context import ROOT,graph_audit
from dot_initial_store import need
from ownership_cones import cell_pins
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_dot_model_extension_draft'),
             str(ROOT/'build/sparkle/mxu_dot_defined_sharing_draft'),
             str(ROOT/'build/sparkle/mxu_dot_composition_draft'),
             str(ROOT/'build/sparkle/mxu_dot_initial_draft'),
             str(ROOT/'build/sparkle/mxu_cascade_draft')]
from extension_model import authenticate_extension_model

UNARY={'$not','$logic_not','$reduce_and','$reduce_or','$reduce_bool'}
BINARY={'$add','$and','$eq','$ge','$gt','$le','$logic_and','$logic_or',
        '$lt','$mul','$or','$sub'}
TYPES=UNARY|BINARY|{'$mux','$bmux'}
EXTRA_ANCHORS=(
    'bool is_arith_compare = cell->type.in(ID($lt), ID($le), ID($ge), ID($gt));',
    'if (cell->type == ID($bmux))',
    'std::vector<int> yy = model_undef ? ez->vec_var(out.size()) : out;',
    'if (cell->type == ID($reduce_and))',
    'if (cell->type.in(ID($reduce_or), ID($reduce_bool)))',
    'ez->assume(ez->IFF(ez->AND(ez->NOT(a0), aX), undef_y.at(0)));',
    'ez->assume(ez->IFF(ez->AND(ez->NOT(a1), aX), undef_y.at(0)));',
    'if (cell->type.in(ID($logic_and), ID($logic_or)))',
)


def number(params,name):
    value=params[name]
    need(type(value)is str and value and set(value)<=set('01'),'nonbinary control cell parameter')
    return int(value,2)


def schema(cell):
    typ=cell['type'];need(typ in TYPES,'unreviewed auxiliary primitive '+typ)
    need(set(cell)<={'type','parameters','attributes','port_directions','connections','hide_name'},
         'unknown auxiliary primitive metadata')
    need('init' not in cell.get('attributes',{}),'constraint in auxiliary primitive')
    cell_pins(cell)
    params=cell['parameters'];pins=cell['connections']
    for bits in pins.values():
        need(type(bits)is list,'nonvector primitive port')
        for bit in bits:
            need(type(bit)is int and bit>=0 or type(bit)is str and bit in ('0','1','x'),
                 'unsupported primitive bit or Z')
    if typ in ('$mux','$bmux'):
        need(set(params)==({'WIDTH'} if typ=='$mux' else {'WIDTH','S_WIDTH'}),
             'selector parameter inventory')
        width=number(params,'WIDTH');sw=1 if typ=='$mux' else number(params,'S_WIDTH')
        need(width>0 and sw>0,'empty auxiliary selector')
        if typ=='$mux':
            need(len(pins['A'])==len(pins['B'])==len(pins['Y'])==width and len(pins['S'])==1,
                 'mux coordinate dimensions')
        else:
            # Compare bit_length before shifting; malformed widths must not
            # allocate an enormous integer while validating a small graph.
            blocks=len(pins['A'])//width
            need(blocks>0 and blocks.bit_length()==sw+1 and blocks&(blocks-1)==0 and
                 len(pins['A'])==blocks*width and len(pins['Y'])==width and len(pins['S'])==sw,
                 'bmux coordinate dimensions')
        return {'type':typ,'width':width,'select_width':sw}
    expected={'A_SIGNED','A_WIDTH','Y_WIDTH'}
    if typ in BINARY:expected|={'B_SIGNED','B_WIDTH'}
    need(set(params)==expected,'arithmetic parameter inventory')
    dims={name:number(params,name) for name in params}
    for pin in ('A','Y') if typ in UNARY else ('A','B','Y'):
        need(dims[pin+'_WIDTH']>0 and dims[pin+'_WIDTH']==len(pins[pin]),'arithmetic dimensions')
    need(all(dims[name] in (0,1) for name in dims if name.endswith('_SIGNED')),'invalid sign parameter')
    return {'type':typ,**dims}


def authenticate_model(binary,source,freeze):
    base=authenticate_extension_model(binary,source,freeze)
    text=(Path(source)/'kernel/satgen.cc').read_text()
    need(all(anchor in text for anchor in EXTRA_ANCHORS),'auxiliary extension source anchor mismatch')
    return {'source_authentication':base['source_authentication'],
            'accepted_cell_types':sorted(TYPES),'model_undef':True,
            'rule':'constructive total relation on arbitrary value/undef inputs; no input constraint',
            'witness':'compute yy and output mask; choose known Y from yy and unknown Y freely; recursively extend bmux stages',
            'literal_x':'fresh underlying value per import use, mask one',
            'control_definedness_proven':False,'memory_semantics_proven':False}


def audit(module):
    need(set(module)<={'attributes','parameter_default_values','ports','cells','netnames'},
         'unknown/unlowered auxiliary module owner')
    need(not module.get('parameter_default_values',{}),'parameterized auxiliary module')
    need(not any(k in module.get('attributes',{}) for k in ('init','blackbox','whitebox')),
         'constrained or opaque auxiliary module')
    counts={}
    for cell in module['cells'].values():
        schema(cell);typ=cell['type'];counts[typ]=counts.get(typ,0)+1
    for kind in ('ports','netnames'):
        for owner in module[kind].values():
            need('init' not in owner,'direct auxiliary owner initializer')
            need('init' not in owner.get('attributes',{}),'initial constraint in auxiliary owner')
            for bit in owner['bits']:
                need(type(bit)is int and bit>=0 or type(bit)is str and bit in ('0','1','x'),'invalid/Z auxiliary alias')
    result=graph_audit(module)
    return {**result,'cell_types':dict(sorted(counts.items())),
            'schema_audit_complete':True,'model_authentication_required':True,
            'control_definedness_proven':False,'graph_modified':False}
