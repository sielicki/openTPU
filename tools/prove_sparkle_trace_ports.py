"""Trace complete-controller proof with two exactly matched RAM primitives.

Run only inside sparkle_bounded.py. No reset, event, address or queue occupancy
assumptions. All RAM inputs and controller next-state/output bits are checked.
Equal arbitrary RAM contents are preserved by matching primitive semantics and
matching writes. Reference-unspecified initialization admits native refinement.
"""
import argparse
import gc
import json
from pathlib import Path
import re
import shutil
import subprocess
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_compiled_lean import import_closure, run_generator
from sparkle_provenance import ROOT, archive, sha256
from sparkle_transition import expose_steps, step_miter
from sparkle_mxu_transition import prune_unobserved_register_bits

RAM_PORTS = {'RD_CLK':'input', 'RD_EN':'input', 'RD_ARST':'input',
             'RD_SRST':'input', 'RD_ADDR':'input', 'RD_DATA':'output',
             'WR_CLK':'input', 'WR_EN':'input', 'WR_ADDR':'input', 'WR_DATA':'input'}


def require(ok, message):
    if not ok: raise ValueError(message)


def freeze(observed, paths):
    for path in paths:
        path = Path(path).resolve()
        require(path.is_file(), 'Missing proof input: ' + str(path))
        digest = sha256(path)
        require(str(path) not in observed or observed[str(path)] == digest,
                'Proof input changed: ' + str(path))
        observed[str(path)] = digest


def frontend_plugins(text):
    """Authenticate actual plugin inventory; the workspace frontend is built in.

    Refuse an unfamiliar plugin-list format rather than inventing a library path.
    Explicit plugin paths from the tool's inventory are relative to its cwd ROOT.
    """
    require('read_slang [options]' in text, 'read_slang frontend unavailable')
    if 'No plugins loaded.' in text:
        require('Loaded plugins:' not in text, 'Ambiguous frontend inventory')
        return []
    require(text.count('Loaded plugins:') == 1, 'Unsupported plugin inventory')
    rows = text.split('Loaded plugins:',1)[1].split('\n\n',1)[0].splitlines()
    paths = []
    for row in rows:
        if not row.strip(): continue
        path = Path(row.strip())
        if not path.is_absolute(): path = ROOT/path
        require(path.is_file(), 'Cannot authenticate reported plugin: '+row.strip())
        paths.append(path.resolve())
    require(bool(paths) and len(set(paths)) == len(paths), 'Empty/duplicate plugin inventory')
    return paths


def cut_memories(raw, config):
    depth, qd, _ = config
    require(set(raw['modules']) == {'gold', 'gate'}, 'Unexpected extracted modules')
    result = []
    for name, size, width in [('qm', qd, 1277), ('mem', depth, 64)]:
        pair = [raw['modules'][side]['cells'].get(name) for side in ('gold', 'gate')]
        require(all(c is not None and c['type'] == '$mem_v2' for c in pair), 'Missing RAM ' + name)
        parameters = [{k:v for k,v in c['parameters'].items() if k != 'MEMID'} for c in pair]
        require(parameters[0] == parameters[1], 'RAM semantic parameters differ: ' + name)
        p = parameters[0]
        for key, expected in [('SIZE',size), ('WIDTH',width), ('ABITS',(size-1).bit_length()),
                              ('RD_PORTS',1), ('WR_PORTS',1), ('RD_CLK_ENABLE',0),
                              ('WR_CLK_ENABLE',1), ('WR_CLK_POLARITY',1), ('OFFSET',0)]:
            require(int(p[key], 2) == expected, 'Unexpected RAM parameter: ' + name + '.' + key)
        widths = {port:len(bits) for port,bits in pair[0]['connections'].items()}
        expected_widths = {'RD_CLK':1,'RD_EN':1,'RD_ARST':1,'RD_SRST':1,
                           'RD_ADDR':(size-1).bit_length(),'RD_DATA':width,
                           'WR_CLK':1,'WR_EN':width,'WR_ADDR':(size-1).bit_length(),'WR_DATA':width}
        require(widths == expected_widths, 'RAM pin widths differ from contract')
        for side, cell in zip(('gold','gate'),pair):
            m = raw['modules'][side]
            require(cell['port_directions'] == RAM_PORTS and set(cell['connections']) == set(RAM_PORTS),
                    'RAM pin inventory/direction mismatch')
            require({k:len(v) for k,v in cell['connections'].items()} == widths, 'RAM pin width mismatch')
            require(cell['connections']['WR_CLK'] == m['ports']['clk']['bits'], 'Unsupported RAM clock')
            for port, direction in RAM_PORTS.items():
                bits = cell['connections'][port]; alias = 'ram_' + name + '_' + port
                require(alias not in m['ports'] and alias not in m['netnames'], 'RAM boundary collision')
                if direction == 'output':
                    require(all(type(b) is int for b in bits) and len(set(bits)) == len(bits), 'Aliased/constant RAM output')
                    require(not any(set(bits).intersection(p['bits']) for p in m['ports'].values()
                                    if p['direction'] == 'input'), 'RAM output overlaps input')
                    for other_name, other in m['cells'].items():
                        if other_name == name: continue
                        require(not any(set(bits).intersection(other['connections'][pin])
                                        for pin,d in other['port_directions'].items() if d == 'output'),
                                'RAM output has another driver')
                m['ports'][alias] = {'direction':'input' if direction == 'output' else 'output','bits':bits}
                m['netnames'][alias] = {'hide_name':0,'bits':bits,'attributes':{}}
            del m['cells'][name]
        result.append({'name':name,'size':size,'width':width,'parameters':p,'pin_widths':widths})
    require(all(c['type'] != '$mem_v2' for m in raw['modules'].values() for c in m['cells'].values()),
            'Unmatched extra RAM')
    return result


