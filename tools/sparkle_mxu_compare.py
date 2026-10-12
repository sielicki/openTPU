"""Exact RTLIL comparison orientation, preserving operand widths and signs."""


def normalize_comparisons(netlist):
    count=0
    for module in netlist['modules'].values():
        for cell in module['cells'].values():
            kind=cell['type']
            if kind not in ('$gt','$ge'):continue
            cell['type']={'$gt':'$lt','$ge':'$le'}[kind]
            ports=cell['connections']
            ports['A'],ports['B']=ports['B'],ports['A']
            params=cell['parameters']
            for suffix in ('WIDTH','SIGNED'):
                a,b='A_'+suffix,'B_'+suffix
                params[a],params[b]=params[b],params[a]
            count+=1
    return count
