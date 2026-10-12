"""Full module/directive and actual control pin bridge; no behavior by names."""
from pathlib import Path
from check_sparkle_fp_state_consumers import selected_modules
from check_sparkle_fpga_top_complete import global_directives
from control_applicability import CONTROL, ports, edge
from physical_slices import require
from issue_bridge import INPUTS, OUTPUTS, INTERNAL

MODULE = 'otpu_vpu_issue_sparkle'


def identity(path, name):
    modules = selected_modules(path, {name}); _, context = global_directives(path)
    require(set(modules) == {name}, 'Unique complete module absent')
    return modules[name], context[name]


def bind_case(assembly, proved_source, case):
    actual, context = identity(assembly, MODULE)
    require((actual, context) == identity(proved_source, MODULE), 'Reached/proved issue full body/directives differ')
    pp = ports(actual)
    require({n:(d,w) for n,d,w in pp} == {**{n:('input',w) for n,w in INPUTS.items()},
                                              **{n:('output',w) for n,w in OUTPUTS.items()}}, 'Exact reached issue ABI differs')
    parent, pcontext = identity(assembly, CONTROL)
    providers = {n for n,d,w in ports(parent) if d == 'output'}
    wiring = edge(parent, 'issue', pp, providers)
    wires = dict(wiring)
    require(len(wires) == len(wiring), 'Duplicate issue pin')
    expected = {n: ('c_hold' if n == 'c_hold' else 'control_'+n) for n in INPUTS}
    require({n:wires[n] for n in INPUTS} == expected, 'Actual issue input provider expressions differ')
    components = {c['unit']:c for c in case['components']}
    require(set(components) == {'command','sequence','stream','write_buffer'}, 'Complete bound component set differs')
    state_outputs = {(n[2:] if n.startswith('o_') else n):(n,w) for n,d,w in components['sequence']['all_ports'] if d == 'output'}
    sequence_wires = dict(components['sequence']['edge'])
    for n,w in INPUTS.items():
        if n == 'c_hold': continue
        require(n in state_outputs and state_outputs[n][1] == w and
                sequence_wires[state_outputs[n][0]] == wires[n], 'Reached sequence state provider differs '+n)
    consumers = {}
    for n,w in INTERNAL.items():
        found = []
        for unit, component in components.items():
            mapping = dict(component['edge'])
            for pin,direction,width in component['all_ports']:
                if direction == 'input' and mapping[pin] == wires[n]:
                    require(pin == n and width == w, 'Internal consumer pin coordinate differs')
                    found.append({'unit': unit, 'pin': pin, 'width': width, 'expression': mapping[pin]})
        require(found, 'Proven internal provider has no actual bound consumer')
        consumers[n] = found
    cp = [a['path'] for a in case['ancestors'] if a['module'] == CONTROL]
    require(len(cp) == 1, 'Unique reached control path absent')
    return {'case': case['name'], 'issue_path': cp[0]+'/u_issue', 'complete_ports': pp,
            'actual_ordered_edge': wiring, 'internal_consumers': consumers,
            'parent_complete_tokens': parent, 'parent_incoming_directives': pcontext,
            'c_hold_scope': 'actual_control_external_datapath_port_not_producer_equivalence'}
