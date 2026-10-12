"""Stream original root owners into SQLite; no cone/proof/state rewriting."""
import collections,hashlib,json,re,sqlite3,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import require,module_hashes,global_directives,tokens
from audit_sparkle_rtlil_roundtrip import Owners
from audit_sparkle_specialized_hierarchy import parameter_types,ast_top_metadata
from child_ast import bind_child_parameters,bind_child_ports
SOURCES=['rtl/top/otpu_pkg.sv','rtl/vpu/otpu_fp.sv','rtl/vpu/otpu_fpipe.sv','rtl/vpu/otpu_se_comp.sv','rtl/vpu/otpu_vtree.sv','rtl/vpu/otpu_se_tail.sv','rtl/vpu/otpu_vpu.sv']
EXPECTED_MODULES={'otpu_delay','otpu_fmul','otpu_fadd','otpu_fadd2','otpu_fmadd','otpu_fmma','otpu_se_comp','otpu_vtree','otpu_se_tail','otpu_vpu'}
PARAMS={'LANES':8,'CL':2,'WBUF':1,'HAS_SE':1,'SID':0}

def safe(p):
    s=str(p);require(re.fullmatch(r'[A-Za-z0-9_./-]+',s),'Unsafe tool path');return s

def package_inventory(path):
    """Exact package-only compilation unit; never discard package declarations.

    These two original units have no external preamble or trailing declarations.
    Preserve every token, including attributes, imports and in-package macros,
    plus directive line boundaries. Unsupported unit shapes fail closed.
    """
    located=list(tokens(Path(path),with_lines=True));body=[t for _,t in located]
    require(len(body)>=4 and body[0]=='package' and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*',body[1]) and body[2]==';','Unsupported package declaration')
    name=body[1]
    require(body.count('package')==body.count('endpackage')==1 and not any(t in ('module','endmodule') for t in body),'Mixed/nested package unit')
    end=body.index('endpackage');require(body[end+1:] in ([],[':',name]),'Trailing package-unit tokens')
    directives=[]
    for i,(line,token) in enumerate(located):
        if token=='`':
            parts=[t for ln,t in located[i:] if ln==line]
            require(len(parts)>1 and parts[-1]!='\\','Unsupported package directive continuation')
            directives.append(parts)
    imports=[]
    for i,t in enumerate(body):
        if t=='import':
            require(';' in body[i+1:],'Unterminated package import')
            stop=body.index(';',i+1);imports.append(body[i:stop+1])
    return name,{'source':str(path),'tokens':body,'token_sha256':hashlib.sha256(canonical(body).encode()).hexdigest(),'directives':directives,'imports':imports}

def source_inventory(paths):
    require([str(Path(p).resolve().relative_to(ROOT)) for p in paths]==SOURCES,'Exact source compilation order differs')
    definitions={};packages={};contexts={};records=[]
    for p in paths:
        text=Path(p).read_text();require(not re.search(r'`\s*(?:include|define|undef)\b',text),'Unresolved preprocessor dependency')
        if str(Path(p).resolve().relative_to(ROOT)) in SOURCES[:2]:
            name,package=package_inventory(p);require(name not in packages,'Duplicate package');packages[name]=package
            records.append({'path':str(p),'directives':package['directives'],'module_names':[],'package_names':[name]})
            require(not package['imports'],'Unexpected import dependency in original package')
            continue
        names=module_hashes(Path(p));directives,incoming=global_directives(Path(p));params=parameter_types(Path(p))
        for name,h in names.items():
            require(name not in definitions,'Duplicate source module');definitions[name]={'source':str(p),'module_sha256':h,'parameter_types':params[name]};contexts[name]=incoming[name]
        stripped=re.sub(r'//[^\n]*|/\*.*?\*/','',text,flags=re.S)
        require(not re.search(r'\b(?:package|endpackage)\b',stripped),'Package in module-only compilation unit')
        require(set(re.findall(r'\bimport\s+(\w+)\s*::',stripped))<={'otpu_pkg','otpu_fp'},'Unexpected imported package')
        records.append({'path':str(p),'directives':directives,'module_names':sorted(names)})
    require(set(definitions)==EXPECTED_MODULES and set(packages)=={'otpu_pkg','otpu_fp'},'Exact original definition closure differs')
    return {'definitions':definitions,'packages':packages,'contexts':contexts,'compilation_units':records}

def extraction(paths,il,json_path):
    require(len(paths)==len(SOURCES),'Missing source compilation unit')
    flags=['--no-proc','--keep-hierarchy','--dump-ast','--top','otpu_vpu','-D','SYNTHESIS','-D','YOSYS']
    for name in sorted(EXPECTED_MODULES-{'otpu_vpu'}):flags+=['--blackboxed-module',name]
    flags+=['-GLANES=8','-GCL=2','-GWBUF=1','-GHAS_SE=1']
    return ('read_slang '+' '.join(flags+[safe(p) for p in paths])+'\nwrite_rtlil '+safe(il)+
            '\nproc -noopt -norom\nwrite_json '+safe(json_path)+'\n')

def valid(bits):
    require(type(bits)is list and all(type(b)is int and b>=0 or type(b)is str and b in ('0','1','x','z') for b in bits),'Invalid signal bit token')

def bits_parameter(value):
    require(type(value)is str and value and set(value)<={'0','1'},'Unresolved binary parameter')
    return int(value,2)

def sequential(cell):
    """Exact primitive contract for noopt proc_dff; no guessed storage cells."""
    kind=cell['type']
    if kind=='$dff':
        p=cell['parameters'];c=cell['connections'];d=cell['port_directions']
        require(set(p)=={'WIDTH','CLK_POLARITY'} and d=={'CLK':'input','D':'input','Q':'output'},'DFF schema differs')
        width=bits_parameter(p['WIDTH']);polarity=bits_parameter(p['CLK_POLARITY'])
        require(width>0 and polarity in (0,1) and len(c['D'])==len(c['Q'])==width and len(c['CLK'])==1,'DFF dimensions differ')
        return {'Q':c['Q'],'D':c['D'],'clock':c['CLK'],'polarity':polarity}
    require(not any(x in kind.lower() for x in ('dff','latch','$ff','$sr')),'Unsupported sequential primitive '+kind)
    return None

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))