def state_pairs(raw):
    """All DFF bits, including unobservable matched bits; no state pruning."""
    q = {}; init = {}; covered = {s:set() for s in ('gold','gate')}
    for side,m in raw['modules'].items():
        bits = [b for c in m['cells'].values() if c['type'] == '$dff' for b in c['connections']['Q']]
        require(all(type(b) is int for b in bits) and len(bits) == len(set(bits)), 'Bad DFF state')
        q[side] = set(bits); init[side] = {}
        for net in m['netnames'].values():
            value = net.get('attributes',{}).get('init')
            if value is None: continue
            require(len(value) == len(net['bits']), 'Malformed initial state')
            for bit, val in zip(net['bits'],reversed(value)):
                if bit not in q[side] or val == 'x': continue
                require(val in '01', 'Unsupported initial state')
                require(bit not in init[side] or init[side][bit] == val, 'Conflicting initial aliases')
                init[side][bit] = val
    gold, gate = raw['modules']['gold'], raw['modules']['gate']
    states = {}; mapping = []; refinements = 0
    for name, net in sorted(gate['netnames'].items(), key=lambda item:(-len(item[1]['bits']),item[0])):
        if name.startswith('$'): continue
        target = 'rdata' if name == 'rdata_q' else name
        if target not in gold['netnames']: continue
        nb, gb = net['bits'], gold['netnames'][target]['bits']
        if len(nb) != len(gb): continue
        pairs = [(g,n) for g,n in zip(gb,nb) if n in q['gate'] and n not in covered['gate']]
        if not pairs: continue
        require(all(g in q['gold'] and g not in covered['gold'] for g,n in pairs), 'State relation overlap/width mismatch: '+name)
        for g,n in pairs:
            gi,ni = init['gold'].get(g,'x'),init['gate'].get(n,'x')
            require(gi == 'x' or gi == ni, 'Defined reference initialization differs')
            refinements += gi == 'x' and ni != 'x'
        alias = 'paired_' + str(len(states)); states[alias] = len(pairs)
        for side,bits in [('gold',[g for g,n in pairs]),('gate',[n for g,n in pairs])]:
            require(alias not in raw['modules'][side]['netnames'], 'State alias collision')
            raw['modules'][side]['netnames'][alias] = {'hide_name':0,'bits':bits,'attributes':{}}
            covered[side].update(bits)
        mapping.append({'native':name,'reference':target,'bits':len(pairs),'alias':alias})
    require(covered == q, 'Unpaired controller state; no pruning permitted')
    return states, {'mapping':mapping,'native_initial_refinement_bits':refinements}


