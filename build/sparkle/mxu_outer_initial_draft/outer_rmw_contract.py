"""Read-only pin resolution for the eight exact audited RMW blackboxes."""
from dot_initial_store import need,encoded

PINS={'clk':('input',1),'en':('input',1),'a':('input',32),'b':('input',32),'y':('output',32)}
TYPES={'proof_mul','proof_add','otpu_mxu_fmul','otpu_mxu_fadd'}


def declarations(modules):
    result={}
    for typ in TYPES:
        need(typ in modules,'missing authenticated RMW blackbox declaration')
        module=modules[typ]
        need(module.get('cells')=={} and not module.get('processes') and not module.get('memories'),
             'RMW declaration is not an empty blackbox')
        need(int(module.get('attributes',{}).get('blackbox','0'),2)==1,'RMW declaration lacks blackbox attribute')
        need(not module.get('parameter_default_values',{}),'RMW declaration has parameters')
        need(set(module['ports'])==set(PINS),'RMW declaration complete pins differ')
        for pin,(direction,width) in PINS.items():
            need(module['ports'][pin]['direction']==direction and len(module['ports'][pin]['bits'])==width,
                 'RMW declaration pin schema differs')
        need('init' not in module and 'init' not in module.get('attributes',{}),'RMW declaration initializer')
        for group in ('ports','netnames'):
            for item in module[group].values():
                need('init' not in item and 'init' not in item.get('attributes',{}),'RMW declaration hidden initialization')
        result[typ]={'type':typ,'parameters':{},'empty_blackbox':True,
                     'pins':{pin:{'direction':dr,'width':width} for pin,(dr,width) in PINS.items()}}
    return result


def expected_instances(side):
    need(side in ('gold','gate'),'RMW resolution requires explicit graph side')
    return {(f'g_rmw[{lane}].u_y.u_{letter}' if side=='gold' else f'rmw_{op}{lane}'):
            ('proof_'+op if side=='gold' else 'otpu_mxu_f'+op)
            for lane in range(4) for op,letter in (('mul','m'),('add','a'))}


def directions(side,module,name,cell,contracts=None):
    """Return checked directions without adding fields to the graph being compared.

    Only an exact RMW occurrence can omit port_directions; its fallback must
    originate from declarations checked in the authenticated original flat
    graph. Other cells require their own explicit complete direction map.
    """
    expected=expected_instances(side) if side is not None else {}
    if name not in expected and cell['type'] not in TYPES:
        need('port_directions' in cell,'missing primitive pin directions')
        value=cell['port_directions']
        need(set(value)==set(cell['connections']) and all(dr in ('input','output') for dr in value.values()),
             'incomplete explicit primitive directions')
        return dict(value)
    need(name in expected and cell['type']==expected[name],'RMW occurrence name/type differs')
    need(cell['parameters']=={},'RMW specialization has parameters')
    need(set(cell['connections'])==set(PINS),'RMW complete pin inventory differs')
    need(cell['connections']['clk']==module['ports']['clk']['bits'],'RMW clock is not the common clock')
    resolved={pin:dr for pin,(dr,width) in PINS.items()}
    for pin,(dr,width) in PINS.items():
        need(len(cell['connections'][pin])==width,'RMW actual pin width differs')
        for bit in cell['connections'][pin]:encoded(bit)
    if contracts is not None:
        need(contracts.get(cell['type'])=={'type':cell['type'],'parameters':{},'empty_blackbox':True,
            'pins':{pin:{'direction':dr,'width':width} for pin,(dr,width) in PINS.items()}},
            'RMW declaration context absent or changed')
    if 'port_directions' in cell:
        need(cell['port_directions']==resolved,'RMW explicit directions differ from its contract')
    else:
        need(contracts is not None,'missing authenticated RMW declaration for omitted directions')
    return resolved
