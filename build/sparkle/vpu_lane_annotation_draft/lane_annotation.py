"""Exact single-register hint correspondence, never generic attribute stripping."""
import hashlib,json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import require
from audit_sparkle_rtlil_roundtrip import Owners
from check_sparkle_se_tail_assertion_emission import clean_location_attributes
LANES='otpu_vpu_lanes_sparkle'
ATTRIBUTE=['(','*','keep','=','"true"',',','shreg_extract','=','"no"','*',')']
DECLARATION=['logic','[','32',':','0',']','meta_slot0_6','=',"33'h0",';']

def exact_annotation(raw,annotated):
    raw=list(raw);annotated=list(annotated);needle=ATTRIBUTE+DECLARATION
    hits=[i for i in range(len(annotated)-len(needle)+1) if annotated[i:i+len(needle)]==needle]
    require(len(hits)==1,'Exact single meta_slot0_6 annotation missing/duplicated')
    i=hits[0];without=annotated[:i]+annotated[i+len(ATTRIBUTE):]
    require(without==raw,'Other module token/attribute/initializer difference')
    require(sum(raw[j:j+len(DECLARATION)]==DECLARATION for j in range(len(raw)))==1,'Original initialized33-bit declaration missing')
    return {'register':'meta_slot0_6','width':33,'initializer':"33'h0",'added_attributes':{'keep':'true','shreg_extract':'no'},'all_other_tokens_identical':True}

def owner(module,category,name,value,annotated):
    canonical=clean_location_attributes(value)
    if module==LANES and category=='netnames' and name=='meta_slot0_6':
        require(len(value['bits'])==33 and len(set(value['bits']))==33 and all(type(b)is int for b in value['bits']),
                'Annotated register exact bits differ')
        attrs=canonical.get('attributes',{})
        require(attrs.get('init')=='0'*33,'Annotated register actual initialization differs')
        if annotated:
            require(attrs.get('keep')=='true' and attrs.get('shreg_extract')=='no','Actual graph hint values differ')
            del attrs['keep'];del attrs['shreg_extract']
        else:require('keep' not in attrs and 'shreg_extract' not in attrs,'Raw register unexpectedly already annotated')
    return canonical

def graph_inventory(path,annotated):
    result={};seen=set();target_count=0
    with Path(path).open() as f:
        r=Owners(f)
        for top in r.object():
            require(top not in seen,'Duplicate graph top field');seen.add(top)
            if top=='creator':require(type(r.value())is str,'Invalid creator');continue
            require(top=='modules','Unsupported graph top field')
            for module in r.object():
                require(module not in result,'Duplicate graph module');groups={};qd={};target_bits=None
                for category in r.object():
                    require(category not in groups and category in {'attributes','parameter_default_values','ports','cells','netnames','memories'},'Unknown/repeated graph category')
                    if category in {'attributes','parameter_default_values'}:
                        value=r.value();groups[category]={k:v for k,v in value.items() if k!='src'} if category=='attributes' else value;continue
                    entries={}
                    for name in r.object():
                        require(name not in entries,'Duplicate graph owner');value=r.value()
                        if module==LANES and category=='netnames' and name=='meta_slot0_6':target_count+=1;target_bits=value['bits']
                        if category=='cells' and value['type']=='$dff':
                            c=value['connections'];require(len(c['Q'])==len(c['D'])==int(value['parameters']['WIDTH'],2),'Actual DFF width differs')
                            for q,d in zip(c['Q'],c['D']):require(type(q)is int and q not in qd,'Duplicate/constant actual Q');qd[q]=d
                        cleaned=owner(module,category,name,value,annotated)
                        entries[name]=hashlib.sha256(json.dumps(cleaned,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                    groups[category]=entries
                if module==LANES:require(len(qd)==1255 and target_bits is not None and set(target_bits)<=set(qd),'Complete local lane state/annotated target differs')
                result[module]={'groups':groups,'actual_qd':qd}
        r.whitespace();require(r.eof and r.pos==len(r.buf),'Trailing graph JSON')
    require(seen=={'creator','modules'} and target_count==1,'Missing actual top/annotation owner')
    return result
