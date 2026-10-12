"""Unrestricted combinational equivalence of both native slice arbiter paths."""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
WORK=ROOT/'build/sparkle/formal_slice_arbiter'
CONFIGS=[(2,2,2),(4,4,2),(8,4,2),(2,16,1),(8,64,1),(16,128,1)]

def prove(cfg,mutation=False):
    l,r,w=cfg;work=WORK/('_'.join(map(str,cfg)))
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.SliceArbiter\ndef main : IO Unit := do\n'
      f'  IO.FS.writeFile "{native}" (← IO.ofExcept (OpenTPU.SliceArbiter.toVerilog ⟨{l},{r},{w}⟩))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    mapped = r >= 8*l and w == 1
    if mapped:
        # Checked intermediate points, never assumptions: equiv_status requires
        # every mask/admission bit as well as every external output to prove.
        aliases = (f'wire [{5*l-1}:0] amk = {{' +
                   ','.join(f'_gen_mask{i}' for i in reversed(range(5))) + '};\n' +
                   'wire [4:0] aok = {' +
                   ','.join(f'_gen_ok{i}' for i in reversed(range(5))) + '};\n')
        source = native.read_text()
        assert source.count('endmodule') == 1
        native.write_text(source.replace('endmodule', aliases+'endmodule'))
    if mutation:
        s,n=re.subn(r'(assign coll_gnt_local = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1)
        assert n==1;native.write_text(s)
    rtl=ROOT/'rtl/top/otpu_slice.sv';s=rtl.read_text()
    body=s[s.index('  // ---- TMEM bank arbiter:'):s.index('  // ---- DRAM ports')]
    constants=s[s.index('  localparam int BW'):s.index('  // ---- sequencer')]
    ref=work/'reference.sv'
    ref.write_text(f'''module gold # (parameter LANES={l},RPB={r},WPB={w})(
 input [7:0][LANES-1:0] rq_en,
 input [7:0][LANES-1:0][31:0] r_addr,
 input [3:0][LANES-1:0] wq_en,
 input [3:0][LANES-1:0][31:0] w_addr,
 input q_awant,sw_rdy,coll_gnt,v_ren,
 output logic [4:0] gnt,
 output logic coll_gnt_local,
 output logic [7:0][LANES-1:0] r_en,
 output logic [3:0][LANES-1:0] w_en,
 output logic [3:0] w_gnt
);
'''+constants+body+'\nendmodule\n')
    mapping = 'techmap\nopt -full\nabc -g simple\nopt_clean\n' if mapped else ''
    strategy = 'equiv_simple -short -nogroup' if mapped else 'equiv_simple'
    script=work/'proof.ys';script.write_text(f'''read_slang --top gold {ref.relative_to(ROOT)}
read_slang --top otpu_slice_arbiter_sparkle {native.relative_to(ROOT)}
rename otpu_slice_arbiter_sparkle gate
proc
opt_expr
opt_clean
{mapping}equiv_make gold gate equiv
hierarchy -top equiv
opt -full
{strategy}
equiv_status -assert
''')
    files=[native,ref,gen,script,rtl,Path(__file__).resolve(),ROOT/'OpenTPU/SliceArbiter.lean',ROOT/'OpenTPU/Circuit.lean']
    before=hashes(files);log=work/'proof.log'
    (work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    with log.open('w') as out: result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=600)
    assert hashes(files)==before
    if mutation: assert result.returncode and 'unproven $equiv cells' in log.read_text(),str(log)
    else: assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS slice arbiter',cfg,'mutation rejected' if mutation else '',flush=True)
    return {'config':cfg,'mutation':mutation,'input_sha256':before,'log':str(log.relative_to(ROOT))}

def main():
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json';records=[]
    try:
        for cfg in CONFIGS:
            records.append(prove(cfg));summary.write_text(json.dumps({'status':'running','proofs':records},indent=2)+'\n')
        for cfg in [CONFIGS[0],CONFIGS[3]]:records.append(prove(cfg,True))
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'proofs':records},indent=2)+'\n')
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err),'proofs':records},indent=2)+'\n');raise
if __name__=='__main__':main()