def root_ast_contract(root,metadata,declared):
    expected_types={'LANES':'int','CL':'int','SID':'int','WBUF':'bit','HAS_SE':'bit'}
    require(declared==expected_types,'Original root parameter declarations differ')
    require(set(metadata['parameters'])==set(PARAMS),'AST full root parameter vector differs')
    effective={}
    for name,value in PARAMS.items():
        p=metadata['parameters'][name];kind=expected_types[name];width=32 if kind=='int' else 1
        require(p['type']==kind and p['width']==width and p['signed']==(kind=='int') and p['offset']==0 and p['upto']==0,'AST evaluated root parameter type differs')
        require(len(p['bits'])==width and bits_parameter(p['bits'])==value,'AST evaluated root parameter value differs')
        effective[name]=p['bits']
    if 'parameter_default_values' in root:
        require(root['parameter_default_values']==effective,'Root JSON/AST parameter disagreement')
    require(set(root['ports'])==set(metadata['ports']),'Root JSON/AST port inventory differs')
    unresolved=[]
    for name,p in root['ports'].items():
        a=metadata['ports'][name];require(p['direction']==a['direction'],'Root JSON/AST port direction differs')
        if 'width' in a:
            require(p['width']==a['width'],'Root JSON/AST port width differs')
            if 'unpacked_dimensions' not in a:
                for k in ('offset','upto','signed'):require(int(p.get(k,0))==int(a[k]),'Root JSON/AST port type differs')
        else:
            unresolved.append({'port':name,'ast_type':a['type'],'declared_type':a['declared_type'],'direction':a['direction'],'actual_json_width':p['width'],'status':'inventory_only_typed_layout_unresolved'})
    root['evaluated_parameter_values']=effective;root['typed_ast_metadata']=metadata
    root['unresolved_ast_port_geometry']=unresolved;root['complete_typed_port_geometry']=not unresolved

