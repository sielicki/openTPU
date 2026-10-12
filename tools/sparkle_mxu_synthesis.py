"""Selective xc7 pipeline preservation for already explicit MXU DSP48E1s."""
import re
from pathlib import Path

ATTRIBUTE = 'opentpu_preserve_dsp_pipeline'
REGISTERS = ('AREG','BREG','CREG','DREG','ADREG','MREG','PREG','INMODEREG','OPMODEREG')


def selective_xc7(top, instance_globs, expected_dsps, work):
    """Emit commands after read_slang, preserving only named explicit DSP cells.

    Hierarchy globs refer to flattened cell names (e.g. ``slice0.mxu.impl.dot.*``).
    The exact count guards against hierarchy drift and accidentally empty cuts.
    Standard multiplier inference runs across the entire design. Only subsequent
    DSP register packing excludes the tagged explicit cells. No ``-nodsp`` flag
    is used. Snapshots make this property independently auditable.
    """
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',top):
        raise ValueError('Invalid synthesis top identifier')
    if not instance_globs or expected_dsps <= 0:
        raise ValueError('Explicit MXU DSP hierarchy and expected count are required')
    if any(not re.fullmatch(r'[A-Za-z0-9_.*?]+',p) for p in instance_globs):
        raise ValueError('Invalid flattened MXU hierarchy glob')
    work = Path(work)
    def snapshot(name):
        return f'select *\nwrite_json -selected {work}/{name}.json\nselect -clear\n'
    selection = ' '.join(f'{top}/c:{p}' for p in instance_globs)
    selection += ' %u' * (len(instance_globs)-1) + f' {top}/t:DSP48E1 %i'
    return f'''select -assert-none {top}/a:{ATTRIBUTE}
select -set opentpu_mxu_dsps {selection}
select -assert-count {expected_dsps} @opentpu_mxu_dsps
setattr -set {ATTRIBUTE} 1 @opentpu_mxu_dsps
select -clear
{snapshot('initial')}scratchpad -assert-unset xilinx_dsp.multonly
scratchpad -set xilinx_dsp.multonly 1
synth_xilinx -family xc7 -top {top} -flatten -noclkbuf -noiopad -run begin:coarse
scratchpad -unset xilinx_dsp.multonly
{snapshot('inferred')}xilinx_dsp -family xc7 */* */a:{ATTRIBUTE} %d
select -clear
{snapshot('packed')}synth_xilinx -family xc7 -top {top} -flatten -noclkbuf -noiopad -run coarse:
xilinx_srl -fixed -minlen 2
techmap -map +/xilinx/cells_map.v
clean
scratchpad -assert-unset xilinx_dsp.multonly
select -assert-count {expected_dsps} {top}/a:{ATTRIBUTE}
{snapshot('mapped')}'''


def protected(module):
    return {n:c for n,c in module['cells'].items() if c['attributes'].get(ATTRIBUTE)}


def audit_preservation(stages, expected_dsps):
    """Require exact protected parameters and connections, plus real FP packing."""
    initial = protected(stages['initial'])
    if len(initial) != expected_dsps or any(c['type']!='DSP48E1' for c in initial.values()):
        raise RuntimeError('Incorrect explicit MXU DSP selection')
    for stage,module in stages.items():
        cells = protected(module)
        if cells.keys() != initial.keys():
            raise RuntimeError(f'{stage}: protected DSP population changed')
        for name,c in cells.items():
            if c['type']!='DSP48E1' or c['parameters']!=initial[name]['parameters']:
                raise RuntimeError(f'{stage}: protected DSP parameters changed: {name}')
    before,after = stages['inferred'],stages['packed']
    aliases = {}
    for name,net in before['netnames'].items():
        other = after['netnames'].get(name)
        if other is None or len(net['bits'])!=len(other['bits']): continue
        for a,b in zip(net['bits'],other['bits']): aliases.setdefault(a,set()).add(b)
    for name,c in protected(before).items():
        pc = after['cells'][name]
        if c['connections'].keys()!=pc['connections'].keys():
            raise RuntimeError('Protected DSP port set changed')
        for port,bits in c['connections'].items():
            other = pc['connections'][port]
            if len(bits)!=len(other) or any((a!=b if isinstance(a,str) else b not in aliases.get(a,set())) for a,b in zip(bits,other)):
                raise RuntimeError(f'Protected DSP connection changed: {name}.{port}')
    inferred = {n:c for n,c in before['cells'].items() if c['type']=='DSP48E1' and n not in initial}
    if not inferred:
        raise RuntimeError('Unrelated multiplier DSP inference did not run')
    if any(c['type']=='$mul' for c in before['cells'].values()):
        raise RuntimeError('Qualification multiplier was left in fabric')
    packed = []
    for name,c in inferred.items():
        pc = after['cells'].get(name)
        if pc is None or pc['type']!='DSP48E1': raise RuntimeError('Inferred DSP disappeared')
        changed = [p for p in REGISTERS if int(pc['parameters'].get(p,'0'),2)>int(c['parameters'].get(p,'0'),2)]
        if changed: packed.append({'cell':name,'registers':changed})
    if not packed:
        raise RuntimeError('Unrelated DSP pipeline packing did not run')
    return {'protected_dsps':len(initial),'inferred_dsps':len(inferred),'packed_unrelated_dsps':packed,
            'protected_parameters_unchanged':True,'protected_packing_boundary_connections_unchanged':True}


def design_view(modules):
    """Namespace per-module bits for audits across retained arithmetic hierarchy."""
    import copy
    result = {'cells':{},'netnames':{}}
    for module,m in modules.items():
        bit = lambda b: b if isinstance(b,str) else (module,b)
        for name,c in m['cells'].items():
            c=copy.deepcopy(c)
            c['connections']={p:[bit(b) for b in bs] for p,bs in c['connections'].items()}
            result['cells'][module+'/'+name]=c
        for name,n in m['netnames'].items():
            result['netnames'][module+'/'+name]={'bits':[bit(b) for b in n['bits']]}
    return result


def primitive_counts(modules,top):
    """Count actual leaf instances recursively, including kept FP submodules."""
    from collections import Counter
    def count(name,ancestors):
        if name in ancestors: raise RuntimeError('Recursive synthesis hierarchy')
        total=Counter()
        for c in modules[name]['cells'].values():
            kind=c['type']
            if kind in modules: total.update(count(kind,ancestors+[name]))
            else: total[kind]+=1
        return total
    return dict(count(top,[]))
