"""Immutable per-property reuse, independently rechecked against current cone bytes."""
from pathlib import Path
from check_sparkle_fpga_top_complete import require
from qualify_sparkle_specialization_binding import read,normalized_hashes
from sparkle_provenance import sha256,ROOT


def authenticated_artifact(ev,entry):
    require(set(entry)=={'path','sha256'},'Malformed proof artifact identity')
    path=str(Path(entry['path']).resolve());digest=entry['sha256']
    ev.closure({path:digest})
    return Path(ev.authenticated[(path,digest)])


def prior_results(prior,parent_sha):
    require(prior['schema']==2 and prior['parent_sha256']==parent_sha and prior['config']==[8,2,True] and
            prior['product_proven'] is False and prior['status'] in {'incomplete','all_24427_parent_obligations_defined_and_equal_product_unproved'},
            'Prior proof lineage/scope differs')
    result={};ranges=[]
    for item in prior['partitions']:
        lo,hi=item['lo'],item['hi'];require(type(lo)is int and type(hi)is int and 0<=lo<hi<=24427,'Invalid prior interval')
        require((lo,hi) not in result and set(item['proofs'])<={'definedness','equality'},'Repeated/unknown prior proof')
        result[(lo,hi)]=item;ranges.append((lo,hi))
    end=0
    for lo,hi in sorted(ranges):require(lo>=end,'Overlapping prior intervals');end=hi
    return result


def reuse_property(ev,record,graph,bench,manifest,kind,yosys,query,completed):
    require(record['kind']==kind and record['returncode']==0,'Prior property did not succeed')
    require(record['tool_sha256']==sha256(yosys),'Prior solver binary differs')
    paths=record['query_paths'];require(set(paths)=={'graph','bench','model','script'},'Prior query identity malformed')
    require(record['cwd']==str(ROOT),'Prior solver workspace differs')
    for name in ['graph','bench','script']:
        require(paths[name]==record['artifacts'][name]['path'],'Query target is not the authenticated '+name+' artifact')
    artifacts={n:authenticated_artifact(ev,e) for n,e in record['artifacts'].items()}
    require(set(artifacts)=={'graph','bench','manifest','script','command','log','result'},'Incomplete reusable proof artifacts')
    require(sha256(graph)==sha256(artifacts['graph']) and sha256(bench)==sha256(artifacts['bench']),
            'Prior cone or harness changed; cannot inherit proof')
    require(read(manifest)==read(artifacts['manifest']),'Prior full cone/root/projection manifest differs')
    require(artifacts['script'].read_text()==query(Path(paths['graph']),Path(paths['bench']),kind,Path(paths['model'])),
            'Prior query is not exact strong proof')
    command=read(artifacts['command'])
    require(command=={'argv':[str(yosys),'-Q','-T','-s',paths['script']],'cwd':record['cwd']},'Prior solver invocation differs')
    require(read(artifacts['result'])=={'returncode':0,'kind':kind},'Prior returncode evidence differs')
    completed(artifacts['log'],0)
    # Preserve original artifact identities used by the original invocation.
    # HistoricalEvidence resolves those identities to archives on every reuse;
    # replacing these paths with archive filenames would break the query binding.
    return {**record,'reused':True}