class Store:
    def __init__(self,path):
        require(not Path(path).exists(),'Fresh inventory database required');self.db=sqlite3.connect(path)
        try:
            self.db.executescript('''PRAGMA journal_mode=DELETE; PRAGMA cache_size=-8192;
CREATE TABLE owners(module TEXT, section TEXT, name TEXT, sha TEXT, payload TEXT,PRIMARY KEY(module,section,name));
CREATE TABLE drivers(module TEXT,bit INTEGER,owner TEXT,pin TEXT,PRIMARY KEY(module,bit));
CREATE TABLE uses(module TEXT,bit INTEGER,owner TEXT,pin TEXT,position INTEGER);
CREATE INDEX uses_bit ON uses(module,bit);
CREATE TABLE qd(module TEXT,q INTEGER,d TEXT,cell TEXT,clock TEXT,polarity INTEGER,PRIMARY KEY(module,q));
CREATE TABLE initials(module TEXT,bit INTEGER,value TEXT,alias TEXT);
CREATE TABLE aliases(module TEXT,bit INTEGER,name TEXT,position INTEGER);
CREATE INDEX alias_bit ON aliases(module,bit);
CREATE TABLE literals(module TEXT,owner TEXT,pin TEXT,position INTEGER,value TEXT);
''')
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def owner(self,module,section,name,value):
        encoded=canonical(value);self.db.execute('INSERT INTO owners VALUES(?,?,?,?,?)',(module,section,name,hashlib.sha256(encoded.encode()).hexdigest(),encoded))
    def drive(self,module,bits,owner,pin):
        require(len(set(bits))==len(bits) and all(type(b)is int for b in bits),'Aliased/constant output driver')
        try:self.db.executemany('INSERT INTO drivers VALUES(?,?,?,?)',[(module,b,owner,pin) for b in bits])
        except sqlite3.IntegrityError as e:raise RuntimeError('Duplicate input/cell driver') from e
    def signals(self,module,bits,owner,pin):
        valid(bits)
        self.db.executemany('INSERT INTO uses VALUES(?,?,?,?,?)',[(module,b,owner,pin,i) for i,b in enumerate(bits) if type(b)is int])
        self.db.executemany('INSERT INTO literals VALUES(?,?,?,?,?)',[(module,owner,pin,i,b) for i,b in enumerate(bits) if type(b)is str])
    def inventory(self,path,declared,root_metadata=None):
        modules={};top_seen=set()
        with Path(path).open() as f:
            reader=Owners(f)
            for top in reader.object():
                require(top not in top_seen,'Repeated top owner');top_seen.add(top)
                if top=='creator':require(type(reader.value())is str,'Creator malformed');continue
                require(top=='modules','Unknown top graph field')
                for name in reader.object():
                    require(name not in modules,'Repeated module');meta={'counts':collections.Counter(),'ports':{},'children':[],'memories':{},'state_bits':0};modules[name]=meta;seen=set()
                    for section in reader.object():
                        require(section not in seen,'Repeated module section');seen.add(section)
                        require(section in {'attributes','parameter_default_values','ports','cells','netnames','memories'},'Unlowered/unknown graph section '+section)
                        if section in {'attributes','parameter_default_values'}:
                            value=reader.value();require(type(value)is dict,'Invalid module metadata');self.owner(name,section,'',value);meta[section]=value
                            require('init' not in value,'Unsupported module initializer');continue
                        for owner in reader.object():
                            value=reader.value();require(type(value)is dict,'Invalid graph owner');self.owner(name,section,owner,value);meta['counts'][section]+=1
                            require('init' not in value,'Unsupported direct owner initializer')
                            attributes=value.get('attributes',{});require(type(attributes)is dict,'Invalid owner attributes')
                            require(section=='netnames' or 'init' not in attributes,'Unsupported owner initializer attribute')
                            if section=='ports':
                                require(value['direction'] in ('input','output'),'Unsupported original direction');valid(value['bits']);require('init' not in value.get('attributes',{}),'Unsupported port initializer')
                                meta['ports'][owner]={k:v for k,v in value.items() if k in ('direction','bits','offset','upto','signed')};meta['ports'][owner]['width']=len(value['bits'])
                                if value['direction']=='input':self.drive(name,value['bits'],'port:'+owner,'')
                                else:self.signals(name,value['bits'],'port:'+owner,'')
                            elif section=='netnames':
                                valid(value['bits']);self.db.executemany('INSERT INTO aliases VALUES(?,?,?,?)',[(name,b,owner,i) for i,b in enumerate(value['bits']) if type(b)is int])
                                init=value.get('attributes',{}).get('init')
                                if init is not None:
                                    require(type(init)is str and len(init)==len(value['bits']) and set(init)<=set('01xz'),'Invalid initializer encoding')
                                    for bit,digit in zip(value['bits'],reversed(init)):
                                        if digit in '01':
                                            require(type(bit)is int or bit==digit,'Initializer contradicts constant')
                                            if type(bit)is int:self.db.execute('INSERT INTO initials VALUES(?,?,?,?)',(name,bit,digit,owner))
                            elif section=='memories':
                                require(type(value['width'])is int and value['width']>0 and type(value['size'])is int and value['size']>0 and type(value['start_offset'])is int,'Invalid memory geometry')
                                meta['memories'][owner]={'width':value['width'],'size':value['size'],'start_offset':value['start_offset'],'logical_bits':value['width']*value['size']}
                            else:
                                require('init' not in value.get('attributes',{}),'Unsupported cell initializer')
                                conn=value['connections'];directions=value['port_directions'];require(set(conn)==set(directions),'Cell pin inventory differs')
                                for pin,bits in conn.items():
                                    valid(bits);require(directions[pin] in ('input','output'),'Unsupported cell pin direction')
                                    if directions[pin]=='output':self.drive(name,bits,owner,pin)
                                    else:self.signals(name,bits,owner,pin)
                                state=sequential(value)
                                if state:
                                    meta['state_bits']+=len(state['Q'])
                                    for q,d in zip(state['Q'],state['D']):self.db.execute('INSERT INTO qd VALUES(?,?,?,?,?,?)',(name,q,canonical(d),owner,canonical(state['clock']),state['polarity']))
                                kind=value['type'];meta['counts']['cell:'+kind]+=1
                                if not kind.startswith('$') or kind.startswith('$paramod'):
                                    meta['children'].append({'cell':owner,'type':kind,'parameters':value['parameters'],'connections':conn,'port_directions':directions,'attributes':value.get('attributes',{})})
                    require({'attributes','ports','cells','netnames'}<=seen,'Missing mandatory module section')
                    self.db.commit()
            reader.whitespace();require(reader.eof and reader.pos==len(reader.buf),'Trailing graph JSON')
        require(top_seen=={'creator','modules'},'Missing complete graph metadata')
        self.audit_initials()
        roots=[n for n,m in modules.items() if bits_parameter(m.get('attributes',{}).get('top','0'))==1]
        require(roots==['otpu_vpu'],'Exact original root absent/ambiguous')
        root=modules['otpu_vpu'];require(bits_parameter(root.get('attributes',{}).get('blackbox','0'))==0 and root['counts'].get('cells',0)>0,'Root was blackboxed or empty');parameters=root.get('parameter_default_values',{})
        if root_metadata is not None:root_ast_contract(root,root_metadata,declared['otpu_vpu']['parameter_types'])
        else:require(set(parameters)==set(PARAMS) and all(bits_parameter(parameters[n])==v for n,v in PARAMS.items()),'Actual effective root parameters differ')
        require(root['ports']['clk']['direction']=='input' and root['ports']['clk']['width']==1,'Root clock differs')
        for n,m in modules.items():
            if n=='otpu_vpu':continue
            require(bits_parameter(m.get('attributes',{}).get('blackbox','0'))==1 and m['counts'].get('cells',0)==0,'Unexpected elaborated child body')
        if root_metadata is not None:
            require(len(root['children'])==23 and len({c['cell'] for c in root['children']})==23,'Exact original production child occurrence count differs')
            require({c['cell'] for c in root['children']}==set(root_metadata['direct_children']),'Complete AST/JSON direct child occurrence inventory differs')
        for child in root['children']:
            require(child['type'] in modules,'Child declaration absent');definition=modules[child['type']]
            original=definition.get('attributes',{}).get('hdlname',child['type'])
            require(original in declared and original!='otpu_vpu','Unknown/recursive original child declaration')
            child['original_definition']=original;child['definition_identity']=declared[original]
            if root_metadata is not None:
                bind_child_ports(child,definition['ports'],root_metadata['direct_children'][child['cell']])
                bind_child_parameters(child,definition,root_metadata['direct_children'][child['cell']],declared[original]['parameter_types'])
            else:
                require(set(child['connections'])==set(definition['ports']),'Missing/extra original child pin')
                for pin,bits in child['connections'].items():
                    require(child['port_directions'][pin]==definition['ports'][pin]['direction'] and len(bits)==definition['ports'][pin]['width'],'Specialized child complete ABI differs')
                effective={**definition.get('parameter_default_values',{}),**child['parameters']}
                require(set(effective)==set(declared[original]['parameter_types']),'Complete original child parameter inventory differs')
                for v in effective.values():require(type(v)is str and v and set(v)<=set('01'),'Unresolved child parameter')
                child['effective_parameters']=effective
        for n,m in modules.items():
            m['counts']=dict(m['counts']);m['undriven_used_bits']=self.db.execute('SELECT count(DISTINCT u.bit) FROM uses u LEFT JOIN drivers d ON d.module=u.module AND d.bit=u.bit WHERE u.module=? AND d.bit IS NULL',(n,)).fetchone()[0]
        self.db.commit();return modules
    def audit_initials(self):
        bad=self.db.execute('SELECT module,bit FROM initials GROUP BY module,bit HAVING count(DISTINCT value)>1 LIMIT 1').fetchone();require(bad is None,'Conflicting initializer aliases')
        bad=self.db.execute('SELECT i.module,i.bit FROM initials i LEFT JOIN qd q ON q.module=i.module AND q.q=i.bit WHERE q.q IS NULL LIMIT 1').fetchone();require(bad is None,'Defined net initializer outside actual DFF-Q; memory initialization must remain in actual memory cells')

