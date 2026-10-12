"""Convert positive-edge flops to an arbitrary discrete clock-edge transition.

The original clock input bits denote edge occurrence, independently. All flops
in a domain update together; simultaneous domain edges observe the same old
state, matching nonblocking assignment semantics. No clock-domain is omitted.
"""
import copy

def edge_model(netlist):
    result=copy.deepcopy(netlist)
    for module in result['modules'].values():
        assert 'clk' not in module['ports']
        bits=[b for net in module['netnames'].values() for b in net['bits'] if isinstance(b,int)]
        next_bit=max(bits)+1
        common_clock=next_bit;next_bit+=1
        module['ports']['clk']={'direction':'input','bits':[common_clock]}
        clocks={tuple(module['ports'][name]['bits']) for name in ['wclk','rclk']}
        for index,(name,cell) in enumerate(list(module['cells'].items())):
            if cell['type']!='$dff':continue
            con=cell['connections']
            assert tuple(con['CLK']) in clocks,(name,con['CLK'])
            assert int(cell['parameters']['CLK_POLARITY'],2)==1
            width=len(con['Q']);assert len(con['D'])==width
            out=list(range(next_bit,next_bit+width));next_bit+=width
            muxname=f'$edge_enable_{index}'
            assert muxname not in module['cells']
            module['cells'][muxname]={'hide_name':1,'type':'$mux',
                'parameters':{'WIDTH':format(width,'032b')},'attributes':{},
                'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
                'connections':{'A':list(con['Q']),'B':list(con['D']),'S':list(con['CLK']),'Y':out}}
            con['D']=out
            con['CLK']=[common_clock]
    return result
