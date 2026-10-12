"""Native trace ABI differential checks against the original board recorder."""
import json,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from sparkle_provenance import archive
WORK=ROOT/'build/sparkle/check_trace'
CONFIGS=[(4,2,16),(64,4,8),(16384,32,16)]

def check(cfg):
    depth,qd,win=cfg;work=WORK/f'{depth}_{qd}_{win}';work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.TraceABI\ndef main : IO Unit := do\n'
       f'  IO.FS.writeFile "{native}" (← IO.ofExcept (OpenTPU.Trace.abiVerilog ⟨{depth},{qd},{win}⟩))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    rtl=ROOT/'rtl/boards/ypcb-00338/otpu_trace.sv';pkg=ROOT/'rtl/top/otpu_pkg.sv'
    ref=work/'reference.sv';ref.write_text(rtl.read_text().replace('module otpu_trace\n','module gold\n'))
    tb=work/'tb.sv';tb.write_text('''module tb;
import otpu_pkg::*;
bit clk=0,rst=1,en=0,stop=0,clear=0;
perf_t pf='0;
logic [31:0] raddr=0,count_g,count_n,drop_g,drop_n;
logic [63:0] rdata_g,rdata_n;
logic busy_g,busy_n;
int unsigned random_state=32'h91a52f33;
function automatic logic [31:0] rng();
 random_state ^= random_state << 13;
 random_state ^= random_state >> 17;
 random_state ^= random_state << 5;
 return random_state;
endfunction
'''+f'''gold #(.DEPTH({depth}),.QD({qd}),.WIN({win})) g
(.clk,.rst,.pf,.en,.stop,.clear,.raddr,.rdata(rdata_g),.count(count_g),.drop(drop_g),.busy(busy_g));
otpu_trace #(.DEPTH({depth}),.QD({qd}),.WIN({win})) n
(.clk,.rst,.pf,.en,.stop,.clear,.raddr,.rdata(rdata_n),.count(count_n),.drop(drop_n),.busy(busy_n));
'''+'''
int drops=0,writes=0,stops=0,drains=0;
initial begin
 for(int t=0;t<20000;t++) begin
  clk=0;
  for(int b=0;b<$bits(pf);b++) pf[b]=1'(rng());
  pf.sq.d_pc[31:16]=0;
  pf.sq.cyc=t;
  rst=(t<3)||(t%4001==0);
  clear=(t%2003==0);
  en=(t%4000<2000);
  stop=(t%6000<2000);
  if(t%4000>=2000) pf='0;
  raddr=rng();
  #5;clk=1;#5;
  if ({rdata_g,count_g,drop_g,busy_g} !== {rdata_n,count_n,drop_n,busy_n})
    $fatal(1,"trace mismatch cycle %0d count %0d/%0d drop %0d/%0d data %h/%h busy %b/%b",t,count_g,count_n,drop_g,drop_n,rdata_g,rdata_n,busy_g,busy_n);
  if(drop_g!=0)drops++;
  if(count_g!=0)writes++;
  if(stop && count_g>='''+str(depth)+''')stops++;
  if(!en && !busy_g)drains++;
 end
 if(drops==0||writes==0||drains==0) $fatal(1,"missing trace coverage");
'''+(' if(stops==0)$fatal(1,"missing full-ring stop coverage");\n' if depth<100 else '')+'''
 $display("PASS trace 20000 cycles drops=%0d writes=%0d stops=%0d drains=%0d",drops,writes,stops,drains);
 $finish;
end
endmodule
''')
    files=[native,gen,ref,tb,rtl,pkg,ROOT/'OpenTPU/Trace.lean',ROOT/'OpenTPU/TraceABI.lean',ROOT/'OpenTPU/Circuit.lean',ROOT/'OpenTPU/Backend.lean',Path(__file__).resolve()]
    before=hashes(files)
    for p in files:archive(p)
    obj=work/'obj';buildlog=work/'build.log'
    cmd=['verilator','--binary','--timing','-j','2','--top-module','tb','-Wno-fatal','--Mdir',str(obj),str(pkg),str(ref),str(native),str(tb)]
    with buildlog.open('w') as out:subprocess.run(cmd,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=300)
    log=work/'run.log'
    with log.open('w') as out:subprocess.run([str(obj/'Vtb')],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=120)
    assert 'PASS trace 20000 cycles' in log.read_text()
    assert hashes(files)==before,'trace inputs changed during test'
    print(cfg,log.read_text().splitlines()[0],flush=True)
    return {'config':cfg,'cycles':20000,'input_sha256':before,'log':str(log.relative_to(ROOT)),'log_sha256':hashes([log])}

def main():
    WORK.mkdir(parents=True,exist_ok=True);records=[];summary=WORK/'summary.json'
    try:
        for cfg in CONFIGS:
            records.append(check(cfg));summary.write_text(json.dumps({'status':'running','tests':records},indent=2)+'\n')
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'tests':records},indent=2)+'\n')
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err),'tests':records},indent=2)+'\n');raise
if __name__=='__main__':main()
