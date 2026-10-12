"""Conservative bit liveness for retained MXU register-array proof state.

read_slang can pack an unpacked array into one wide DFF even when its last array
word is unobserved. Remove only DFF bits outside the complete backwards cone of
all outputs, following every enabled hold feedback and every state transition.
All other operators conservatively depend on every input bit; bit slicing is
used only for DFF and exact-width mux cells. This never uses reachability or
arithmetic assumptions to discard state.
"""


def prune_unobserved_register_bits(netlist, protected=None):
    """Keep explicitly related state even when neither design observes it.

    `protected` adds proof obligations; it can never remove a live bit.
    """
    report={}
    for name,module in netlist['modules'].items():
        live={b for p in module['ports'].values() if p['direction']=='output'
              for b in p['bits'] if isinstance(b,int)}
        live.update((protected or {}).get(name, []))
        changed=True
        while changed:
            previous=len(live)
            for cell in module['cells'].values():
                p=cell['connections']
                if cell['type']=='$dff':
                    used=[i for i,b in enumerate(p['Q']) if b in live]
                    needed=[p['D'][i] for i in used]+(p['CLK'] if used else [])
                elif (cell['type']=='$mux' and len(p['Y'])==len(p['A'])==len(p['B'])
                      and len(p['S'])==1):
                    used=[i for i,b in enumerate(p['Y']) if b in live]
                    needed=[p[x][i] for i in used for x in ['A','B']]+(p['S'] if used else [])
                else:
                    outputs=[b for port,direction in cell['port_directions'].items() if direction=='output' for b in p[port]]
                    needed=[b for port,direction in cell['port_directions'].items() if direction=='input' for b in p[port]] if any(b in live for b in outputs) else []
                live.update(b for b in needed if isinstance(b,int))
            changed=len(live)!=previous
        removed=0
        for cell_name,cell in list(module['cells'].items()):
            if cell['type']!='$dff': continue
            ports=cell['connections']
            keep=[i for i,b in enumerate(ports['Q']) if b in live]
            removed+=len(ports['Q'])-len(keep)
            if not keep:
                del module['cells'][cell_name]
            elif len(keep)!=len(ports['Q']):
                ports['D']=[ports['D'][i] for i in keep]
                ports['Q']=[ports['Q'][i] for i in keep]
                cell['parameters']['WIDTH']=format(len(keep),'032b')
        report[name]=removed
    return report
