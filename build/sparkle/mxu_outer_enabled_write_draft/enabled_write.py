"""Actual enabled write event, with original mk wire identities as observations."""
import copy
import re
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_observation_queries_draft'),
             str(ROOT/'build/sparkle/mxu_outer_observation_diagnostics_draft')]
from observation_queries import qualify_coordinates,PROBE
from dot_initial_store import need


def lane_rows(rows,lane):
    need(type(lane)is int and 0<=lane<8,'invalid actual write lane')
    def select(name,lo,width):
        selected=[r for r in rows if r['semantic_port']==name and lo<=r['bit_index_lsb']<lo+width]
        need([r['bit_index_lsb'] for r in selected]==list(range(lo,lo+width)),'complete actual lane coordinates missing')
        need(all(r['owner']=={'kind':'top','port':name} for r in selected),'write boundary owner differs')
        return selected
    return select('t_wdata',32*lane,32)+select('t_wen',lane,1)


def mk_rows(original,pair,manifest):
    mapping={};inverse={}
    for name,cell in original['cells'].items():
        target=pair['cells']['gold:'+name]
        need({k:v for k,v in cell.items() if k!='connections'}==
             {k:v for k,v in target.items() if k!='connections'},'gold source cell metadata differs')
        need(cell['connections'].keys()==target['connections'].keys(),'gold complete pin inventory differs')
        for pin,bits in cell['connections'].items():
            other=target['connections'][pin];need(len(bits)==len(other),'gold pin width differs')
            for old,new in zip(bits,other):
                if type(old)is str:need(old==new,'literal unknown occurrence changed');continue
                need(type(new)is int and (old not in mapping or mapping[old]==new) and
                    (new not in inverse or inverse[new]==old),'original wire identity/fanout changed')
                mapping[old]=new;inverse[new]=old
    def remap(bit):
        need(type(bit)is str or bit in mapping,'original mk wire lacks actual paired owner')
        return bit if type(bit)is str else mapping[bit]
    memory=manifest['original_memory_inventory']['mk']
    need(memory['width']==32 and memory['size']==4,'actual mk geometry differs')
    reads={}
    for row in manifest['expansion']['reads']:
        for use in row['occurrences']:
            if use['memory']=='mk':
                key=use['read_port'],use['bit_lsb'];need(key not in reads,'duplicate mk read coordinate')
                reads[key]=row['original_read_bit']
    count=len(memory['read_address_vectors'])
    need(set(reads)=={(p,b) for p in range(count) for b in range(32)},'incomplete actual mk read ports')
    out=[];ports=[]
    for port,address in enumerate(memory['read_address_vectors']):
        need(len(address)==32,'full original mk address missing')
        data=[reads[port,b] for b in range(32)]
        record={'port':port,'source_address':address,'source_read':data,
                'paired_address':[remap(b) for b in address],'paired_read':[remap(b) for b in data]}
        ports.append(record)
        for kind,source in [('address',address),('read',data)]:
            for i,bit in enumerate(source):
                paired=remap(bit)
                out.append({'semantic_port':f'mk{port}_{kind}','bit_index_lsb':i,
                    'owner':{'kind':'original_mk_display','read_port':port,'vector':kind},
                    'gold':paired,'gate':paired,'gold_source':bit,'gate_source':bit})
    return out,ports


def relevant_ports(index,ports):
    cells,_=index.cone(0,66)
    driven=set()
    from ownership_cones import cell_pins
    for name,indices in cells.items():
        cell=index.projected(name,indices);_,outputs=cell_pins(cell)
        driven.update(b for pin in outputs for b in cell['connections'][pin] if type(b)is int)
    return [r['port'] for r in ports if driven.intersection(r['paired_read'])]


def add_aliases(module,rows,lane,ports):
    need(len(rows)>=33,'incomplete enabled-write vector')
    aliases={'gold_data':[r['gold'] for r in rows[:32]],'native_data':[r['gate'] for r in rows[:32]],
        'gold_enable':[rows[32]['gold']],'native_enable':[rows[32]['gate']]}
    for record in ports:
        for kind in ('address','read'):aliases[f"mk{record['port']}_{kind}"]=record['paired_'+kind]
    for name,bits in aliases.items():
        need(name not in module['ports'] and name not in module['netnames'],'target display namespace collision')
        module['ports'][name]={'direction':'output','bits':list(bits)}
    return aliases


def script(path,aliases):
    need(not any(c in str(path) for c in ' \n;"\\'),'unsafe event query path')
    need(set(('gold_data','native_data','gold_enable','native_enable'))<=set(aliases),'event query observations missing')
    return (f'read_json {path}\nhierarchy -top paired\n'
        'sat -enable_undef -set-def-inputs -set gold_enable 1 -set-any-undef gold_data -show-inputs '+
        ' '.join('-show '+name for name in aliases)+' -timeout 180\n')


def decode(text,aliases):
    result={}
    for name,bits in aliases.items():
        rows=re.findall(r'^\s*\\'+re.escape(name)+r'\s+\S+\s+\S+\s+([01xz]+)\s*$',text,re.M)
        need(len(rows)==1 and len(rows[0])==len(bits),'missing complete event display '+name)
        value=rows[0];defined=set(value)<=set('01')
        result[name]={'bits_msb_first':value,'defined':defined,'unsigned_value':int(value,2) if defined else None}
    need(result['gold_enable']['bits_msb_first']=='1' and not result['gold_data']['defined'],
        'witness lacks actual enabled undefined write')
    return result