CONTROL_FIELDS={
 'command':{'cq_n':2,'cq_h':1,'cq0':240,'cq1':240},
 'sequence':dict([('issuing',1),('red_act',1),('filling',1),('flushing',1),('ew_n',7),('last_tap',4),('tag',8),('dst',20),('a',20),('b',20),('rows',16),('cols',16),('drs',16),('ars',16),('brs',16),('func',8),('bmode',2),('imm',32),('nslots',4),('nch',16),('ir',16),('ic',16),('ch',16),('a_row',20),('b_row',20),('d_row',20),('nfill',16),('oc_a',20),('od_a',20),('od_sc',1),('od_one',1),('wr_row',20),('rows_done',16),('rdb',1),('fl',16),('mx_have',1),('mx_run',32),('mx_ri',17),('done_i',1),('pf_u',1),('st_c',1),('st_frz',32),('pf_frz',32),('mi',115)]),
 'write_buffer':{**{f'wq{i}':425 for i in range(4)},'wh':2,'wt':2,'wn':3,'hen':8,'hrot':3,'en_q':1,'en_r':1,'done_r':1,'dpend':1},
 'stream':dict([('ss_rq',1),('ss_act',1),('s_init',1),('sen_q',1),('sen',1),('s1_fk',3),('s_fk',3),('s1_fi',5),('s1_fd',256),('s_fi',5),('s_fd',256),('s1_in_v',1),('s1_in_d',256),('s_in_v',1),('s_in_d',256),('s_cfg',23),('q_cap',1),('q_rl',1),('q_sub',8),('q_pd',256),('kt',3),('kh',3)]+[(f'kq{i}',1) for i in range(8)])}

