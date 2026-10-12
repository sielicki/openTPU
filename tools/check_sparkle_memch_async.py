"""Qualify native asynchronous FIFOs in the unchanged board memory-channel bench.

Only otpu_afifo is replaced. The channel, split, controller models, scoreboards,
reset checks, and internal monitors remain their original sources. This is digital
qualification; the added ABI hierarchy requires CDC constraint remapping before
board implementation and is not a routed timing/metastability qualification.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

import memch_test
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_async_fifo import prove
from prove_sparkle_qscale import yosys
from sparkle_provenance import verify, archive
from check_sparkle_physical import module_tokens

WORK = ROOT / 'build/sparkle/check_memch_async'
CONFIGS = [(26,32,False,False), (577,32,False,False), (512,64,True,False),
           (26,16,False,True), (577,16,False,True), (512,16,True,False)]
SCENARIOS = {
    'ldn': ['default','partial','ctlstall','fastcore','slowcore','resetsrep',
            'aresetshort','xresetshort','seqrd','seqwr','shared','gen2deep'],
    'cred': ['default','credstress','resetsrep'],
    'xreg': ['default','gen2xres','gen2part','gen2full','gen2deepx'],
}


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def generate():
    source = WORK / 'native.sv'
    runner = WORK / 'Generate.lean'
    runner.write_text('import OpenTPU.AsyncFifoABI\ndef main : IO Unit := do\n'
                     f'  IO.FS.writeFile "{source}" (← IO.ofExcept (OpenTPU.AsyncFifoABI.memChVerilog 64 16))\n')
    sources = [runner, ROOT/'OpenTPU/AsyncFifoABI.lean', ROOT/'OpenTPU/AsyncFifo.lean',
               ROOT/'OpenTPU/Backend.lean', ROOT/'OpenTPU/Circuit.lean', Path(__file__).resolve()]
    before = hashes(sources)
    write(WORK/'generation-inputs.json', before)
    for path in sources:
        archive(path)
    subprocess.run(['lake','build','OpenTPU.AsyncFifoABI'], cwd=ROOT, check=True,
                   stdout=(WORK/'lake-build.log').open('w'), stderr=subprocess.STDOUT)
    subprocess.run(['lake','env','lean','--run',str(runner)], cwd=ROOT, check=True)
    assert hashes(sources) == before, 'generation inputs changed'
    archive(source)
    return source, before


def proofs(source):
    summary = WORK/'fifo-proofs.json'
    old = json.loads(summary.read_text()) if summary.exists() else {'proofs': []}
    records = []
    emitted = module_tokens(source.read_text())
    for cfg in CONFIGS:
        prior = next((r for r in old['proofs'] if tuple(r['config']) == cfg), None)
        if prior:
            verify(prior['input_sha256'])
            record = prior
        else:
            record = prove(cfg)
        log = ROOT/record['log']
        assert 'Equivalence successfully proven!' in log.read_text()
        resolved = verify(record['input_sha256'])
        native = ROOT/next(v for k,v in resolved.items() if k.endswith('/native.sv'))
        name = 'otpu_afifo_sparkle_' + '_'.join(str(int(x)) for x in cfg)
        actual = emitted[name].replace('module'+name+'(', 'moduleotpu_afifo_sparkle(', 1)
        assert actual == module_tokens(native.read_text())['otpu_afifo_sparkle'], ('ABI changed native logic', cfg)
        record['terminal_log_sha256'] = hashes([log])
        records.append(record)
        write(summary, {'status':'running','proofs':records})
    write(summary, {'status':'passed','scope':'All retained state and all four independent write/read edge combinations, actual board FIFO widths and depths.', 'proofs':records})
    return records


def physical(source):
    records = []
    for cfg in CONFIGS:
        name = 'otpu_afifo_sparkle_' + '_'.join(str(int(x)) for x in cfg)
        directory = WORK/'physical'/name
        directory.mkdir(parents=True,exist_ok=True)
        netlist = directory/'physical.json'
        command = f'''read_slang --top {name} {source.relative_to(ROOT)}
proc
memory_collect
check -assert
write_json {netlist.relative_to(ROOT)}
'''
        before = hashes([source,Path(__file__).resolve()])
        write(directory/'inputs.json',before)
        script, log = yosys(directory,'physical',command)
        module = json.loads(netlist.read_text())['modules'][name]
        for signal in ['rgray_w1','rgray_w2','wgray_r1','wgray_r2']:
            assert module['netnames'][signal]['attributes']['ASYNC_REG'] == 'TRUE'
        if cfg[3]:
            assert int(module['netnames']['wa_q']['attributes']['max_fanout'],2) == 32
        memories = [cell for cell in module['cells'].values() if cell['type'] == '$mem_v2']
        assert len(memories) == 1 and memories[0]['attributes']['ram_style'] == 'distributed'
        assert hashes([source,Path(__file__).resolve()]) == before
        records.append({'config':cfg,'input_sha256':dict(before,**hashes([script])), 'log_sha256':hashes([log])})
    return records


def diagnostics(source):
    directory = WORK/'diagnostics'
    directory.mkdir(exist_ok=True)
    tb = directory/'tb.sv'
    tb.write_text('''module tb;
logic wclk=0,rclk=0,wrst=1,rrst=1,wvalid=0;
always #5 wclk=~wclk;
always #7 rclk=~rclk;
wire wready,wcommit,rvalid;wire [4:0] wused;wire [511:0] rdata;
otpu_afifo #(.W(512),.DEPTH(16),.OOO(1)) dut
 (.wclk,.rclk,.wrst,.rrst,.wvalid,.wready,.wcommit,.wused,.rvalid,
  .wdata(512'h1234),.wslot(4'd3),.rready(1'b0),.rdata);
initial begin
repeat(3) @(negedge wclk);
wrst=0;wvalid=1;
@(negedge wclk);wrst=1; // Duplicate during reset is legal and clears pending slots.
@(negedge wclk);wrst=0;
@(negedge wclk);wvalid=$test$plusargs("duplicate");
@(negedge wclk);$display("PASS ASYNC DIAGNOSTIC RESET");$finish;
end
endmodule
''')
    results = []
    for name, fifo in [('reference', ROOT/'rtl/boards/ypcb-00338/otpu_afifo.sv'), ('native',source)]:
        inputs = hashes([fifo,tb])
        write(directory/f'{name}-inputs.json', inputs)
        with (directory/f'{name}-build.log').open('w') as log:
            subprocess.run(['verilator','--binary','--timing','-j','2','--top-module','tb','-Wno-fatal',
                            '--x-assign','0','--x-initial','0','--Mdir',str(directory/name),str(fifo),str(tb)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        for duplicate in [False,True]:
            result = subprocess.run([str(directory/name/'Vtb')] + (['+duplicate'] if duplicate else []),
                                    cwd=ROOT,capture_output=True,text=True,timeout=30)
            log = directory/f'{name}-{int(duplicate)}.log'
            log.write_text(result.stdout+result.stderr)
            if duplicate:
                assert result.returncode != 0 and 'otpu_afifo: slot 3 written twice' in log.read_text(), log
            else:
                assert result.returncode == 0 and 'PASS ASYNC DIAGNOSTIC RESET' in log.read_text(), log
            assert hashes([fifo,tb]) == inputs
            results.append({'implementation':name,'duplicate':duplicate,'input_sha256':inputs,'log_sha256':hashes([log])})
    return results


def bench(source, selected, ntx):
    # Reuse the original bench's compilation and result handling unchanged.
    memch_test.OUT = WORK/'bench'
    memch_test.JOBS = '2'
    memch_test.SRC = [source if p.name == 'otpu_afifo.sv' else p for p in memch_test.SRC]
    records = []
    summary = WORK/'bench-summary.json'
    for name in selected:
        before = hashes(memch_test.SRC + [ROOT/'tools/memch_test.py',Path(__file__).resolve()])
        directory = memch_test.OUT/name
        directory.mkdir(parents=True,exist_ok=True)
        write(directory/'inputs.json', before)
        for path in memch_test.SRC:
            archive(path)
        executable = memch_test.build(name, memch_test.BUILDS[name])
        for scenario in SCENARIOS[name]:
            log = directory/f'{scenario}.log'
            args = memch_test.SCEN[scenario] + [f'+ntx={ntx}','+tmax=100000000','+cov']
            result, throughput, why = memch_test.run(executable, log, args)
            assert result == 'PASS', (name,scenario,result,why,str(log))
            assert hashes(memch_test.SRC + [ROOT/'tools/memch_test.py',Path(__file__).resolve()]) == before
            records.append({'build':name,'scenario':scenario,'arguments':args,'input_sha256':before,
                            'log_sha256':hashes([log]),'throughput':throughput})
            write(summary, {'status':'running','cases':records})
            print('PASS native async FIFO memory-channel bench',name,scenario,flush=True)
    write(summary, {'status':'passed','cases':records})
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', choices=['all','proofs','bench'], default='all')
    ap.add_argument('--builds', nargs='+', choices=list(SCENARIOS), default=list(SCENARIOS))
    ap.add_argument('--ntx', type=int, default=3000)
    args = ap.parse_args()
    WORK.mkdir(parents=True,exist_ok=True)
    source, generation = generate()
    records = proofs(source) if args.phase != 'bench' else None
    attributes = physical(source)
    checks = diagnostics(source) if args.phase != 'proofs' else None
    cases = bench(source,args.builds,args.ntx) if args.phase != 'proofs' else None
    constraints = ROOT/'boards/ypcb-00338/constraints/otpu_mem_ch.tcl'
    result = {'status':'passed','scope':__doc__,'generation_input_sha256':generation,
              'native_sha256':hashes([source]),'proofs':records,'physical':attributes,'diagnostics':checks,'bench':cases,
              'cdc_scope':{'constraint_sha256':hashes([constraints,ROOT/'tools/memch_ooc.tcl']),
                'native_hierarchy':'u_{aq,ad,ar,xq,xd,xr}/g_cfgN/u_native/{wgray,wbin,rgray,rbin,wgray_r1,rgray_w1,mem}',
                'implication':'Existing direct instance/register Tcl patterns do not match the added ABI levels. ASYNC_REG, distributed RAM and write-address fanout hints remain in native cores; board constraint remapping, endpoint-count checks and routed CDC/timing analysis are required before deployment. No board source selection or constraints changed.'}}
    write(WORK/('summary.json' if args.phase=='all' else args.phase+'-summary.json'), result)


if __name__ == '__main__':
    main()
