"""AXI-Lite differential qualification of the native board control ABI.

Exercises all 4096 byte addresses, valid/data arrival skew, response stalls,
ignored byte strobes, argument packing, every counter and shadow, loader pulses,
trace-address increment/write priority, and resets during active transactions.
"""
import json
import subprocess
from pathlib import Path

from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_provenance import archive

WORK = ROOT/'build/sparkle/check_control'
FIELDS = ['depth','columns','lanes','actRows','coreKhz','buildId','ddrMts','traceDepth',
          'pqWindow','hasTemp','hasI2c','channelHash','dstep','hostCalibration']
PARAMS = ['D','MCOLS','LANES','ACT_ROWS','CORE_KHZ','BUILD_ID','DDR_MTS','TRACE_DEPTH',
          'PQ_WIN','HAS_TEMP','HAS_I2C','CHASH','DSTEP','HOSTCAL']
CONFIGS = [
    [128,2,8,2,100000,0,0,16384,1024,True,True,False,True,False],
    [32,3,4,6,125000,0xfeedbeef,1600,0,512,False,False,True,False,True],
    [256,4,16,3,133333,0x1234abcd,800,17,37,False,True,True,True,True],
]
INPUTS = {'s_awaddr':12,'s_awvalid':1,'s_wdata':32,'s_wstrb':4,'s_wvalid':1,
          's_bready':1,'s_araddr':12,'s_arvalid':1,'s_rready':1,
          'ld_busy':1,'halted':1,'error':1,'wait_to':1,'icount':32,'wr_idle':1,'axi_err':1,
          'calib':2,'b_rd':1,'b_wr':1,'a_rd':1,'a_wr':1,'b_wait':1,'temp_v':1,'temp':12,
          'mxu_busy':1,'mxu_mac':1,'vpu_busy':1,'qnt_busy':1,'dma_busy':1,'tmem_deny':1,
          'mxu_starve':1,'dram_rd':2,'dram_wr':2,'dram_wait':1,'instr':2,
          'tr_count':32,'tr_drop':32,'tr_busy':1,'tr_rdata':64,'i2c_in':5}
OUTPUTS = {'s_awready':1,'s_wready':1,'s_bresp':2,'s_bvalid':1,'s_arready':1,
           's_rdata':32,'s_rresp':2,'s_rvalid':1,'run':1,'ld_start':1,'ld_addr':32,'ld_n':32,
           'tr_en':1,'tr_stop':1,'tr_clear':1,'tr_addr':32,'i2c_lo':4}