def candidate_name(unit,name):
    if unit=='command' and name.startswith('cq') and name[-1:] in ('0','1'):return 'cq['+name[-1]+']'
    if unit=='write_buffer':
        return 'done' if name=='done_r' else 'dpend' if name=='dpend' else 'g_wbuf.'+('wq['+name[2:]+']' if name.startswith('wq') else name)
    if unit=='stream' and (name.startswith('s1_') or name in ('sen_q','kt','kh') or name.startswith('kq')):
        return 'g_se.kq' if name.startswith('kq') else 'g_se.'+name
    return name

def candidates(store):
    require({u:sum(fs.values()) for u,fs in CONTROL_FIELDS.items()}=={'command':483,'sequence':676,'write_buffer':1722,'stream':1350},'Independent logical inventory differs')
    clockrow=store.db.execute("SELECT payload FROM owners WHERE module='otpu_vpu' AND section='ports' AND name='clk'").fetchone()
    require(clockrow is not None,'Root clock owner missing');clock=json.loads(clockrow[0])['bits']
    report={'candidate_logical_bits':4231,'partition_proven':False,'fields':[],'unresolved':[]};claimed={}
    for unit,fields in CONTROL_FIELDS.items():
        for field,width in fields.items():
            name=candidate_name(unit,field);row=store.db.execute("SELECT payload FROM owners WHERE module='otpu_vpu' AND section='netnames' AND name=?",(name,)).fetchone()
            record={'unit':unit,'field':field,'logical_width':width,'exact_alias':name,'classification':'unresolved'}
            coordinates=[]
            if row:
                net=json.loads(row[0]);bits=net['bits']
                if unit=='stream' and field.startswith('kq'):
                    require(len(bits)==8,'Original packed kind FIFO width differs');bits=[bits[int(field[2:])]]
                if len(bits)==width and all(type(b)is int for b in bits):
                    qs={r[0] for r in store.db.execute("SELECT q FROM qd WHERE module='otpu_vpu' AND q IN ("+','.join('?' for _ in bits)+')',bits)}
                    if set(bits)<=qs:
                        # Inventory retains original coordinates; lane permutation
                        # must be established by later declared-range mapping.
                        require(all(c==canonical(clock) and p==1 for c,p in store.db.execute("SELECT clock,polarity FROM qd WHERE module='otpu_vpu' AND q IN ("+','.join('?' for _ in bits)+')',bits)),'Candidate storage clock/polarity differs')
                        record.update(classification='physical_DFF_Q',original_bits=bits,declared_offset=net.get('offset'),declared_upto=net.get('upto'))
                        coordinates=[('Q',b) for b in bits]
                    else:record.update(classification='wire_not_complete_Q',original_bits=bits)
                else:record['actual_alias_width']=len(bits)
            if not coordinates:
                # Exact array word backed by original memory, never guessed from
                # a same-width wire or a broad suffix match.
                match=re.fullmatch(r'(.+)\[(\d+)\]',name)
                if match:
                    mr=store.db.execute("SELECT payload FROM owners WHERE module='otpu_vpu' AND section='memories' AND name=?",(match[1],)).fetchone()
                    if mr:
                        memory=json.loads(mr[0]);word=int(match[2]);start=memory['start_offset']
                        require(memory['width']==width and start<=word<start+memory['size'],'Original memory word geometry mismatch')
                        record.update(classification='original_memory_word',memory=match[1],word=word)
                        coordinates=[('memory',match[1],word,b) for b in range(width)]
            if coordinates:
                require(len(set(coordinates))==width,'Aliased candidate storage within field')
                for coordinate in coordinates:
                    require(coordinate not in claimed,'Overlapping selected original storage');claimed[coordinate]=(unit,field)
            else:report['unresolved'].append(unit+'.'+field)
            report['fields'].append(record)
    report['resolved_storage_bits']=len(claimed);report['complete_candidate_storage_identification']=not report['unresolved']
    report['lane_order_bridge_proven']=False
    return report
