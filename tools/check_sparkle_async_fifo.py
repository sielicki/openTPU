"""Compare native asynchronous FIFO against RTL under independent clock/reset activity."""
import json,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_async_fifo import CONFIGS

WORK=ROOT/'build/sparkle/check_async_fifo'

def bench(cfg):
    w,d,ooo,rwr=cfg;aw=(d-1).bit_length()
    return f'''module tb;
logic wclk=0,rclk=0,wrst=1,rrst=1,wvalid=0,rready=0;
logic [{w-1}:0] wdata=0;logic [{aw-1}:0] wslot=0;
wire gw,nw,gc,nc,gv,nv;wire [{aw}:0] gu,nu;wire [{w-1}:0] gd,nd;
otpu_afifo #(.W({w}),.DEPTH({d}),.OOO({int(ooo)}),.RWR({int(rwr)})) gold
 (.wclk,.rclk,.wrst,.rrst,.wvalid,.rready,.wdata,.wslot,.wready(gw),.wcommit(gc),.wused(gu),.rvalid(gv),.rdata(gd));
otpu_afifo_sparkle native
 (.wclk,.rclk,.wrst,.rrst,.wvalid,.rready,.wdata,.wslot,.wready(nw),.wcommit(nc),.wused(nu),.rvalid(nv),.rdata(nd));
int unsigned seed=32'hbca01937;
function automatic int unsigned rnd();seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;endfunction
int edges[4]='{{default:0}};
int writes=0,reads=0;
initial begin
  for(int step=0;step<20000;step++) begin
    int e;
    wclk=0;rclk=0;
    wrst=step<4 || rnd()%101==0;rrst=step<4 || rnd()%107==0;
    wslot=rnd();wdata=rnd();rready=rnd()%3!=0;
    wvalid=rnd()%3!=0;
    // Respect the reference's duplicate pending-slot diagnostic; other inputs
    // remain independent, including clock edges and each domain's reset.
    if({int(ooo)} && gold.wvld[wslot]) wvalid=0;
    e=step<4?3:rnd()%4;edges[e]++;
    #2;
    if((e&1) && wvalid && gw) writes++;
    if((e&2) && rready && gv) reads++;
    wclk=e&1;rclk=(e>>1)&1;
    #2;
    if({{gw,gc,gu,gv,gd}} !== {{nw,nc,nu,nv,nd}})
      $fatal(1,"async FIFO mismatch step=%0d edges=%0d",step,e);
  end
  for(int e=0;e<4;e++) if(edges[e]<100) $fatal(1,"missing edge coverage");
  if(writes<100 || reads<100) $fatal(1,"missing traffic coverage");
  $display("PASS ASYNC FIFO 20000 steps writes=%0d reads=%0d edges=%p",writes,reads,edges);
  $finish;
end
endmodule
'''

def main():
    WORK.mkdir(parents=True,exist_ok=True);records=[];summary=WORK/'summary.json'
    try:
        subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,check=True)
        rtl=ROOT/'rtl/boards/ypcb-00338/otpu_afifo.sv'
        for cfg in CONFIGS:
            work=WORK/'_'.join(str(int(x)) for x in cfg);work.mkdir(parents=True,exist_ok=True)
            source=work/'native.sv';tb=work/'tb.sv';tb.write_text(bench(cfg))
            subprocess.run([str(ROOT/'.lake/build/bin/opentpu-gen'),'async-fifo-core',*[str(int(x)) for x in cfg],str(source)],cwd=ROOT,check=True)
            files=[source,tb,rtl,Path(__file__).resolve(),ROOT/'OpenTPU/AsyncFifo.lean',ROOT/'OpenTPU/Backend.lean']
            before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
            with (work/'build.log').open('w') as log:
                subprocess.run(['verilator','--binary','--timing','-j','2','-Wno-fatal','--top-module','tb',
                    '--x-assign','0','--x-initial','0','--Mdir',str(work/'obj'),str(rtl),str(source),str(tb)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
            result=subprocess.run([str(work/'obj/Vtb')],cwd=ROOT,capture_output=True,text=True,timeout=120)
            (work/'run.log').write_text(result.stdout+result.stderr)
            assert result.returncode==0 and 'PASS ASYNC FIFO' in result.stdout,str(work/'run.log')
            assert before==hashes(files),'FIFO differential inputs changed'
            records.append(dict(config=cfg,steps=20000,input_sha256=before,log=str(work/'run.log')))
            summary.write_text(json.dumps(dict(status='running',cases=records),indent=2)+'\n')
            print('PASS asynchronous FIFO differential',cfg,flush=True)
        summary.write_text(json.dumps(dict(status='passed',scope=__doc__,cases=records),indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps(dict(status='failed',error=str(error),cases=records),indent=2)+'\n');raise

if __name__=='__main__':main()
