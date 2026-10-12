import json
from pathlib import Path
base=Path('build/sparkle/formal_mxu_memory_control/128_4_4_1024_8_2_16')
with (base/'cut.json').open() as f:old=json.load(f)
with (base/'mapped.json').open() as f:new=json.load(f)
def meta(cell):
    result={k:v for k,v in cell.items() if k!='connections'}
    if 'attributes' in result:result['attributes']={k:v for k,v in result['attributes'].items() if k!='src'}
    return result
result={}
for side in ('gold','gate'):
    changes=[]
    for name,c in old['modules'][side]['cells'].items():
        if c['type'].startswith('$mem'):continue
        d=new['modules'][side]['cells'].get(name)
        if d is None:changes.append({'name':name,'missing':True});continue
        a,b=meta(c),meta(d)
        if a!=b:
            changes.append({'name':name,'type':c['type'],'differences':{k:{'old':a.get(k),'new':b.get(k)} for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}})
    result[side]={'count':len(changes),'differences':changes}
print(json.dumps(result,indent=2))