def exclude_dead_perf_fields(raw):
    """Only unmatched native perf busy/ret/mac/starve/deny pipeline copies.

    Slang omits these unused reference FFs. Protect every pair of matching FF
    bits before conservative transition liveness, including all RAM input pins.
    A new consumer of any allowed bit keeps it live and makes the guard fail.
    """
    modules = raw['modules']
    q = {s:{b for c in m['cells'].values() if c['type'] == '$dff'
             for b in c['connections']['Q']} for s,m in modules.items()}
    protected = {s:set() for s in modules}
    for name,net in modules['gate']['netnames'].items():
        target = 'rdata' if name == 'rdata_q' else name
        gold = modules['gold']['netnames'].get(target,{}).get('bits',[])
        if len(gold) != len(net['bits']): continue
        for g,n in zip(gold,net['bits']):
            if g in q['gold'] and n in q['gate']:
                protected['gold'].add(g); protected['gate'].add(n)
    expected = {b for name in ('pr','ev')
                for b in modules['gate']['netnames'][name]['bits'][837:847]}
    require(len(expected) == 20 and expected <= q['gate'] and
            not expected.intersection(protected['gate']), 'Unexpected dead perf field identities')
    counts = prune_unobserved_register_bits(raw,protected)
    after = {s:{b for c in m['cells'].values() if c['type'] == '$dff'
                 for b in c['connections']['Q']} for s,m in modules.items()}
    removed = {s:sorted(q[s]-after[s]) for s in modules}
    require(not removed['gold'] and set(removed['gate']) == expected,
            'Unexpected removed state or live perf field; no other pruning allowed')
    return {'counts':counts,'q_ids':removed,
            'native_fields':{'pr':list(range(837,847)),'ev':list(range(837,847))},
            'scope':'Only unmatched, structurally unobservable perf busy/ret/mac/starve/deny copies; all paired state protected.'}


def mutate(text, mode, config):
    if mode == 'write_data':
        old = 'mem[wp] <= r_rec;'; new = "mem[wp] <= r_rec ^ 64'd1;"
    elif mode == 'read_address':
        aw = (config[0]-1).bit_length()
        old = f'assign rd = mem[raddr[{aw-1}:0]];'
        new = f"assign rd = mem[raddr[{aw-1}:0] ^ {aw}'d1];"
    elif mode == 'queue_write':
        matches = list(re.finditer(r'qm\[q_t\] <= ([^;]+);',text))
        require(len(matches) == 1, 'Queue write mutation target differs')
        old = matches[0].group(); new = old[:-1] + " ^ 1277'd1;"
    else: raise ValueError('Unknown mutation')
    require(text.count(old) == 1, 'Mutation target differs')
    return text.replace(old,new)


def call(script, timeout=600):
    log = script.with_suffix('.log')
    with log.open('w') as stream:
        result = subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,
                                stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
    return result.returncode,log


