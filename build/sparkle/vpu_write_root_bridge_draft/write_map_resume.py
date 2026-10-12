"""Exact immutable isolated memory_map replay; no semantic status promotion."""
import json
from pathlib import Path
from physical_slices import require
from check_geometry import safe
from qualify_sparkle_specialization_binding import read


def map_memory(s,isolated):
    folder=s.work/'none';path=folder/'isolated.json';mapped_path=folder/'mapped.json'
    digest=s.write(path,isolated);old=None if s.prior is None else s.prior.get('map_record')
    if old is not None:
        require(old['isolated_sha256']==digest,'Resume isolated memory differs');paths={}
        require(set(old['artifacts'])==set(old['query_paths'])=={'raw','mapped','script','command','result','log'},'Incomplete map reuse')
        for name,record in old['artifacts'].items():
            require(record['query_path']==old['query_paths'][name] and s.prior_map.get(record['stored_path'])==record['sha256'],'Map owner/path identity differs')
            p=Path(s.ev.authenticated[(record['stored_path'],record['sha256'])]);s.freeze(p,record['sha256']);paths[name]=p
        require(old['artifacts']['raw']['sha256']==digest,'Reused raw map identity differs')
        expected=f'read_json {safe(Path(old["query_paths"]["raw"]))}\nmemory_map\nwrite_json {safe(Path(old["query_paths"]["mapped"]))}\n'
        require(paths['script'].read_text()==expected and read(paths['command'])=={'argv':[str(s.binary),'-Q','-T','-s',old['query_paths']['script']],'cwd':str(s.root),'timeout':120}
            and read(paths['result'])=={'returncode':0} and 'ERROR:' not in paths['log'].read_text(),'Map replay invocation/result differs')
        mapped=read(paths['mapped']);record=json.loads(json.dumps(old))
        for name,p in paths.items():record['artifacts'][name]['stored_path']=str(p)
    else:
        s.active.add(mapped_path);s.checkpoint()
        rc,log=s.script('none/map',f'read_json {safe(path)}\nmemory_map\nwrite_json {safe(mapped_path)}\n')
        require(rc==0 and mapped_path.is_file() and 'ERROR:' not in log,'Actual mapping incomplete')
        s.freeze(mapped_path);mapped=read(mapped_path)
        paths={'raw':path,'mapped':mapped_path,'script':folder/'map.ys','command':folder/'map.command.json','result':folder/'map.result.json','log':folder/'map.log'}
        record={'isolated_sha256':digest,'query_paths':{n:str(p) for n,p in paths.items()},
                'artifacts':{n:{'query_path':str(p),'stored_path':str(p),'sha256':s.freeze(p)} for n,p in paths.items()}}
    s.report['map_record']=record;s.checkpoint();return mapped
