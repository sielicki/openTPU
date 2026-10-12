"""Native VPU control composition: hierarchy, drivers, combinational loops and hints.

This checks assembled structure, not full-VPU behavioral equivalence. Individual
component transition proofs remain the behavioral evidence until integration.
"""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
WORK=ROOT/'build/sparkle/check_vpu_control'
CONFIGS=[(8,8,True,True),(8,8,True,False),(8,4,False,True),(4,2,False,False),(16,4,False,True)]

def check(cfg):
    l,cl,se,buffered=cfg;work=WORK/'_'.join(map(str,(l,cl,int(se),int(buffered))));work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv';plain=work/'plain.sv';gen=work/'Generate.lean'
    value=f'{{lanes := {l},compositeLanes := {cl},streams := {str(se).lower()},buffered := {str(buffered).lower()}}}'
    gen.write_text('import OpenTPU.VpuControl\ndef main : IO Unit := do\n'
        f'  let c : OpenTPU.VpuControl.Config := {value}\n'
        f'  IO.FS.writeFile "{source}" (← IO.ofExcept (OpenTPU.VpuControl.toVerilog c))\n'
        f'  IO.FS.writeFile "{plain}" (String.join ((← IO.ofExcept (OpenTPU.VpuControl.build c)).modules.map Sparkle.Backend.Verilog.toVerilog))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    def tokens(p):
        s=re.sub(r'/\*.*?\*/|//[^\n]*','',p.read_text(),flags=re.S)
        s=re.sub(r'\(\*.*?\*\)','',s,flags=re.S)
        return re.findall(r'\w+|[^\s]',s)
    assert tokens(source)==tokens(plain),'physical emitter changed functional tokens'
    flat=work/'flat.json'
    script,log=yosys(work,'structure',f'''read_slang --top otpu_vpu_control_sparkle {source.relative_to(ROOT)}
hierarchy -check -top otpu_vpu_control_sparkle
proc
flatten
opt
check -assert
scc -expect 0
write_json {flat.relative_to(ROOT)}
''')
    m=json.loads(flat.read_text())['modules']['otpu_vpu_control_sparkle']
    boundary=set("clk rst start cmd c_hold gnt mo_v mo_all_last mo_mask mo_waddr lres lmm lmv mxm_v mxm_tag mxm_row_last mxm_all_last mxm_waddr mx_new mx_ni am4_v am4_l am4_a am4_m am4_i root root_v rbuf_q".split())
    if se and l==8:
        boundary.update("ss_req ss_pe ss_fk ss_fi ss_fd ss_in_v ss_in_d ss_cfg s_xm_first t_qc t_qrl t_qsub t_qd cap vt_rl t_yv t_ov".split())
    else:
        # Unused external controls still occur on the configurable write-buffer interface.
        boundary.add('ss_pe')
    actual={n for n,v in m['ports'].items() if v['direction']=='input'}
    assert actual==boundary,('unexpected boundary ports',sorted(actual-boundary),sorted(boundary-actual))
    expected=[]
    if buffered:expected.append(('u_write_buffer.en_r',64))
    if se and l==8:
        if buffered:expected.append(('u_write_buffer.en_q',32))
        expected += [('u_stream.ss_act',64),('u_stream.sen',64),('u_stream.sen_q',32)]
    for name,value in expected:
        attr=m['netnames'][name]['attributes']['max_fanout'];assert int(attr,2)==value,(name,attr)
    files=[source,plain,gen,script,Path(__file__).resolve(),*[ROOT/'OpenTPU'/f'{n}.lean' for n in ['VpuControl','VpuCommand','VpuIssue','VpuSequence','VpuWriteBuffer','VpuWriteSelect','VpuStream','VpuDecode','Circuit','Backend']]]
    print('PASS VPU control composition',cfg,flush=True)
    return {'config':cfg,'input_sha256':hashes(files),'hints':expected,'inputs':[n for n,v in m['ports'].items() if v['direction']=='input'],'outputs':[n for n,v in m['ports'].items() if v['direction']=='output']}

def main():
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json';records=[]
    try:
        for cfg in CONFIGS:
            records.append(check(cfg));summary.write_text(json.dumps({'status':'running','cases':records},indent=2)+'\n')
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'cases':records},indent=2)+'\n')
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err),'cases':records},indent=2)+'\n');raise
if __name__=='__main__':main()
