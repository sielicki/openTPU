"""Exact production Control retained-state extension; historical results untouched.

Run only via the bounded gate; each invocation records its own qualification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_compiled_lean import run_generator, import_closure
from sparkle_provenance import archive, sha256
from sparkle_transition import expose_steps, step_miter

NAMES = ['D','MCOLS','LANES','ACT_ROWS','CORE_KHZ','BUILD_ID','DDR_MTS','TRACE_DEPTH',
         'PQ_WIN','HAS_TEMP','HAS_I2C','CHASH','DSTEP','HOSTCAL']
EXPECTED = {
    'gen1': [128,4,8,4,100000,0,1066,16384,1024,1,1,1,1,1],
    'gen2': [128,4,8,4,100000,0,1066,16384,1024,1,1,1,1,1],
    'bundle': [128,4,8,4,133333,0,1066,16384,1024,1,1,1,1,1],
}
BUNDLE = ('{columns:=4,actRows:=4,vpuCompositeLanes:=2,mxuImplementation:=2,lanes:=8,'
          'unitLanes:=8,coreKhz:=133333,buildId:=0,ddrMts:=1066,dstep:=true,pcieGen:=2}')
BUNDLE_CLI = [4,4,2,2,8,8,133333,0,1066,1,2]


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def save(path, value):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(value, f, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def run(command, log, timeout=300):
    process = None
    with log.open('w') as output:
        try:
            process = subprocess.Popen(command, cwd=ROOT, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            return process.wait(timeout=timeout)
        finally:
            if process is not None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()


def small_json(path):
    require(path.stat().st_size <= 64 * 1024 * 1024, 'Control extraction exceeded bounded small-netlist limit')
    with path.open() as source:
        return json.load(source)


COMBINATIONAL = {"$mux", "$pmux", "$bmux", "$bwmux", "$demux", "$eq", "$ne", "$eqx", "$add", "$sub", "$mul", "$div", "$mod", "$shift", "$shiftx",
                 "$not", "$neg", "$logic_not", "$logic_and", "$logic_or", "$and", "$or", "$xor", "$xnor", "$reduce_and", "$reduce_or", "$reduce_xor",
                 "$reduce_bool", "$lt", "$le", "$gt", "$ge", "$shl", "$shr", "$sshr"}


def qbits(module):
    result = set()
    require('clk' in module['ports'], 'Missing clock port')
    for cell in module['cells'].values():
        kind = cell['type']
        require(kind == '$dff' or kind in COMBINATIONAL, 'Unsupported retained state/cell type: ' + kind)
        if kind != '$dff': continue
        pins = cell['connections']; polarity = cell['parameters']['CLK_POLARITY']
        require(set(pins) == {'CLK','D','Q'}, 'Unexpected flop pins')
        require(pins['CLK'] == module['ports']['clk']['bits'] and
                (int(polarity, 2) if isinstance(polarity, str) else polarity) == 1,
                'Unsupported clock or polarity')
        require(len(pins['Q']) == len(pins['D']), 'Flop D/Q width mismatch')
        for bit in pins['Q']:
            require(type(bit) is int and bit not in result, 'Multiply driven or constant state bit')
            result.add(bit)
    return result


def initial_bits(module, state):
    known = {}
    for name, net in module['netnames'].items():
        value = net.get('attributes', {}).get('init')
        if value is None: continue
        require(isinstance(value, str) and len(value) == len(net['bits']) and
                all(c in '01xz' for c in value), 'Unsupported initialization encoding: ' + name)
        for bit, initial in zip(net['bits'], reversed(value)):
            require(bit in state, 'Initialization on non-state bit: ' + name)
            if initial in '01':
                require(bit not in known or known[bit] == initial, 'Conflicting initial aliases: ' + name)
                known[bit] = initial
    return known


def initial_relation(raw, states):
    gold, gate = raw['modules']['gold'], raw['modules']['gate']
    gi, ni = initial_bits(gold, qbits(gold)), initial_bits(gate, qbits(gate))
    checked = set()
    for name in states:
        for gb, nb in zip(gold['netnames'][name]['bits'], gate['netnames'][name]['bits']):
            if gb in gi:
                require(ni.get(nb) == gi[gb], 'Defined gold initialization differs or is missing')
                checked.add(gb)
    require(checked == set(gi), 'Initialization omitted by state mapping')
    return {'gold_defined_bits': len(gi), 'gate_defined_bits': len(ni),
            'relation': 'Every defined reference initial bit is equal; unspecified reference bits permit refinement'}


def correspondence(raw, expected_bits=2421):
    """Original prove_sparkle_control name mapping; no bits are pruned."""
    gold, gate = raw['modules']['gold'], raw['modules']['gate']
    gq, nq = qbits(gold), qbits(gate)
    covered, gcovered, states = set(), set(), {}
    for name, net in list(gate['netnames'].items()):
        if name.startswith('_'): continue
        bits = net['bits']; indices = [i for i,b in enumerate(bits) if b in nq and b not in covered]
        if not indices: continue
        match = re.fullmatch(r'(arg|fr_inc|fr_s|fr)([0-9]+)', name)
        target = ('impl.' + f'{match[1]}[{match[2]}]') if match else ('arg' if name == 'arg' else 'impl.' + name)
        require(target in gold['netnames'], 'Missing reference alias: ' + target)
        other = gold['netnames'][target]['bits']
        require(len(bits) == len(other), 'Alias width differs: ' + name)
        gb, nb = [other[i] for i in indices], [bits[i] for i in indices]
        require(set(gb) <= gq and not (set(gb) & gcovered), 'Invalid/overlapping gold state mapping')
        require(len(set(gb)) == len(gb) and len(set(nb)) == len(nb), 'Repeated state mapping bit')
        alias = f'paired_{len(states)}'
        require(alias not in gold['netnames'] and alias not in gate['netnames'], 'Pair alias collision')
        gold['netnames'][alias] = {'bits':gb, 'hide_name':0}
        gate['netnames'][alias] = {'bits':nb, 'hide_name':0}
        states[alias] = len(nb); covered.update(nb); gcovered.update(gb)
    require(covered == nq and gcovered == gq, 'Incomplete retained-state correspondence')
    require(sum(states.values()) == expected_bits, 'Unexpected Control retained-state inventory')
    return states


def prove(work, native, cfg, yosys, mutation=False, expected_native_digest=None):
    work.mkdir()
    save(work/'summary.json', {'status':'incomplete','config':cfg,'mutation':mutation,'phase':'extraction'})
    target = work / 'native.sv'
    text = native.read_text()
    require(expected_native_digest is not None and
            hashlib.sha256(text.encode()).hexdigest() == expected_native_digest,
            'Proof copy differs from authenticated generation')
    if mutation:
        text, count = re.subn(r'(assign s_arready = )(.*?);', r"\1(\2)^1'b1;", text, count=1)
        require(count == 1, 'Mutation target missing')
    target.write_text(text)
    ref = work / 'reference.sv'
    header = text.split(');',1)[0].replace('module otpu_ctrl_sparkle','module gold') + ');\n'
    ports = re.findall(r'(?:input|output)\s+(?:wire|reg|logic)?\s*(?:\[[^]]+\]\s*)?(\w+)',header)
    require(len(ports) == len(set(ports)) and 'arg' in ports, 'Unexpected control port inventory')
    bindings = ', '.join('.arg(args)' if n == 'arg' else '.' + n for n in ports)
    settings = ', '.join(f'.{n}({v})' for n,v in zip(NAMES,cfg))
    ref.write_text(header + 'logic [31:0] args [8];\n' + f'otpu_ctrl #({settings}) impl ({bindings});\n' +
                   'for(genvar i=0;i<8;i++) assign arg[i*32+:32]=args[i];\nendmodule\n')
    flat = work / 'flat.json'; extract = work / 'extract.ys'
    extract.write_text(f'''read_slang --top gold {ROOT}/rtl/top/otpu_pkg.sv {ROOT}/rtl/boards/ypcb-00338/otpu_ctrl.sv {ref}
flatten
read_slang --top otpu_ctrl_sparkle {target}
rename otpu_ctrl_sparkle gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat}
''')
    require(run([yosys,'-Q','-T','-s',str(extract)], work/'extract.log') == 0, 'Extraction failed')
    modules = small_json(flat)['modules']
    require(set(modules) == {'gold','gate'}, 'Unexpected flattened modules')
    raw = {'modules':modules}; states = correspondence(raw)
    initialization = initial_relation(raw, states)
    steps = expose_steps(raw, states)
    (work/'steps.json').write_text(json.dumps(steps))
    (work/'miter.sv').write_text(step_miter(steps))
    del raw, modules, steps
    script = work / 'proof.ys'
    script.write_text(f'''read_json {work}/steps.json
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
''')
    inputs = {str(p): archive(p) for p in (target,ref,extract,flat,script,work/'steps.json',work/'miter.sv')}
    record = {'status':'incomplete','config':cfg,'state_bits':sum(states.values()),
              'unobserved_bits_removed':{'gold':0,'gate':0},'initial_relation':initialization,'mutation':mutation,'input_sha256':inputs}
    save(work/'summary.json', record)
    code = run([yosys,'-Q','-T','-s',str(script)],work/'proof.log')
    log = (work/'proof.log').read_text()
    require(all(sha256(Path(p)) == h for p,h in inputs.items()), 'Proof inputs changed')
    if mutation:
        require(code != 0 and 'unproven $equiv cells' in log, 'Mutation not rejected by equivalence obligations')
    else:
        require(code == 0 and 'Equivalence successfully proven!' in log, 'Positive equivalence not established')
    record.update(status='passed',result='mutation-rejected' if mutation else 'equivalent',returncode=code,
                  log_sha256=archive(work/'proof.log'))
    save(work/'summary.json',record); archive(work/'summary.json')
    return record


def main():
    bounded_context()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='Fresh directory, must not exist')
    args=parser.parse_args(); work=args.output.resolve()
    require(re.fullmatch(r'[/A-Za-z0-9_.-]+',str(work)) is not None,'Output path must use simple ASCII path characters')
    work.mkdir(parents=True,exist_ok=False)
    record={'status':'incomplete','proofs':[],'scope':'Exact production Control transition equivalence; arbitrary AXI-Lite inputs/reset/state; all 2421 retained bits, no pruning.'}
    save(work/'summary.json',record)
    before={}; started=time.monotonic()
    try:
        gen=work/'Generate.lean'
        gen.write_text('import OpenTPU.FpgaTopConfig\nimport Lean\n'
          'def values (c : OpenTPU.Control.Config) : List Nat :=\n'
          ' [c.depth,c.columns,c.lanes,c.actRows,c.coreKhz,c.buildId,c.ddrMts,c.traceDepth,c.pqWindow,\n'
          '  if c.hasTemp then 1 else 0, if c.hasI2c then 1 else 0, if c.channelHash then 1 else 0,\n'
          '  if c.dstep then 1 else 0, if c.hostCalibration then 1 else 0]\n'
          'def main : IO Unit := do\n'
          f' let cases := [("gen1", ({{}} : OpenTPU.FpgaTop.Config).system.board.control),\n'
          f'  ("gen2", ({{pcieGen:=2}} : OpenTPU.FpgaTop.Config).system.board.control),\n'
          f'  ("bundle", ({BUNDLE} : OpenTPU.FpgaTop.Config).system.board.control)]\n'
          ' for (name,c) in cases do\n'
          f'  IO.FS.writeFile ("{work}/" ++ name ++ ".sv") (Sparkle.Backend.Verilog.toVerilog (OpenTPU.Control.build c))\n'
          f'  IO.FS.writeFile ("{work}/" ++ name ++ ".json") (Lean.Json.compress (Lean.toJson (values c)))\n')
        sources={p for _,p in import_closure(gen).values()}|{gen,Path(__file__).resolve()}
        sources.update(ROOT/p for p in ('rtl/top/otpu_pkg.sv','rtl/boards/ypcb-00338/otpu_ctrl.sv',
                       'lean-toolchain','lakefile.lean','lake-manifest.json','OpenTPU/Generate.lean'))
        sources.update((ROOT/'tools').glob('*.py'))
        before={str(p):archive(p) for p in sources}; record['source_sha256']=before
        tool=Path(shutil.which('yosys') or '').resolve(); require(tool.is_file(),'Yosys unavailable')
        record['yosys']={'path':str(tool),'sha256':archive(tool)}
        save(work/'summary.json',record)
        require(run([str(tool),'-V'],work/'yosys-version.log',10)==0,'Yosys version check failed')
        frontend = work/'frontend.log'
        require(run([str(tool),'-Q','-T','-p','plugin -l; help read_slang'],frontend,30)==0,
                'Frontend inventory capture failed')
        require('read_slang' in frontend.read_text() and 'No such command' not in frontend.read_text(),
                'Required embedded read_slang frontend unavailable')
        require('No plugins loaded.' in frontend.read_text(),
                'External frontend plugins require explicit dependency authentication')
        record['frontend'] = {'inventory_sha256': archive(frontend), 'implementation': 'embedded in authenticated Yosys executable; no external plugin path assumed'}
        require(run(['lake','build','opentpu-gen'],work/'build.log',600)==0,'Generator build failed')
        run_generator(gen)
        projected={name:small_json(work/(name+'.json')) for name in EXPECTED}
        require(projected==EXPECTED,'Actual Lean production projection differs from audited constants')
        require((work/'gen1.sv').read_bytes()==(work/'gen2.sv').read_bytes(),'Gen1/Gen2 Control hardware differs')
        record['projected_configs']=projected
        record['production_bundle_cli_parameters']=BUNDLE_CLI
        record['generation_sha256']={str(p):archive(p) for p in work.iterdir() if p.is_file() and p.name!='summary.json'}
        save(work/'summary.json',record)
        for name in ('gen1','bundle'):
            require(all(sha256(Path(p))==h for p,h in record['generation_sha256'].items()),
                    'Generation artifacts changed before proof')
            native = work/(name+'.sv')
            record['proofs'].append(prove(work/(name+'-proof'),native,projected[name],str(tool),
                expected_native_digest=record['generation_sha256'][str(native)]))
            save(work/'summary.json',record)
        record['proofs'].append(prove(work/'mutation',work/'gen1.sv',projected['gen1'],str(tool),True,
            record['generation_sha256'][str(work/'gen1.sv')]))
        record['bindings']={'gen1':'gen1-proof','gen2':'gen1-proof','bundle':'bundle-proof'}
        require(all(sha256(Path(p))==h for p,h in before.items()),'Qualification sources changed')
        require(sha256(tool)==record['yosys']['sha256'],'Yosys executable changed')
        record['status']='passed'
    except BaseException as error:
        record['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        record['elapsed_seconds']=time.monotonic()-started
        record['changed_sources']=[p for p,h in before.items() if not Path(p).is_file() or sha256(Path(p))!=h]
        record['changed_generation']=[p for p,h in record.get('generation_sha256',{}).items()
            if not Path(p).is_file() or sha256(Path(p))!=h]
        if record['changed_sources'] or record['changed_generation']:record['status']='incomplete'
        save(work/'summary.json',record);archive(work/'summary.json')
        print(json.dumps({k:record[k] for k in ('status','elapsed_seconds')}),flush=True)
    return 0 if record['status']=='passed' else 1

if __name__=='__main__':sys.exit(main())
