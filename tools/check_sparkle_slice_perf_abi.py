"""Authenticate retained Slice +bucket guards and every +trace diagnostic token."""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from sparkle_provenance import archive
WORK=ROOT/'build/sparkle/slice_perf_abi'

def tokens(text):
    # Strings are single tokens; comments/whitespace alone are discarded.
    pattern=r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|[A-Za-z_$][A-Za-z0-9_$]*|[0-9]+|[^\s]'
    return [x for x in re.findall(pattern,text,re.S) if not x.startswith(('//','/*'))]

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    gen=WORK/'Generate.lean';window=WORK/'window.sv';trace=WORK/'trace.sv'
    gen.write_text('import OpenTPU.SlicePerfABI\ndef main : IO Unit := do\n'+
      f'  IO.FS.writeFile "{window}" (OpenTPU.SlicePerf.windowDeclaration 17)\n'+
      f'  IO.FS.writeFile "{trace}" (OpenTPU.SlicePerf.traceDiagnostics 3)\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    rtl=ROOT/'rtl/top/otpu_slice.sv';pkg=ROOT/'rtl/top/otpu_pkg.sv';source=rtl.read_text()
    a=source.index('  logic [31:0] win;');b=source.index("  // this cycle's activity:",a)
    original_window=tokens(source[a:b]);original_trace=tokens(source[source.index('`ifndef SYNTHESIS\n  // ---- +trace:'):source.rindex('endmodule')])
    maps={'win':'slice_perf_win','bucket':'slice_perf_bucket','PQ_WIN':'17','trace':'slice_perf_trace','SID':'3'}
    expected_window=[maps.get(t,t) for t in original_window]
    expected_trace=[maps.get(t,t) for t in original_trace]
    assert tokens(window.read_text())==expected_window
    assert tokens(trace.read_text())==expected_trace
    mutated=trace.read_text().replace('pf.w_n, pf.w_q[0]','pf.w_n, pf.w_q[1]')
    assert mutated!=trace.read_text() and tokens(mutated)!=expected_trace
    bench=WORK/'lint.sv';bench.write_text('module perf_abi_check import otpu_pkg::*; (input clk,input perf_t pf);\n'+window.read_text()+trace.read_text()+'\nendmodule\n')
    log=WORK/'lint.log'
    with log.open('w') as out:
        subprocess.run(['verilator','--lint-only','--top-module','perf_abi_check','-Wno-fatal',str(pkg),str(bench)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
    files=[gen,window,trace,bench,log,rtl,pkg,Path(__file__).resolve(),ROOT/'OpenTPU/SlicePerfABI.lean',ROOT/'OpenTPU/SlicePerf.lean']
    manifest=hashes(files)
    for p in files:archive(p)
    (WORK/'summary.json').write_text(json.dumps({'status':'passed','scope':__doc__,'window_tokens':len(expected_window),'trace_tokens':len(expected_trace),'diagnostic_mutation_rejected':True,'input_sha256':manifest},indent=2)+'\n')
    print('PASS Slice perf ABI: exact original guards/diagnostics, mutation rejected, Verilator lint')
if __name__=='__main__':main()
