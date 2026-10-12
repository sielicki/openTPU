"""Common clock audit is separate from data-boundary equivalence classes."""
import json
from joint_partition import owner,flop,memid
from physical_slices import require,number


def native_clock(module,expected_q):
    clock=module['ports']['clk'];require(clock['direction']=='input' and len(clock['bits'])==1 and type(clock['bits'][0])is int,'Native scalar clock differs')
    q=set();owners=[]
    for name,cell in module['cells'].items():
        if cell['type']=='$dff':
            flop(cell);require(cell['connections']['CLK']==clock['bits'],'Native flop common clock differs')
            bits=cell['connections']['Q'];require(not q.intersection(bits),'Aliased native clocked Q');q.update(bits);owners.append(name)
    require(q==set(expected_q),'Complete native clocked state differs')
    return {'clock_port':clock,'positive_edge':True,'state_bits':len(q),'actual_flop_owners':owners}


def original_clock(db,selected):
    clock=owner(db,'ports','clk');require(clock['direction']=='input' and len(clock['bits'])==1,'Original scalar clock differs')
    seen={}
    for coordinate in selected:
        if coordinate[0]!='Q':continue
        q=coordinate[1];r=db.execute('SELECT cell,clock,polarity FROM qd WHERE module="otpu_vpu" AND q=?',(q,)).fetchone()
        require(r is not None,'Missing selected original flop');name,c,p=r
        cell=seen.setdefault(name,owner(db,'cells',name));flop(cell)
        require(q in cell['connections']['Q'] and cell['connections']['CLK']==json.loads(c)==clock['bits'] and p==1,'Selected original common clock differs')
    writers=[]
    for name,payload in db.execute('SELECT name,payload FROM owners WHERE module="otpu_vpu" AND section="cells"'):
        cell=json.loads(payload)
        if cell['type']=='$memwr_v2' and cell['parameters']['MEMID'] in ('cq','\\cq','g_wbuf.wq','\\g_wbuf.wq'):
            require(cell==owner(db,'cells',name),'Actual memory owner digest differs')
            require(cell['connections']['CLK']==clock['bits'] and number(cell['parameters']['CLK_ENABLE'])==number(cell['parameters']['CLK_POLARITY'])==1,'Selected actual memory writer clock differs')
            writers.append({'owner':name,'memory':memid(cell,('cq','g_wbuf.wq')),'clock':cell['connections']['CLK']})
    require(len(writers)==2 and {r['memory'] for r in writers}=={'cq','g_wbuf.wq'},'Complete selected memory writer clock inventory differs')
    return {'clock_port':clock,'positive_edge':True,'flop_owner_count':len(seen),'memory_writers':writers}
