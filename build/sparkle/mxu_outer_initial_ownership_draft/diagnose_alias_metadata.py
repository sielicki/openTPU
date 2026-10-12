import json
from pathlib import Path
base=Path('build/sparkle/formal_mxu_memory_control/128_4_4_1024_8_2_16')
with (base/'cut.json').open() as f:old=json.load(f)
with (base/'mapped.json').open() as f:new=json.load(f)
def meta(net):
    result={k:v for k,v in net.items() if k!='bits'}
    if 'attributes' in result:result['attributes']={k:v for k,v in result['attributes'].items() if k!='src'}
    return result
result={}
for side in ('gold','gate'):
    a=old['modules'][side]['netnames'];b=new['modules'][side]['netnames']
    rows=[]
    for name in sorted(a.keys()&b.keys()):
        x,y=meta(a[name]),meta(b[name])
        if x!=y:rows.append({'name':name,'old':x,'new':y,'old_width':len(a[name]['bits']),'new_width':len(b[name]['bits'])})
    result[side]={'changed':rows,'removed':[{'name':n,'metadata':meta(a[n]),'width':len(a[n]['bits'])} for n in sorted(a.keys()-b.keys())],
                  'added':[{'name':n,'metadata':meta(b[n]),'width':len(b[n]['bits'])} for n in sorted(b.keys()-a.keys())]}
print(json.dumps(result,indent=2))
