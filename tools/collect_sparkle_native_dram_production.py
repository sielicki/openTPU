"""Exact production NativeDram RAM-preserving inventory; NOT a proof result.

Draft intended for installation in tools/. Run only through sparkle_bounded.py.
No RAM is cut or memory-mapped here. A successful inventory remains incomplete
until concrete memory induction and complete local-state/interface proofs pass.
"""
import argparse
import gc
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_compiled_lean import import_closure
from sparkle_provenance import archive, sha256
from prove_sparkle_trace_ports import frontend_plugins, RAM_PORTS

CONFIG = (128, 16, 32, 1, 4, 128, 64, 32)
NAMES = ('D', 'QD', 'WQD', 'CHASH', 'WGATHER', 'RD', 'AD', 'APF')
MAX_JSON_BYTES = 32 * 1024 * 1024


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as output:
        json.dump(value, output, indent=2)
        output.write('\n'); output.flush(); os.fsync(output.fileno())
    os.replace(temporary, path)


def run(command, log, timeout):
    process = None
    with log.open('w') as output:
        try:
            process = subprocess.Popen(command, cwd=ROOT, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            code = process.wait(timeout=timeout)
            require(code == 0, f'Command exited {code}; see {log}')
        finally:
            if process is not None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()


def snapshot(paths):
    return {str(Path(p).resolve()): archive(Path(p).resolve()) for p in paths}


def verify(record):
    require(all(sha256(Path(p)) == h for p,h in record.items()), 'Input changed during inventory')


def shapes():
    result = [('bt_q','bt_q',256,2,1), ('ao_q','ao_q',256,11,1)]
    for channel in range(2):
        for name,size,width,reads in [('qbm',32,554,1), ('qam',16,66,1),
            ('qwm',32,89,1), ('qwd',32,512,1), ('wam',32,25,1),
            ('whm',32,6,2), ('tgm',256,7,1), ('ram',64,512,1), ('wrm',32,512,1)]:
            result.append((f'g_mem[{channel}].{name}',f'{name}{channel}',size,width,reads))
        for bank in range(8):
            result.append((f'g_mem[{channel}].g_rb[{bank}].rbm',
                           f'rbm{channel}_{bank}',128,64,1))
    require(len(result) == 36 and sum(s*w for _,_,s,w,_ in result) == 314304,
            'Incorrect exact production RAM inventory')
    return result


def number(value):
    require(type(value) is str and set(value) <= {'0','1'} and value,
            'Non-binary RAM integer parameter')
    return int(value,2)


def read_order(module, cell, names, width):
    data = cell['connections']['RD_DATA']
    chunks = [data[i:i+width] for i in range(0,len(data),width)]
    result = []
    for name in names:
        require(name in module['netnames'], 'Missing read-port semantic alias: '+name)
        bits = module['netnames'][name]['bits']
        matches = [i for i,c in enumerate(chunks) if c == bits]
        require(len(matches) == 1, 'Ambiguous/missing memory read alias: '+name)
        result.append(matches[0])
    require(sorted(result) == list(range(len(chunks))), 'Read order is not a bijection')
    return result


def inventory(raw):
    require(set(raw['modules']) == {'gold','gate'}, 'Unexpected extracted modules')
    rows = []
    used = {side:set() for side in ('gold','gate')}
    for gold_name,gate_name,size,width,reads in shapes():
        row = {'reference':gold_name,'native':gate_name,'size':size,'width':width,
               'ram_state_bits':size*width,'read_ports':reads,'sides':{}}
        for side,name in [('gold',gold_name),('gate',gate_name)]:
            module = raw['modules'][side]
            # Exact names observed in the native emitter; do not use fuzzy matching.
            require(name in module['cells'], 'Missing architectural memory: '+side+':'+name)
            cell = module['cells'][name]
            require(cell['type'] == '$mem_v2', 'Architectural RAM not collected: '+name)
            parameters = cell['parameters']
            for key,value in [('SIZE',size),('WIDTH',width),('ABITS',(size-1).bit_length()),
                              ('RD_PORTS',reads),('WR_PORTS',1),('OFFSET',0),
                              ('RD_CLK_ENABLE',0),('WR_CLK_ENABLE',1),('WR_CLK_POLARITY',1)]:
                require(number(parameters[key]) == value, 'Unexpected '+side+':'+name+'.'+key)
            require(len(parameters['INIT']) == size*width and set(parameters['INIT']) == {'x'},
                    'Initialized architectural RAM needs a separate explicit base proof')
            require(cell['port_directions'] == RAM_PORTS, 'Unexpected RAM port inventory')
            pins = cell['connections']
            widths = {'RD_CLK':reads,'RD_EN':reads,'RD_ARST':reads,'RD_SRST':reads,
                      'RD_ADDR':reads*(size-1).bit_length(),'RD_DATA':reads*width,
                      'WR_CLK':1,'WR_EN':width,'WR_ADDR':(size-1).bit_length(),'WR_DATA':width}
            require({p:len(b) for p,b in pins.items()} == widths, 'RAM pin shape differs')
            require(pins['WR_CLK'] == module['ports']['clk']['bits'], 'Unexpected write clock')
            order = list(range(reads))
            if reads == 2:
                channel = int(gate_name[-1])
                names = ([f'wh_f[{channel}]',f'wh_n[{channel}]'] if side == 'gold'
                         else [f'wh_f{channel}',f'wh_n{channel}'])
                order = read_order(module,cell,names,width)
            row['sides'][side] = {'cell':cell,'canonical_read_order':order}
            used[side].add(name)
        rows.append(row)
    remaining = {}
    for side,module in raw['modules'].items():
        remaining[side] = {name:cell for name,cell in module['cells'].items()
                           if cell['type'].startswith('$mem') and name not in used[side]}
        require(all(c['type'] == '$mem_v2' for c in remaining[side].values()),
                'Uncollected residual memory cell')
    # No deletion, cut, pruning, or state substitution. Residual arrays must later
    # be memory-mapped and included in the exhaustive local-state correspondence.
    return {'architectural_memories':rows,'ram_state_bits':314304,
            'residual_memories_to_map':remaining,
            'ports':{s:m['ports'] for s,m in raw['modules'].items()},
            'cell_counts':{s:len(m['cells']) for s,m in raw['modules'].items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work',type=Path)
    parser.add_argument('--timeout',type=int,default=600)
    args = parser.parse_args()
    bounded_context()
    work = args.work.resolve()
    require(not work.exists(),'Fresh output directory required')
    require(args.timeout > 0,'Positive timeout required')
    work.mkdir(parents=True)
    summary = {'status':'incomplete','config':CONFIG,'phase':'start',
               'scope':'RAM-preserving inventory only; no equivalence claimed'}
    save(work/'summary.json',summary)
    try:
        def interrupted(signum, frame):
            raise RuntimeError('Interrupted by signal '+str(signum))
        signal.signal(signal.SIGTERM,interrupted)
        yosys = Path(shutil.which('yosys') or '').resolve()
        require(yosys.is_file(),'Yosys unavailable')
        runner = work/'Emit.lean'
        runner.write_text('import OpenTPU.NativeDram\nimport OpenTPU.Backend\nopen OpenTPU Sparkle.Backend.Verilog\n'
            'def main : IO Unit := do\n'
            '  let c : NativeDram.Config := ⟨128,16,32,true,4,128,64,32⟩\n'
            '  IO.ofExcept c.validate\n'
            f'  IO.FS.writeFile {json.dumps(str(work/"native.sv"))} (toVerilog (NativeDram.build c))\n')
        sources = [p for _,p in import_closure(runner).values()]
        sources += [runner,Path(__file__).resolve(),ROOT/'rtl/mem/otpu_native_dram.sv',
                    ROOT/'lakefile.lean',ROOT/'lean-toolchain',yosys]
        # Authenticate the exact imported Python closure, including helper dependencies.
        sources += list((ROOT/'tools').glob('*.py'))
        summary['input_sha256'] = snapshot(sources)
        save(work/'summary.json',summary)
        run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],work/'frontend.log',30)
        plugins = frontend_plugins((work/'frontend.log').read_text())
        summary['frontend_plugins'] = snapshot(plugins)
        run([str(yosys),'-V'],work/'yosys-version.log',30)
        run(['lake','build','opentpu-gen'],work/'build.log',args.timeout)
        command = [sys.executable,'-c',
                   'from sparkle_compiled_lean import run_generator; import sys; run_generator(sys.argv[1])',str(runner)]
        # Import helper via explicit repository tools path in child environment.
        old_path = os.environ.get('PYTHONPATH')
        os.environ['PYTHONPATH'] = str(ROOT/'tools') + (os.pathsep+old_path if old_path else '')
        try: run(command,work/'generate.log',args.timeout)
        finally:
            if old_path is None: os.environ.pop('PYTHONPATH',None)
            else: os.environ['PYTHONPATH'] = old_path
        verify(summary['input_sha256'])
        summary['generation_sha256'] = snapshot([runner,work/'native.sv',runner.with_suffix('.runner.json')])
        settings = ' '.join(f'-G{k}={v}' for k,v in zip(NAMES,CONFIG))
        script = work/'collect.ys'
        script.write_text(f'read_slang -D SYNTHESIS --allow-use-before-declare --top otpu_native_dram {settings} {ROOT}/rtl/mem/otpu_native_dram.sv\n'
            'rename otpu_native_dram gold\n'
            f'read_slang -D SYNTHESIS --top otpu_native_dram_sparkle {work}/native.sv\n'
            'rename otpu_native_dram_sparkle gate\nproc\nopt_expr\nopt_clean\nmemory_collect\n'
            f'write_json {work}/collected.json\n')
        summary['phase'] = 'memory_collect'
        summary['extraction_input_sha256'] = snapshot([script,work/'native.sv',yosys])
        save(work/'summary.json',summary)
        run([str(yosys),'-Q','-T','-s',str(script)],work/'collect.log',args.timeout)
        collected = work/'collected.json'
        summary['collected_sha256'] = snapshot([collected])
        require(collected.stat().st_size <= MAX_JSON_BYTES,
                'Collected netlist exceeds 32 MiB parse ceiling; use streaming inventory, do not raise limit')
        with collected.open() as source: raw = json.load(source)
        details = inventory(raw)
        save(work/'inventory.json',details)
        del details,raw
        gc.collect()
        for key in ['input_sha256','frontend_plugins','generation_sha256','extraction_input_sha256','collected_sha256']:
            verify(summary[key])
        summary.update(phase='inventory_complete',inventory_sha256=archive(work/'inventory.json'),
                       next='Review actual cells; prove RAM base/step and all local state/interfaces. No proof run here.')
    except BaseException as error:
        summary['error'] = type(error).__name__+': '+str(error)
        raise
    finally:
        save(work/'summary.json',summary)
    print('INCOMPLETE: inventory complete; 36 RAMs / 314304 bits preserved; equivalence pending',flush=True)


if __name__ == '__main__': main()
