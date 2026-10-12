"""Unexecuted local helpers; integrate only after review. No shared-tool edits."""
import copy


def require(ok,message):
    if not ok:raise RuntimeError(message)


def normalize_buffers(module):
    """Exact unsigned identity: actual $buf(A) becomes $or(A, all-zero).

    This preserves X propagation as well as binary bits. No aliases, ports,
    register pins or initializer attributes change. Do before expose_steps.
    """
    result=copy.deepcopy(module);changed=[]
    for name,cell in result['cells'].items():
        if cell['type']!='$buf':continue
        require(set(cell['parameters'])=={'WIDTH'} and
                cell['port_directions']=={'A':'input','Y':'output'} and
                set(cell['connections'])=={'A','Y'},'Malformed projected buffer')
        bits=cell['parameters']['WIDTH'];width=int(bits,2);c=cell['connections']
        require(width>0 and len(c['A'])==len(c['Y'])==width and
                all(type(b)is int for b in c['Y']) and len(set(c['Y']))==width and
                all(type(b)is int or b in ['0','1','x'] for b in c['A']),
                'Malformed projected buffer widths/bits')
        cell.update(type='$or',parameters={'A_SIGNED':'0','B_SIGNED':'0',
            'A_WIDTH':bits,'B_WIDTH':bits,'Y_WIDTH':bits},
            port_directions={'A':'input','B':'input','Y':'output'},
            connections={'A':c['A'],'B':['0']*width,'Y':c['Y']})
        changed.append(name)
    return result,sorted(changed)


def add_definedness_outputs(harness):
    require(harness.count('output step_ok,output_ok,observer_ok);')==1 and
            harness.count('endmodule')==1,'Unexpected actual diagnostic harness')
    harness=harness.replace('output step_ok,output_ok,observer_ok);',
        'output step_ok,output_ok,observer_ok,output [21:0] observed,output impossible);')
    return harness.replace('endmodule',
        'assign observed={gold_next,gold_count,gold_pop,gold_dv,gold_fault,gate_next,gate_count,gate_pop,gate_dv,gate_fault};\n'+
        'assign impossible=1\'b0;\nendmodule')


def sat_command(prop,model,definedness=False):
    if definedness:
        # This asks whether ANY observed bit can be X, while every public
        # input/state/boundary bit is defined but otherwise unrestricted.
        # Proving false==true is possible exactly when the X query is UNSAT.
        theorem='-set-any-undef observed -prove impossible 1'
    else:
        require(prop in ['step_ok','output_ok','observer_ok'],'Unknown property')
        theorem='-prove '+prop+' 1'
    return 'sat -enable_undef -set-def-inputs '+theorem+' -verify -show-inputs -show-outputs -dump_json '+str(model)+'\n'