def bench(cfg):
    declarations = '\n'.join(f'logic [{w-1}:0] {n}=0;' for n,w in INPUTS.items())
    declarations += '\n' + '\n'.join(f'wire [{w-1}:0] g_{n},n_{n};' for n,w in OUTPUTS.items())
    ports = '.clk,.rst,' + ','.join('.'+n for n in INPUTS)
    params = ','.join(f'.{n}(32\'d{int(v)})' for n,v in zip(PARAMS,cfg))
    instances = '\n'.join(f'{module} #({params}) {name} ({ports},.arg({prefix}_arg),'+
                          ','.join(f'.{n}({prefix}_{n})' for n in OUTPUTS)+');'
                          for module,name,prefix in [('gold_ctrl','gold','g'),('otpu_ctrl','native','n')])
    compare = '\n'.join(f'if(g_{n} !== n_{n}) $fatal(1,"control {n} cycle=%0d gold=%h native=%h",cycles,g_{n},n_{n});' for n in OUTPUTS)
    compare += '\nfor(int k=0;k<8;k++) if(g_arg[k] !== n_arg[k]) $fatal(1,"arg packing index=%0d",k);'
    for name in ['cycles','n_brd','n_bwr','n_ard','n_awr','n_bst','scratch','clear','snap','n_snap','ld_pend_q','r_a','r_p','r_d']:
        compare += f'\nif(gold.{name} !== native.impl.{name}) $fatal(1,"state {name} cycle=%0d",cycles);'
    for i in range(13):
        for name in ['fr','fr_s','fr_inc']:
            compare += f'\nif(gold.{name}[{i}] !== native.impl.{name}{i}) $fatal(1,"counter {name}[{i}] cycle=%0d",cycles);'
    events = '\n'.join(f'{name}=rnd();' for name in INPUTS if not name.startswith('s_') and name != 'tr_rdata')
    return '''module tb;
logic clk=0,rst=1;
wire [31:0] g_arg[8],n_arg[8];
''' + declarations + '\n' + instances + '''
int unsigned seed=32'h783cf14b;
function automatic int unsigned rnd();seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;endfunction
int cycles=0,write_stalls=0,read_stalls=0,skew=0,collisions=0,reset_pending=0,snapshots=0,clears=0;
int aw_seen[4096]='{default:0},ar_seen[4096]='{default:0},strb_seen[16]='{default:0};
bit aw_taken,w_taken,ar_taken;
task automatic activity();
''' + events + '''
tr_rdata={rnd(),rnd()};
endtask
task automatic tick();
clk=0;activity();#2;
aw_taken=s_awvalid&&g_s_awready;w_taken=s_wvalid&&g_s_wready;ar_taken=s_arvalid&&g_s_arready;
if(aw_taken) begin aw_seen[s_awaddr]++;strb_seen[s_wstrb]++;end
if(ar_taken) ar_seen[s_araddr]++;
write_stalls += int'(g_s_bvalid && !s_bready);
read_stalls += int'(g_s_rvalid && !s_rready);
skew += int'(s_awvalid != s_wvalid);
collisions += int'(gold.tr_inc && gold.w_go && s_awaddr[11:2]==10'h083 && !rst);
reset_pending += int'(rst && (g_s_bvalid || g_s_rvalid || gold.r_p!=0));
snapshots += int'(gold.snap);clears += int'(gold.clear);
clk=1;#3;cycles++;
''' + compare + '''
clk=0;
endtask
task automatic idle();
s_awvalid=0;s_wvalid=0;s_arvalid=0;s_bready=1;s_rready=1;
while(g_s_bvalid || g_s_rvalid || gold.r_p!=0) tick();
endtask
task automatic wr(input int address,input int data,input int strobes);
s_awaddr=12'(address);s_wdata=data;s_wstrb=4'(strobes);s_awvalid=1;s_wvalid=1;s_bready=1;
do tick();while(!aw_taken);
s_awvalid=0;s_wvalid=0;
while(g_s_bvalid) tick();
endtask
task automatic rd(input int address,output logic [31:0] data);
s_araddr=12'(address);s_arvalid=1;s_rready=0;
do tick();while(!ar_taken);
s_arvalid=0;
while(!g_s_rvalid) tick();
data=g_s_rdata;
repeat(address%4) tick();
s_rready=1;tick();
endtask
initial begin
logic [31:0] got;
repeat(4) tick();rst=0;idle();
// Every decoded and unmapped byte address, including all unaligned aliases.
for(int a=0;a<4096;a++) wr(a,rnd(),a%16);
for(int a=0;a<4096;a++) rd(a,got);
// WSTRB is intentionally ignored by the original block, even when zero.
for(int s=0;s<16;s++) begin
 wr('h38,32'h719a0300+s,s);rd('h38,got);
 if(got !== 32'h719a0300+s) $fatal(1,"WSTRB semantics changed");
end
// Explicit writes to every argument expose packed/unpacked lane ordering.
for(int k=0;k<8;k++) wr('h60+4*k,32'hfc001100+k,k);
for(int k=0;k<8;k++) if(n_arg[k] !== 32'hfc001100+k) $fatal(1,"argument value");
// Counter snapshots, clear while active, and loader-control transitions.
for(int k=0;k<16;k++) begin
 wr('h08,k%8,k);repeat(7) tick();wr('h50,0,0);
 for(int n=0;n<26;n++) rd('h100+4*n,got);
end
// At the high-word response edge TRACE_ADDR's write overrides its increment.
idle();s_araddr='h214;s_arvalid=1;s_rready=0;tick();s_arvalid=0;tick();
s_awaddr='h20c;s_wdata=32'habcd9876;s_wstrb=0;s_awvalid=1;s_wvalid=1;tick();
if(n_tr_addr !== 32'habcd9876) $fatal(1,"trace-address collision priority");
idle();
// Reset while read/response pipeline and write response are occupied.
s_araddr='h214;s_arvalid=1;s_rready=0;tick();s_arvalid=0;tick();
s_awaddr='h20c;s_wdata='1;s_awvalid=1;s_wvalid=1;rst=1;tick();
if(n_tr_addr !== 0) $fatal(1,"trace-address reset priority");
rst=0;idle();
for(int cycle=0;cycle<30000;cycle++) begin
 rst=(cycle%997==0 || cycle%997==1);
 if(rst || !s_awvalid || aw_taken) begin
  s_awvalid=rnd()%3!=0;
  case(rnd()%6)
   0:s_awaddr='h08;1:s_awaddr='h50;2:s_awaddr='h20c;
   3:s_awaddr='h200;4:s_awaddr='h60+4*(rnd()%8);default:s_awaddr=rnd();
  endcase
 end
 if(rst || !s_wvalid || w_taken) begin s_wvalid=rnd()%3!=0;s_wdata=rnd();s_wstrb=rnd();end
 if(rst || !s_arvalid || ar_taken) begin
  s_arvalid=rnd()%3!=0;s_araddr=rnd()%3==0?'h214:12'(rnd());
 end
 s_bready=rnd()%4==0;s_rready=rnd()%5==0;
 tick();
end
rst=0;idle();
for(int a=0;a<4096;a++) if(aw_seen[a]==0 || ar_seen[a]==0) $fatal(1,"address coverage %h",a);
for(int s=0;s<16;s++) if(strb_seen[s]==0) $fatal(1,"strobe coverage %h",s);
if(write_stalls<100 || read_stalls<100 || skew<100 || collisions<1 || reset_pending<1 || snapshots<16 || clears<10)
 $fatal(1,"missing protocol/event coverage");
$display("PASS CONTROL cycles=%0d all4096addresses all16strobes wstall=%0d rstall=%0d skew=%0d trace_collisions=%0d reset_pending=%0d snapshots=%0d clears=%0d",cycles,write_stalls,read_stalls,skew,collisions,reset_pending,snapshots,clears);
$finish;
end
endmodule
'''


