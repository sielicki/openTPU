"""Exact observation coordinates; no equality of the two transition systems."""
import hashlib
import json
import re

def require(ok,why):
    if not ok:raise RuntimeError(why)

def actual(db,section,name):
    row=db.execute('SELECT sha,payload FROM owners WHERE module="otpu_vpu" AND section=? AND name=?',(section,name)).fetchone()
    require(row is not None,'Missing exact original '+section+':'+name)
    require(hashlib.sha256(row[1].encode()).hexdigest()==row[0],'Original owner digest differs')
    return json.loads(row[1])

def token(b):
    require(type(b)is int and b>=0 or type(b)is str and b in ('0','1','x','z'),'Invalid bit')
    return b

def uint(v):
    require(type(v)is str and v and set(v)<=set('01'),'Unresolved parameter')
    return int(v,2)

def buf(c):
    require(c['type']=='$buf' and set(c['parameters'])=={'WIDTH'},'Nonidentity buffer parameters')
    width=uint(c['parameters']['WIDTH']);p=c['connections']
    require(width>0 and set(p)=={'A','Y'} and c['port_directions']=={'A':'input','Y':'output'},'Buffer pins differ')
    require(len(p['A'])==len(p['Y'])==width and len(set(p['Y']))==width and all(type(b)is int for b in p['Y']),'Buffer width/driver differs')
    for v in p.values():
        for b in v:token(b)
    return dict(zip(p['Y'],p['A']))

class Original:
    def __init__(self,db):self.db=db;self.used={}
    def alias(self,n):return actual(self.db,'netnames',n)['bits']
    def producer(self,b):
        if type(b)is not int:return None
        rows=self.db.execute('SELECT owner,pin FROM drivers WHERE module="otpu_vpu" AND bit=?',(b,)).fetchall()
        require(len(rows)<=1,'Multiple original drivers')
        if not rows or rows[0][0].startswith('port:'):return None
        name,pin=rows[0];c=actual(self.db,'cells',name);require(pin in c['connections'] and b in c['connections'][pin] and c['port_directions'][pin]=='output','Original driver index differs')
        return name,c
    def canonical(self,b):
        token(b);seen=set()
        while type(b)is int:
            require(b not in seen,'Identity buffer cycle');seen.add(b);p=self.producer(b)
            if p is None or p[1]['type']!='$buf':break
            name,c=p;self.used[name]=c;b=buf(c)[b]
        return b

class Gold:
    def __init__(self,m):
        self.m=m;self.drivers={};self.used={}
        for n,p in m['ports'].items():
            if p['direction']=='input':
                for b in p['bits']:
                    require(type(b)is int and b not in self.drivers,'Gold input alias/driver');self.drivers[b]=None
        for name,c in m['cells'].items():
            require(set(c['connections'])==set(c['port_directions']),'Gold cell pin inventory differs')
            for pin,bs in c['connections'].items():
                for b in bs:token(b)
                if c['port_directions'][pin]=='output':
                    for b in bs:
                        require(type(b)is int and b not in self.drivers,'Gold driver overlap');self.drivers[b]=(name,c)
    def alias(self,n):return self.m['netnames'][n]['bits']
    def canonical(self,b):
        token(b);seen=set()
        while type(b)is int:
            require(b not in seen,'Gold identity buffer cycle');seen.add(b);p=self.drivers.get(b)
            if p is None or p[1]['type']!='$buf':break
            name,c=p;self.used[name]=c;b=buf(c)[b]
        return b

def conjunction(c):
    require(c['type']=='$logic_and' and set(c['parameters'])=={'A_SIGNED','B_SIGNED','A_WIDTH','B_WIDTH','Y_WIDTH'},'Scalar logic-and schema differs')
    p={n:uint(v) for n,v in c['parameters'].items()}
    require(p=={'A_SIGNED':0,'B_SIGNED':0,'A_WIDTH':1,'B_WIDTH':1,'Y_WIDTH':1},'Logic-and parameter widths/signedness differ')
    require(c['port_directions']=={'A':'input','B':'input','Y':'output'} and set(c['connections'])=={'A','B','Y'},'Logic-and pins differ')
    require(all(len(bs)==1 for bs in c['connections'].values()),'Logic-and vector geometry differs')
    return c['connections']

