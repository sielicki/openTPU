"""Draft exact parent state exposure and exhaustive paired combinational cones."""
import json
from streamlane_graph_store import Store
from check_sparkle_fpga_top_complete import require
from cascade_cones import cell_pins
from inventory import fp_instances


def normalized_cell(cell):
    if cell['type']!='$buf':return cell
    require(set(cell['parameters'])=={'WIDTH'} and cell['port_directions']=={'A':'input','Y':'output'} and
            set(cell['connections'])=={'A','Y'},'Unsupported buffer schema')
    w=int(cell['parameters']['WIDTH'],2);c=cell['connections']
    require(w>0 and len(c['A'])==len(c['Y'])==w,'Buffer width differs')
    # Four-state identity: A OR zero, with no resizing/sign conversion.
    return {**cell,'type':'$or','parameters':{'A_SIGNED':'0','B_SIGNED':'0','A_WIDTH':format(w,'b'),
            'B_WIDTH':format(w,'b'),'Y_WIDTH':format(w,'b')},
            'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{**c,'B':['0']*w}}


def expose(store,audits,path):
    """Remove ONLY actual audited DFF and FP cells; Q/FP-y become shared inputs.

    Netname init attributes are absent in the combinational query, after witness
    validation in the prior receipt. No init/state constraints enter these queries.
    Every original D and external/FP-input bit remains an observed output.
    """
    manifests={};contracts={}
    with path.open('w') as out:
        out.write('{"creator":"streamlane audited full-step exposure","modules":{')
        for si,side in enumerate(['gold','gate']):
            if si:out.write(',')
            audit=audits[side];ports={};removed=set(audit['cuts'])
            def add(name,direction,bits):
                require(name not in ports,'Exposed port collision');ports[name]={'direction':direction,'bits':list(bits)}
            for name,p in store.rows(side,'ports'):
                actual=name[2:] if side=='gold' and name.startswith(('i_','o_')) else name
                add(actual,p['direction'],p['bits'])
            qcovered=set();actual_qd={}
            for name,cell in store.rows(side,'cells'):
                if cell['type']=='$dff':
                    removed.add(name)
                    for q,d in zip(cell['connections']['Q'],cell['connections']['D']):
                        require(q not in actual_qd,'Duplicate raw Q');actual_qd[q]=d
            require(actual_qd=={int(q):d for q,d in audit['all_qd'].items()},'Frozen actual Q/D changed')
            for name,item in sorted(audit['mapped'].items()):
                q=item['Q'];d=item['D'];require(not qcovered&set(q),'Mapped state overlap');qcovered.update(q)
                require([actual_qd[b] for b in q]==d,'Mapped D changed')
                add('state_'+name,'input',q);add('next_'+name,'output',d)
            require(qcovered==actual_qd.keys() and len(qcovered)==18982,'Incomplete retained state exposure')
            for native,reference,_,_ in fp_instances():
                key=reference if side=='gold' else native
                cell=store.get(side,'cells',key)
                require(cell==audit['cuts'][key],'Actual FP cut changed after audit')
                c=cell['connections'];require(c['clk']==ports['clk']['bits'],'FP clock changed')
                for pin in ['en','a','b','y']:add('pipe_'+native+'_'+pin,'input' if pin=='y' else 'output',c[pin])
            contract={n:(p['direction'],len(p['bits'])) for n,p in ports.items()};contracts[side]=contract
            manifest=[];offset=0
            for name in sorted(ports):
                if ports[name]['direction']!='output':continue
                width=len(ports[name]['bits']);manifest.append({'port':name,'offset_lsb':offset,'width':width});offset+=width
            require(offset==24427,'Complete output/D/FP-input inventory differs');manifests[side]=manifest
            out.write(json.dumps(side)+':{"attributes":{},"ports":');json.dump(ports,out)
            out.write(',"netnames":{},"cells":{');count=0
            for name,cell in store.rows(side,'cells'):
                if name in removed:continue
                require(cell['type'].startswith('$'),'Remaining opaque child')
                if count:out.write(',')
                out.write(json.dumps(name)+':');json.dump(normalized_cell(cell),out);count+=1
            out.write('}}')
        out.write('}}\n')
    require(contracts['gold']==contracts['gate'] and manifests['gold']==manifests['gate'],'Paired full interfaces differ')
    return {'manifest':manifests['gold'],'inputs':{n:w for n,(d,w) in contracts['gate'].items() if d=='input'},
            'output_bits':24427,'state_bits':18982}


def partition(width,chunk=32):
    require(type(width)is int and width>0 and type(chunk)is int and 1<=chunk<=32,'Invalid bounded partition')
    return [(lo,min(width,lo+chunk)) for lo in range(0,width,chunk)]


def coverage(ranges,width):
    cursor=0
    for lo,hi in sorted(ranges):
        require(lo==cursor and lo<hi<=width,'Partition gap/overlap');cursor=hi
    require(cursor==width,'Incomplete obligation partition')


class Index:
    def __init__(self,store,side,manifest):
        self.store=store;self.side=side;self.db=store.db
        self.db.execute('CREATE TABLE IF NOT EXISTS drivers(side TEXT,bit INTEGER,kind TEXT,name TEXT,idx INTEGER,PRIMARY KEY(side,bit))')
        self.db.execute('CREATE TABLE IF NOT EXISTS visited(side TEXT,name TEXT,done INTEGER,PRIMARY KEY(side,name))')
        self.vector=[]
        for item in manifest:
            require(item['offset_lsb']==len(self.vector),'Manifest offset differs')
            bits=store.get(side,'ports',item['port'])['bits'];require(len(bits)==item['width'],'Manifest width differs');self.vector.extend(bits)
        for name,p in store.rows(side,'ports'):
            if p['direction']=='input':
                for i,b in enumerate(p['bits']):
                    require(type(b)is int,'Input literal invalid');self.db.execute('INSERT INTO drivers VALUES (?,?,?,?,?)',(side,b,'input',name,i))
        for name,cell in store.rows(side,'cells'):
            ins,outs=cell_pins(cell);require(cell['type']!='$dff','Unexposed state')
            for pin in sorted(outs):
                for i,b in enumerate(cell['connections'][pin]):
                    require(type(b)is int,'Constant cell driver');self.db.execute('INSERT INTO drivers VALUES (?,?,?,?,?)',(side,b,'cell',name,i))
        for name,_ in store.rows(side,'cells'):self.visit(name)
        for b in self.vector:self.driver(b)
        self.db.commit()
    def driver(self,bit):
        require(type(bit)is int and bit>=0 or type(bit)is str and bit in {'0','1','x','z'},'Invalid bit token')
        if type(bit)is str:return ('literal',bit,0)
        row=self.db.execute('SELECT kind,name,idx FROM drivers WHERE side=? AND bit=?',(self.side,bit)).fetchone()
        require(row is not None,'Undriven graph bit '+str(bit));return row
    def dependencies(self,name):
        cell=self.store.get(self.side,'cells',name);ins,_=cell_pins(cell)
        return [b for pin in sorted(ins) for b in cell['connections'][pin]]
    def visit(self,name):
        stack=[(name,False)]
        while stack:
            name,finish=stack.pop()
            row=self.db.execute('SELECT done FROM visited WHERE side=? AND name=?',(self.side,name)).fetchone()
            if finish:self.db.execute('UPDATE visited SET done=1 WHERE side=? AND name=?',(self.side,name));continue
            if row is not None:require(row[0]==1,'Combinational cycle');continue
            self.db.execute('INSERT INTO visited VALUES (?,?,0)',(self.side,name));stack.append((name,True))
            deps=set()
            for bit in self.dependencies(name):
                kind,owner,_=self.driver(bit)
                if kind=='cell':deps.add(owner)
            stack.extend((dep,False) for dep in sorted(deps))
    def cone(self,lo,hi):
        require(0<=lo<hi<=len(self.vector),'Invalid output slice')
        cells=set();roots={};todo=list(self.vector[lo:hi])
        while todo:
            bit=todo.pop();kind,name,index=self.driver(bit)
            if kind=='input':roots[(name,index)]=bit
            elif kind=='cell' and name not in cells:cells.add(name);todo.extend(self.dependencies(name))
        return cells,roots


def write_pair(path,indexes,lo,hi):
    cones={s:indexes[s].cone(lo,hi) for s in ['gold','gate']}
    keys=sorted(set(cones['gold'][1])|set(cones['gate'][1]));root_ids={k:i for i,k in enumerate(keys)}
    with path.open('w') as out:
        out.write('{"modules":{')
        for si,side in enumerate(['gold','gate']):
            if si:out.write(',')
            ix=indexes[side];cells,roots=cones[side];ports={'observed':{'direction':'output','bits':ix.vector[lo:hi]}}
            for key,b in roots.items():ports['root_'+str(root_ids[key])]={'direction':'input','bits':[b]}
            out.write(json.dumps(side)+':{"attributes":{},"ports":');json.dump(ports,out);out.write(',"netnames":{},"cells":{')
            for ci,name in enumerate(sorted(cells)):
                if ci:out.write(',')
                out.write(json.dumps(name)+':');json.dump(ix.store.get(side,'cells',name),out)
            out.write('}}')
        out.write('}}\n')
    return {'lo':lo,'hi':hi,'roots':[{'name':n,'index':i,'id':root_ids[(n,i)]} for n,i in keys],
            'used':{s:sorted(root_ids[k] for k in cones[s][1]) for s in cones},
            'cells':{s:len(cones[s][0]) for s in cones}}


def harness(record):
    width=record['hi']-record['lo'];count=len(record['roots'])
    header='module check('+','.join([f'input root_{i}' for i in range(count)]+['output equal_ok,output impossible',f'output [{2*width-1}:0] observed'])+');\n'
    rows=[header,f'wire [{width-1}:0] gold_observed,gate_observed;']
    for side in ['gold','gate']:
        pins=[f'.root_{i}(root_{i})' for i in record['used'][side]]+[f'.observed({side}_observed)']
        rows.append(side+' u_'+side+'('+','.join(pins)+');')
    rows+=['assign observed={gold_observed,gate_observed};','assign equal_ok=(gold_observed==gate_observed);',"assign impossible=1'b0;",'endmodule\n']
    return '\n'.join(rows)