def prove(config, output, mutation=None):
    bounded_context(); output = Path(output).resolve()
    require(not output.exists(), 'Preserve existing evidence'); output.mkdir(parents=True)
    status = {'status':'incomplete','config':list(config),'mutation':mutation,'scope':__doc__}
    path = output/'summary.json'; observed = {}
    def save(): path.write_text(json.dumps(status,indent=2)+'\n')
    save()
    try:
        depth,qd,win = config
        require(all(v >= 2 and v&(v-1) == 0 for v in (depth,qd)) and 0 <= win <= 16,'Invalid Trace config')
        native = output/'native.sv'; gen = output/'Generate.lean'
        gen.write_text('import OpenTPU.Trace\ndef main : IO Unit := do\n'
            f'  IO.FS.writeFile {json.dumps(str(native))} (← IO.ofExcept (OpenTPU.Trace.toVerilog ⟨{depth},{qd},{win}⟩))\n')
        sources = [gen,Path(__file__).resolve(),*[p for _,p in import_closure(gen).values()],
                   ROOT/'rtl/boards/ypcb-00338/otpu_trace.sv',ROOT/'rtl/top/otpu_pkg.sv',
                   *[ROOT/'tools'/n for n in ['sparkle_compiled_lean.py','sparkle_provenance.py',
                    'sparkle_transition.py','sparkle_mxu_transition.py','check_sparkle_fpga_top_complete.py','sparkle_bounded.py']]]
        yosys = Path(shutil.which('yosys')).resolve()
        sources += [yosys]
        freeze(observed,sources); status['input_sha256'] = observed; save()
        for source in sources: archive(source)
        frontend = output/'frontend.log'
        with frontend.open('w') as stream:
            subprocess.run(['yosys','-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,
                           stdout=stream,stderr=subprocess.STDOUT,check=True)
        plugins = frontend_plugins(frontend.read_text())
        sources += plugins
        freeze(observed,[frontend,*plugins])
        status['frontend'] = {'yosys':str(yosys),'plugins':list(map(str,plugins)),
                              'inventory_sha256':sha256(frontend)}
        for source in [frontend,*plugins]: archive(source)
        save()
        subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,check=True)
        run_generator(gen); freeze(observed,sources)
        status['generation_sha256'] = json.loads(gen.with_suffix('.runner.json').read_text())['source_sha256']
        if mutation:
            original = output/'native-unmutated.sv'; shutil.copyfile(native,original)
            native.write_text(mutate(native.read_text(),mutation,config))
        extract = output/'extract.ys'; collected = output/'collected.json'
        extract.write_text(f'read_slang --top otpu_trace -GDEPTH={depth} -GQD={qd} -GWIN={win} {ROOT}/rtl/top/otpu_pkg.sv {ROOT}/rtl/boards/ypcb-00338/otpu_trace.sv\n'
            f'rename otpu_trace gold\nread_slang --top otpu_trace_sparkle {native}\nrename otpu_trace_sparkle gate\n'
            f'proc\nopt_expr\nopt_clean\nmemory_collect\nwrite_json {collected}\n')
        rc,log = call(extract); require(rc == 0,'Extraction failed: '+str(log))
        raw = json.loads(collected.read_text()); ram = cut_memories(raw,config)
        excluded = exclude_dead_perf_fields(raw)
        states, relation = state_pairs(raw)
        transformed = expose_steps(raw,states); step_miter(transformed)
        steps = output/'steps.json'
        with steps.open('w') as stream: json.dump(transformed,stream)
        del raw,transformed; gc.collect()
        script = output/'proof.ys'
        script.write_text(f'read_json {steps}\nequiv_make gold gate equiv\nhierarchy -top equiv\n'
                          'opt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short\nequiv_status -assert\n')
        status.update(state_bits=sum(states.values()),ram_bits=sum(r['size']*r['width'] for r in ram),
                      ram_contracts=ram,state_relation=relation,dead_state_exclusion=excluded)
        freeze(observed,[p for p in output.rglob('*') if p.is_file() and p != path]); save()
        for p in observed: archive(p)
        rc,log = call(script,1800)
        text = log.read_text()
        require((rc == 1 and 'unproven $equiv cells' in text) if mutation else
                (rc == 0 and 'Equivalence successfully proven!' in text), 'Proof did not reach expected terminal result')
        freeze(observed,list(observed)); freeze(observed,[log])
        archive(log)
        status.update(status='mutation_rejected' if mutation else 'passed',returncode=rc,
                      proof_log_sha256=sha256(log)); save(); archive(path); return status
    except BaseException as error:
        status['error'] = repr(error)
        # Keep complete and partial artifacts as explicitly incomplete evidence.
        # Do not replace authenticated pre-run digests with post-error contents.
        partial = {}; failures = []
        for artifact in output.rglob('*'):
            if not artifact.is_file() or artifact == path: continue
            try: partial[str(artifact)] = archive(artifact)
            except Exception as failure: failures.append({'path':str(artifact),'error':repr(failure)})
        status['interrupted_artifact_sha256'] = partial
        if failures: status['archive_errors'] = failures
        save(); archive(path); raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='16384,32,16'); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mutation',choices=['write_data','read_address','queue_write'])
    a = p.parse_args(); result = prove(tuple(map(int,a.config.split(','))),a.output,a.mutation)
    print(result['status'],result['config'],result.get('state_bits'))
