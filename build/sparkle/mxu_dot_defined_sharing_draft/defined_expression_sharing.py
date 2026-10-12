"""Exact duplicate defined-expression substitution; never creates a cut/input.

Caller supplies an authenticated model-rule set, independently from a previous
signature diagnostic. This checker recomputes exact expression identities and
definedness from actual source cells. Hash signatures are not equality premises.
"""
import copy
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_dot_arithmetic_diagnostic_draft'))
from arithmetic_signatures import rule
from cascade_cones import cell_pins
from dot_initial_store import need

RULES={'$mux','$not','$logic_not','$and','$or','$xor','$xnor','$add','$sub','$mul','$eq','$ne'}

def share(raw,approved_rules):
    need(set(raw)=={'modules'} and set(raw['modules'])=={'paired'},'exact paired module required')
    module=raw['modules']['paired']
    need(set(module)=={'attributes','ports','netnames','cells'},'unknown module sections')
    need(not module['attributes'] and not module['netnames'],'expected generated paired module metadata')
    need(set(approved_rules)<=RULES and '$mul' in approved_rules,'unsupported/incomplete authenticated model rules')
    cells=module['cells'];drivers={};known=set();inputs={};substitutions={};removed={};canonical={};order=[]
    def bit_ok(bit):need(type(bit)is int or type(bit)is str and bit in ('0','1','x','z'),'invalid signal bit')
    def driver(bits,owner):
        for bit in bits:
            need(type(bit)is int and bit not in drivers,'ambiguous or constant driver');drivers[bit]=owner
    for name,port in module['ports'].items():
        need(set(port)=={'direction','bits'} and port['direction'] in ('input','output'),'unexpected port schema')
        for bit in port['bits']:bit_ok(bit)
        if port['direction']=='input':
            need(name.startswith('shared_'),'unexpected/nonoriginal input port')
            driver(port['bits'],('input',name));known.update(port['bits']);inputs[name]=copy.deepcopy(port)
    need(set(name for name,p in module['ports'].items() if p['direction']=='output')=={'paired_mismatch'},'complete mismatch observation differs')
    for name,cell in cells.items():
        need(name=='mismatch' or name.startswith(('gold:','gate:')),'unexpected cross-side owner')
        need(cell['type']!='$dff' and 'init' not in cell.get('attributes',{}),'state/initial constraint in step graph')
        ins,outs=cell_pins(cell)
        for bits in cell['connections'].values():
            for bit in bits:bit_ok(bit)
        for pin in outs:driver(cell['connections'][pin],('cell',name))
    def owner(bit):
        if type(bit)is str:return None
        need(bit in drivers,'missing driver');return drivers[bit]
    for port in module['ports'].values():
        for bit in port['bits']:owner(bit)
    for name,cell in cells.items():
        ins,_=cell_pins(cell)
        for pin in ins:
            for bit in cell['connections'][pin]:
                source=owner(bit)
                if source and source[0]=='cell' and name!='mismatch':
                    need(source[1].split(':',1)[0]==name.split(':',1)[0],'source side depends on another side/internal comparator')
    def translate(bit):return substitutions.get(bit,bit) if type(bit)is int else bit
    def defined(bit):return bit in ('0','1') if type(bit)is str else bit in known
    done=set();active=set();replay=[]
    def visit(start):
        stack=[(start,False)]
        while stack:
            name,closing=stack.pop()
            if name in done:continue
            cell=cells[name];ins,outs=cell_pins(cell)
            if not closing:
                need(name not in active,'combinational cycle');active.add(name);stack.append((name,True))
                dependencies={source[1] for pin in ins for bit in cell['connections'][pin]
                              if (source:=owner(bit)) is not None and source[0]=='cell'}
                stack.extend((dep,False) for dep in sorted(dependencies));continue
            active.remove(name);done.add(name);order.append(name)
            pin_inputs={pin:[translate(bit) for bit in cell['connections'][pin]] for pin in sorted(ins)}
            model=rule(cell) if cell['type'] in approved_rules else None
            eligible=model is not None and all(defined(bit) for bits in pin_inputs.values() for bit in bits)
            if not eligible:continue
            outputs={pin:cell['connections'][pin] for pin in sorted(outs)}
            for bits in outputs.values():known.update(bits)
            key=json.dumps({'type':cell['type'],'parameters':cell['parameters'],'directions':cell['port_directions'],
                            'attributes':{k:v for k,v in cell.get('attributes',{}).items() if k!='src'},
                            'inputs':pin_inputs,'output_widths':{pin:len(bits) for pin,bits in outputs.items()}},sort_keys=True)
            proof={'cell':name,'rule':model,'inputs_after_prior_substitutions':pin_inputs,'outputs':outputs}
            replay.append(proof)
            if name.startswith('gold:'):canonical.setdefault(key,name)
            elif name.startswith('gate:') and key in canonical:
                target=canonical[key];target_cell=cells[target]
                pairs=[]
                for pin,bits in outputs.items():
                    targets=target_cell['connections'][pin]
                    need(len(bits)==len(targets),'output coordinate widths differ')
                    for old,new in zip(bits,targets):
                        need(old not in substitutions and old!=new and new in known and new not in substitutions,
                             'cyclic/duplicate/nondefined substitution')
                        substitutions[old]=new;pairs.append([old,new])
                removed[name]={'canonical':target,'rule':model,'output_pairs':pairs,'exact_expression':json.loads(key)}
    # Gold cells are processed first, making canonical targets independent of all
    # gate substitutions; original side independence was audited above.
    for prefix in ('gold:','gate:'):
        for name in sorted(n for n in cells if n.startswith(prefix)):visit(name)
    for name in sorted(cells):visit(name)
    result=copy.deepcopy(raw);target=result['modules']['paired']
    for name in list(target['cells']):
        if name in removed:del target['cells'][name];continue
        target['cells'][name]['connections']={pin:[translate(bit) for bit in bits]
                                              for pin,bits in target['cells'][name]['connections'].items()}
    for port in target['ports'].values():port['bits']=[translate(bit) for bit in port['bits']]
    need({n:p for n,p in target['ports'].items() if p['direction']=='input'}==inputs,'rewrite changed inputs or introduced cuts')
    need(len(target['ports']['paired_mismatch']['bits'])==len(module['ports']['paired_mismatch']['bits'])==1,'observation dropped')
    certificate={'kind':'exact_duplicate_defined_expression_substitution','approved_rules':sorted(approved_rules),
                 'topological_order':order,'defined_expression_replay':replay,'removed_cells':removed,
                 'substitutions':[[old,new] for old,new in sorted(substitutions.items())],
                 'original_cell_count':len(cells),'retained_cell_count':len(target['cells']),
                 'original_input_ports':inputs,'new_inputs':[],'new_assumptions':[],
                 'unknown_expression_outputs_shared':False,'equality_proven':False}
    return result,certificate


def verify_rewrite(original,rewritten,certificate,approved_rules):
    expected,expected_certificate=share(original,approved_rules)
    need(rewritten==expected,'rewritten graph differs from exact certified substitution')
    need(certificate==expected_certificate,'substitution certificate differs from independent replay')
    return True