def check(cfg, index):
    directory = WORK/str(index)
    directory.mkdir(parents=True,exist_ok=True)
    runner, native, reference, tb = [directory/n for n in ['Generate.lean','native.sv','reference.sv','tb.sv']]
    config = ', '.join(n+' := '+(str(v).lower() if isinstance(v,bool) else str(v)) for n,v in zip(FIELDS,cfg))
    runner.write_text('import OpenTPU.ControlABI\ndef main : IO Unit := do\n'
                     f'  IO.FS.writeFile "{native}" (OpenTPU.Control.abiVerilog {{{config}}})\n')
    original = ROOT/'rtl/boards/ypcb-00338/otpu_ctrl.sv'
    reference.write_text(original.read_text().replace('module otpu_ctrl #(', 'module gold_ctrl #(', 1))
    tb.write_text(bench(cfg))
    sources = [runner, reference, tb, original, Path(__file__).resolve(), ROOT/'OpenTPU/Control.lean',
               ROOT/'OpenTPU/ControlABI.lean',ROOT/'OpenTPU/Circuit.lean']
    before = hashes(sources)
    for path in sources:
        archive(path)
    subprocess.run(['lake','env','lean','--run',str(runner)],cwd=ROOT,check=True)
    assert hashes(sources)==before
    inputs = hashes(sources+[native])
    (directory/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    with (directory/'build.log').open('w') as log:
        subprocess.run(['verilator','--binary','--timing','-j','2','--top-module','tb','-Wno-fatal',
                        '--x-assign','0','--x-initial','0','--Mdir',str(directory/'obj'),str(reference),str(native),str(tb)],
                       cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    result = subprocess.run([str(directory/'obj/Vtb')],cwd=ROOT,capture_output=True,text=True,timeout=180)
    log = directory/'run.log'
    log.write_text(result.stdout+result.stderr)
    assert result.returncode==0 and 'PASS CONTROL' in result.stdout, str(log)+'\n'+result.stdout
    assert hashes(sources+[native])==inputs
    print(result.stdout.splitlines()[0],flush=True)
    return {'config':dict(zip(FIELDS,cfg)),'input_sha256':inputs,'log_sha256':hashes([log]),'log':str(log.relative_to(ROOT))}


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    with (WORK/'lake-build.log').open('w') as log:
        subprocess.run(['lake','build','OpenTPU.ControlABI'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    records=[]
    summary=WORK/'summary.json'
    try:
        for i,cfg in enumerate(CONFIGS):
            records.append(check(cfg,i))
            summary.write_text(json.dumps({'status':'running','cases':records},indent=2)+'\n')
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'cases':records},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error),'cases':records},indent=2)+'\n')
        raise


if __name__=='__main__':
    main()
