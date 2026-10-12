import collections,json
from pathlib import Path
p=Path('build/sparkle/mxu-outer-alias-metadata-diagnostic-first.log')
s=p.read_text();data=json.JSONDecoder().raw_decode(s[s.index('\n{')+1:])[0]
for side,info in data.items():
    kinds=collections.Counter();samples=[]
    for r in info['changed']:
        a,b=r['old'],r['new'];kind=tuple(sorted(k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)))
        attrs=tuple(sorted(k for k in a.get('attributes',{}).keys()|b.get('attributes',{}).keys() if a.get('attributes',{}).get(k)!=b.get('attributes',{}).get(k)))
        kinds[str((kind,attrs))]+=1
        if len(samples)<4:samples.append(r)
    print(json.dumps({'side':side,'changed_count':len(info['changed']),'kinds':kinds,'samples':samples,
                     'removed_count':len(info['removed']),'removed_semantic':[r for r in info['removed'] if r['metadata'].get('attributes')],
                     'added_count':len(info['added'])},indent=2))