def coordinates(db,storage,gold,outputs,reference,gold_fields):
    o=Original(db);g=Gold(gold)
    fields={(f['unit'],f['field']):f for f in storage['fields']}
    sequence={f['field']:f['logical_width'] for f in storage['fields'] if f['unit']=='sequence'}
    require(len(sequence)==44 and sum(sequence.values())==676,'Complete sequence field map differs')
    command={'hc':240,'hf':8,'h_empty':1,'can_begin':1,'busy':1,'rdy':1,'o_cq_n':2,'begin_cmd':1,'nchunks':16,'nfill':16}
    expected={**{'out_sequence_o_'+n:w for n,w in sequence.items()},**{'out_command_'+n:w for n,w in command.items()}}
    require(outputs==expected and sum(outputs.values())==963,'Exact public observation vector differs')
    require({n:len(p['bits']) for n,p in gold['ports'].items() if p['direction']=='output'}==expected,'Actual gold public port set differs')
    direct={};state_relation={};gold_claimed=set()
    for port,w in expected.items():
        if port in ('out_command_begin_cmd','out_command_nchunks','out_command_nfill'):continue
        isseq=port.startswith('out_sequence_o_');name=port.removeprefix('out_sequence_o_') if isseq else port.removeprefix('out_command_')
        alias='cq_n' if name=='o_cq_n' else name
        # Actual source assignments are checked in addition to net aliases;
        # source initialization/typed layout are not inferred from this check.
        expression=alias if isseq else '('+alias+')'
        require(len(re.findall(r'\bassign\s+'+re.escape(port)+r'\s*=\s*'+re.escape(expression)+r'\s*;',reference))==1,'Exact gold output assignment differs '+port)
        ob=o.alias(alias);gb=g.alias(alias);pb=gold['ports'][port]['bits']
        require(len(ob)==len(gb)==len(pb)==w,'Actual observation width differs '+port)
        require([g.canonical(b) for b in pb]==[g.canonical(b) for b in gb],'Gold public output is not exact alias identity '+port)
        record={'original_alias':alias,'original_bits':ob,'gold_alias_bits':gb,'gold_output_bits':pb,
                'original_normalized_bits':[o.canonical(b) for b in ob],
                'gold_normalized_bits':[g.canonical(b) for b in gb],'behavioral_equality_proven':False}
        if isseq or name=='o_cq_n':
            f=fields[('sequence',name) if isseq else ('command','cq_n')]
            require(f['classification']=='physical_DFF_Q' and ob==f['original_bits'],'Original state coordinate differs')
            require(gb==gold_fields[alias],'Gold alias differs from complete proven state map')
            require(len(set(gb))==w,'Gold state field aliases itself')
            for original,native in zip(ob,gb):
                require(original not in state_relation and native not in gold_claimed,'Overlapping observation state coordinates');state_relation[original]=native;gold_claimed.add(native)
            record['classification']='selected_state_coordinate'
        else:record['classification']='actual_combinational_alias_coordinate_only'
        direct[port]=record
    require(sum(len(r['original_bits']) for r in direct.values())==930 and len(state_relation)==678,'Direct observation/state coordinate totals differ')
    # Search all actual original scalar ANDs. Same-expression duplicates are
    # retained as separate actual owners; none is guessed to be the unique
    # procedural branch consumer. That use-site proof remains explicit work.
    want=sorted([o.canonical(o.alias('can_begin')[0]),o.canonical(o.alias('en')[0])],key=str)
    matches=[]
    for name,payload in db.execute('SELECT name,payload FROM owners WHERE module="otpu_vpu" AND section="cells"'):
        c=json.loads(payload)
        if c['type']!='$logic_and':continue
        # Only scalar candidates can implement this actual one-bit expression.
        if any(len(c['connections'].get(p,[]))!=1 for p in ('A','B','Y')):continue
        values=sorted([o.canonical(c['connections'][p][0]) for p in ('A','B')],key=str)
        if values==want:conjunction(c);matches.append({'name':name,'owner':actual(db,'cells',name)})
    require(matches,'No actual original begin conjunction')
    pb=g.canonical(gold['ports']['out_command_begin_cmd']['bits'][0]);producer=g.drivers.get(pb)
    require(producer is not None,'Gold begin conjunction missing');gp=conjunction(producer[1])
    require(sorted([g.canonical(gp[p][0]) for p in ('A','B')],key=str)==sorted([g.canonical(g.alias('can_begin')[0]),g.canonical(g.alias('en')[0])],key=str),'Gold begin operands differ')
    require(reference.count('assign out_command_begin_cmd=(can_begin && en);')==1,'Gold begin source changed')
    return {'direct_observations':direct,'direct_coordinate_bits':930,'selected_state_observation_bits':678,
       'state_coordinate_pairs':[[a,b] for a,b in sorted(state_relation.items())],
       'begin_expression':{'original_owners':matches,'gold_owner':producer[0],'gold_cell':producer[1],
          'same_scalar_expression_schema':True,'guard_use_site_binding_proven':False,'operand_behavioral_equality_proven':False},
       'original_identity_buffers':o.used,'gold_identity_buffers':g.used,
       'unresolved_geometry_bits':32,'pending_geometry_outputs':['out_command_nchunks','out_command_nfill'],
       'public_observation_bridge_complete':False,'transition_equivalence_proven':False,'physical_layout_proven':False}
