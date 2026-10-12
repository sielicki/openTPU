"""Independently bind original elaborated child parameters to native Config projections."""
import argparse,json,subprocess
from pathlib import Path
from prove_sparkle_slice import ROOT,DEFAULT,FIELDS,source_closure
from prove_sparkle_seq_logic import hashes
from sparkle_provenance import archive
FIELDS_BY_UNIT={
 'seq':{'D':'seq.depth','IMEM_WORDS':'seq.words','S':'seq.slices','SID':'sliceId','WIN':'seq.slots'},
 'tmem':{'WORDS':'tmem.words','LANES':'tmem.lanes','NRP':'tmem.readPorts','NWP':'tmem.writePorts','WPB':'tmem.writesPerBank','GEN_R':'tmem.generalRead','GEN_W':'tmem.generalWrite','SH_HOST':'tmem.shareHost','SH_MASK':'tmem.shareMask','SID':'sliceId'},
 'act':{'D':'act.depth','MCOLS':'act.columns','ROWS':'act.rows','BLOCKS':'act.blocks','LANES':'act.lanes'},
 'dma':{'D':'dma.chunkBytes','LANES':'dma.lanes','DEPTH':'dma.bufferDepth','HAS_DSTEP':'dma.streams'},
 'mxu':{'D':'mxu.d','MCOLS':'mxu.columns','ROWS':'mxu.rows','DEPTH':'mxu.depth','LANES':'mxu.lanes','IMPL':'mxu.implementation','CL':'mxu.chainLength','SID':'mxu.sliceId'},
 'quant':{'D':'quant.depth','LANES':'quant.lanes','SID':'sliceId'},
 'vpu':{'LANES':'vpu.lanes','CL':'vpu.compositeLanes','SID':'sliceId','HAS_SE':'vpu.streams','WBUF':'vpu.buffered'}}
def check(cfg):
    work=ROOT/'build/sparkle/formal_slice'/'_'.join(map(str,cfg));contracts=work/'contracts.json';original=json.loads(contracts.read_text())
    gen=work/'Parameters.lean';output=work/'native-parameters.txt'
    config=','.join(f'{k}:='+('true' if v else 'false') if k=='streams' else f'{k}:={v}' for k,v in zip(FIELDS,cfg))
    lines=['import OpenTPU.SliceConfig','def main : IO Unit := do',f'  let c : OpenTPU.Slice.Config := {{{config}}}']
    for unit,fields in FIELDS_BY_UNIT.items():
        for param,field in fields.items():
            expr='c.'+field
            if param in ['HAS_DSTEP','HAS_SE','WBUF']:expr=f'if {expr} then 1 else 0'
            lines.append('  IO.println s!"'+unit+' '+param+' {'+expr+'}"')
    gen.write_text('\n'.join(lines)+'\n');sources=[gen,*source_closure(ROOT/'OpenTPU/SliceConfig.lean')];before=hashes(sources)
    for p in sources:archive(p)
    with output.open('w') as out:subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,stdout=out,check=True)
    assert hashes(sources)==before
    native={}
    for line in output.read_text().splitlines():
        unit,param,value=line.split();native.setdefault(unit,{})[param]=int(value)
    bindings=[]
    for record in original:
        expected={k:int(v,2) for k,v in record['gold_parameters'].items()};actual=native[record['unit']]
        assert actual==expected,(record['unit'],actual,expected)
        bindings.append({'unit':record['unit'],'parameters':actual})
    inputs=[contracts,output,gen,Path(__file__).resolve(),*sources]
    for p in inputs:archive(p)
    result={'status':'passed','config':cfg,'parameters':bindings,'input_sha256':hashes(inputs),'scope':__doc__}
    (work/'parameter-binding.json').write_text(json.dumps(result,indent=2)+'\n');return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',nargs=19,type=int,default=DEFAULT);a=p.parse_args();print(check(a.config)['status'])
