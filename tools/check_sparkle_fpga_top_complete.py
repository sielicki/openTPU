"""Complete behavioral/physical FPGA ABI assembly and lint qualification.

Run ONLY inside tools/sparkle_bounded.py. This binds the FPGA shell to its exact
existing glue proof and checks complete native subsystem composition. Vendor IP
remains explicit blackboxes. Missing behavioral/physical leaf proofs are reported
as missing coverage, never inferred from successful lint or module equality.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from sparkle_bounded import cgroup, MAX_MIB, TASKS
from sparkle_compiled_lean import run_generator, import_closure
from sparkle_provenance import archive, sha256, verify
from prove_sparkle_fpga_top import CONFIGS, RTL, LD
from prove_sparkle_seq_logic import ROOT
from prove_sparkle_board_composition import header
from prove_sparkle_mxu_physical import dsp_model
from check_sparkle_board_native_abi import modules

WORK = ROOT / 'build/sparkle/check_fpga_top_complete'
VENDORS = {'IBUF', 'BUFG', 'IOBUF', 'otpu_bd_wrapper', 'otpu_litedram'}
SV_OPERATORS = (
    '>>>=', '<<<=', '>>>', '<<<', '===', '!==', '==?', '!=?', '&&&',
    '<<=', '>>=', '->>', '|->', '|=>', '#-#', '#=#', '[*', '[=', '[->',
    '**', '&&', '||', '==', '!=', '<=', '>=', '<<', '>>', '::', '++', '--',
    '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '~&', '~|', '~^', '^~',
    '->', '=>', '*>', '##', '+:', '-:', '.*', '``', '`"',
)
SV_TOKEN = re.compile(
    r"(?:[0-9]+)?'[sS]?[bBoOdDhH][0-9a-fA-F_xzXZ?]+|'[01xXzZ]|"
    r'[A-Za-z_$][A-Za-z0-9_$]*|[0-9]+|'
    + '|'.join(re.escape(op) for op in sorted(SV_OPERATORS, key=len, reverse=True))
    + r'|.')


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def bounded_context():
    group = cgroup()
    require(0 < int((group / 'memory.max').read_text()) <= MAX_MIB * 1024**2,
            'qualification requires the bounded memory ceiling')
    require((group / 'memory.swap.max').read_text().strip() == '0', 'swap must be disabled')
    require((group / 'memory.oom.group').read_text().strip() == '1', 'whole-job OOM required')
    require(int((group / 'pids.max').read_text()) == TASKS, 'task ceiling differs')
    quota, period = map(int, (group / 'cpu.max').read_text().split())
    require(quota == 2 * period, 'two-CPU quota required')
    require(os.environ.get('LEAN_NUM_THREADS') == '1', 'compiler parallelism must be one')


def manifest(paths):
    return {os.path.relpath(p, ROOT): sha256(p) for p in paths}


def same_concatenation(whole, parts):
    """Check the actual complete API output against independent component output."""
    with whole.open('rb') as combined:
        for path in parts:
            with path.open('rb') as source:
                while chunk := source.read(1024 * 1024):
                    require(combined.read(len(chunk)) == chunk, f'composition bytes differ: {whole}')
        require(not combined.read(1), f'extra composition bytes: {whole}')


def tokens(path, with_lines=False):
    """Small streaming SV lexer; preserve quoted strings and escaped identifiers."""
    block = False
    with path.open() as stream:
        for line_number, line in enumerate(stream, 1):
            i = 0
            while i < len(line):
                if block:
                    end = line.find('*/', i)
                    if end < 0:
                        break
                    block = False
                    i = end + 2
                elif line[i].isspace():
                    i += 1
                elif line.startswith('//', i):
                    break
                elif line.startswith('/*', i):
                    block = True
                    i += 2
                elif line[i] == '"':
                    end = i + 1
                    closed = False
                    while end < len(line):
                        if line[end] == '\\':
                            end += 2
                        elif line[end] == '"':
                            end += 1
                            closed = True
                            break
                        else:
                            end += 1
                    require(closed,
                            f'unsupported unterminated string in {path}')
                    yield (line_number, line[i:end]) if with_lines else line[i:end]
                    i = end
                elif line[i] == '\\':
                    end = i + 1
                    while end < len(line) and not line[end].isspace():
                        end += 1
                    yield (line_number, line[i:end]) if with_lines else line[i:end]
                    i = end
                else:
                    match = SV_TOKEN.match(line, i)
                    require(match is not None, f'tokenization failed: {path}')
                    yield (line_number, match[0]) if with_lines else match[0]
                    i += len(match[0])
    require(not block, f'unterminated comment: {path}')


def global_directives(path):
    """Retain global directive boundaries and each module's incoming context.

    Attributes belong to module identity, not the global macro environment.
    New physical helper definitions may therefore carry additional attributes.
    Directive line boundaries matter (especially for `define), while ordinary
    source line numbering and whitespace do not.
    """
    # These directives have compilation-unit effects even inside a module.
    # The generated circuit subset has no need for them in module bodies;
    # reject rather than silently omit their effects on later definitions.
    environment_directives = {
        'define', 'undef', 'undefineall', 'include', 'resetall', 'default_nettype',
        'timescale', 'celldefine', 'endcelldefine', 'unconnected_drive',
        'nounconnected_drive', 'begin_keywords', 'end_keywords', 'pragma', 'line',
        'default_decay_time', 'default_trireg_strength', 'delay_mode_distributed',
        'delay_mode_path', 'delay_mode_unit', 'delay_mode_zero', 'protect',
        'endprotect', 'protected', 'endprotected', 'uselib', 'enable_portfaults',
        'disable_portfaults', 'suppress_faults', 'nosuppress_faults', 'accelerate',
        'noaccelerate', 'expand_vectornets', 'noexpand_vectornets',
    }
    directives = []
    contexts = {}
    active = False
    pending_name = False
    directive = None
    directive_line = None
    body_macro_pending = False
    for line, token in tokens(path, with_lines=True):
        if body_macro_pending:
            require(token not in environment_directives,
                    f'unsupported compilation-unit directive inside module: `{token} in {path}')
            body_macro_pending = False
            continue
        if directive is not None:
            if line == directive_line:
                directive.append(token)
                continue
            if directive[-1] == '\\':
                require(line == directive_line + 1,
                        f'unsupported blank/comment-only directive continuation: {path}')
                directive.pop()  # Backslash-newline is a logical continuation.
                directive_line = line
                directive.append(token)
                continue
            directives.append(tuple(directive))
            directive = None
        if not active and token == '`':
            directive = [token]
            directive_line = line
        elif active and token == '`':
            body_macro_pending = True
        elif pending_name:
            contexts[token] = tuple(directives)
            pending_name = False
        elif token == 'module':
            active = True
            pending_name = True
        elif token == 'endmodule':
            active = False
    if directive is not None:
        require(directive[-1] != '\\', f'unterminated directive continuation: {path}')
        directives.append(tuple(directive))
    require(not body_macro_pending, f'incomplete module macro/directive: {path}')
    return tuple(directives), contexts


def require_same_global_directives(behavioral, physical):
    left, left_contexts = global_directives(behavioral)
    right, right_contexts = global_directives(physical)
    require(left == right, 'global preprocessor directives differ between bundles')
    for name in left_contexts.keys() & right_contexts.keys():
        require(left_contexts[name] == right_contexts[name],
                f'global preprocessor context differs for module {name}')


def module_hashes(path):
    result = {}
    active = None
    pending_name = False
    digest = None
    preamble = []
    for token in tokens(path):
        if active is None and not pending_name:
            if token != 'module':
                require(token != 'endmodule', f'unmatched endmodule in {path}')
                preamble.append(token)
                continue
            pending_name = True
            digest = hashlib.sha256()
            # Include module attributes and any preceding global directives;
            # these may affect hardware and must never disappear from identity.
            for item in preamble:
                data = item.encode()
                digest.update(len(data).to_bytes(8, 'little'))
                digest.update(data)
            preamble = []
        elif pending_name:
            require(re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*', token) is not None,
                    f'unsupported module identifier: {token}')
            require(token not in result, f'duplicate module {token} in {path}')
            active = token
            pending_name = False
        else:
            require(token != 'module', f'nested module in {path}')
        data = token.encode()
        digest.update(len(data).to_bytes(8, 'little'))
        digest.update(data)
        if token == 'endmodule':
            require(active is not None, f'unmatched endmodule in {path}')
            result[active] = digest.hexdigest()
            active = None
            digest = None
    require(active is None and not pending_name, f'unterminated module in {path}')
    require(not preamble, f'unsupported trailing top-level tokens in {path}')
    require(result, f'no module definitions: {path}')
    return result


def reference_header(path, name):
    # Read only the declaration, not the large generated LiteDRAM implementation.
    lines = []
    found = False
    with path.open() as source:
        for line in source:
            if re.match(r'\s*module\s+' + re.escape(name) + r'\b', line):
                found = True
            if found:
                lines.append(line)
                if ');' in line:
                    return header(''.join(lines))
    raise RuntimeError(f'missing declaration {name} in {path}')


def checked_vendor_interfaces(work, proof, resolved):
    key = next(k for k in proof['input_sha256'] if k.endswith('/boundaries.sv'))
    checked = modules((ROOT / resolved[key]).read_text())  # Small declaration-only file.
    require(VENDORS <= set(checked), 'qualified vendor declarations incomplete')
    current_ld = reference_header(LD, 'otpu_litedram') + '\nendmodule'
    require(re.findall(r'\S+', checked['otpu_litedram']) == re.findall(r'\S+', current_ld),
            'current LiteDRAM declaration differs from the qualified boundary')
    result = work / 'vendor-interfaces.sv'
    result.write_text('\n'.join('(* blackbox *) ' + checked[name] for name in sorted(VENDORS)) + '\n')
    return result, key


def extract_module_text(path, name):
    # Keep only one required module, never a whole generated bundle/library.
    lines = []
    found = False
    with path.open() as stream:
        for line in stream:
            if re.match(r'\s*module\s+' + re.escape(name) + r'\b', line):
                found = True
            if found:
                lines.append(line)
                if re.match(r'\s*endmodule\b', line):
                    return ''.join(lines)
    raise RuntimeError(f'missing complete module {name}: {path}')


def synthesis_slice(source, destination):
    # Evaluate only the known SYNTHESIS macro; preserve all other conditional
    # directives and their bodies for a conservative exact hardware comparison.
    stack = []
    def enabled():
        return all(frame['enabled'] for frame in stack)
    with destination.open('w') as output:
        for line in extract_module_text(source, 'otpu_slice').splitlines(keepends=True):
            opening = re.match(r'\s*`(ifdef|ifndef)\s+([A-Za-z_][A-Za-z0-9_]*)\b', line)
            closing = re.match(r'\s*`(else|elsif|endif)\b', line)
            if opening:
                known = opening[2] == 'SYNTHESIS'
                if not known and enabled():
                    output.write(line)
                stack.append({'known': known, 'enabled': opening[1] == 'ifdef' if known else True,
                              'seen_else': False})
            elif closing:
                require(stack, 'unmatched Slice conditional terminator')
                frame = stack[-1]
                if closing[1] == 'endif':
                    stack.pop()
                    if not frame['known'] and enabled():
                        output.write(line)
                elif closing[1] == 'else':
                    require(not frame['seen_else'], 'duplicate Slice conditional else')
                    frame['seen_else'] = True
                    if frame['known']:
                        frame['enabled'] = not frame['enabled']
                    elif enabled():
                        output.write(line)
                else:
                    require(not frame['known'], 'unsupported elsif on SYNTHESIS condition')
                    require(not frame['seen_else'], 'Slice elsif follows else')
                    if enabled():
                        output.write(line)
            elif enabled():
                output.write(line)
    require(not stack, 'unbalanced Slice simulation preprocessor region')


def functional_dsp(work):
    model = dsp_model()
    text = extract_module_text(model, 'DSP48E1').split('module DSP48E1 (', 1)[1].rsplit('endmodule', 1)[0]
    prefix, timing = text.split('`ifdef YOSYS', 1)
    timing, suffix = timing.split('`endif', 1)
    require('`' not in timing and not re.search(
        r'\b(always|always_ff|always_comb|assign|initial|reg|wire)\b', timing),
        'DSP timing-only removal boundary changed')
    path = work / 'DSP48E1.sv'
    path.write_text('module DSP48E1 (' + prefix + suffix + 'endmodule\n')
    return model, path


def bind_physical_leaf(work, mxu_config, actual_modules, model, primitive):
    depth, columns, chain, implementation = mxu_config
    if implementation != 2:
        return {'status': 'not_applicable', 'reason': 'behavioral arithmetic selection'}
    directory = ROOT / 'build/sparkle/formal_mxu_physical_dot' / f'{depth}_{columns}_{chain}'
    path = directory / 'summary.json'
    if not path.exists():
        return {'status': 'missing', 'configuration': mxu_config,
                'reason': 'no exact matching physical dot proof; assembly/lint only'}
    proof = json.loads(path.read_text())
    require(proof.get('status') == 'passed', f'physical leaf proof incomplete: {path}')
    resolved = verify(proof['input_sha256'])
    require(sha256(model) == proof['dsp_model_sha256'], 'DSP model differs from physical proof')
    native_key = str((directory / 'native.sv').relative_to(ROOT))
    primitive_key = str((directory / 'DSP48E1.sv').relative_to(ROOT))
    require(sha256(primitive) == sha256(ROOT / resolved[primitive_key]),
            'functional DSP model differs from proof')
    proven = module_hashes(ROOT / resolved[native_key])
    require(all(actual_modules.get(k) == v for k, v in proven.items()),
            'physical FPGA dot/helper module differs from proof')
    return {'status': 'bound', 'configuration': mxu_config,
            'summary_sha256': archive(path), 'matched_modules': sorted(proven)}


def run_case(name, config):
    work = WORK / name
    work.mkdir(parents=True, exist_ok=True)
    for previous in work.rglob('*'):
        if previous.is_file():
            archive(previous)
    proof_path = ROOT / 'build/sparkle/formal_fpga_top' / name / 'summary.json'
    glue_sha256 = sha256(proof_path)
    proof = json.loads(proof_path.read_text())
    require(sha256(proof_path) == glue_sha256, 'glue proof summary changed while loading')
    require(proof.get('status') == 'passed' and proof['config'] == config,
            f'exact FPGA glue proof missing: {name}')
    resolved = verify(proof['input_sha256'])
    require(sha256(RTL) == proof['input_sha256'][str(RTL.relative_to(ROOT))],
            'current reference FPGA top differs from glue proof')
    gen = work / 'Generate.lean'
    gen.write_text(f'''import Lean
import OpenTPU.FpgaTopCompleteABI
open OpenTPU
def main : IO Unit := do
  let c : FpgaTop.Config := {config}
  IO.FS.writeFile "{work}/behavioral.sv" (← IO.ofExcept (FpgaTop.abiVerilog c))
  IO.FS.writeFile "{work}/physical.sv" (← IO.ofExcept (FpgaTop.physicalAbiVerilog c))
  IO.FS.writeFile "{work}/shell.sv" (← IO.ofExcept (FpgaTop.emitShell c))
  IO.FS.writeFile "{work}/system-behavioral.sv" (← IO.ofExcept (NativeSys.abiVerilog c.system))
  IO.FS.writeFile "{work}/system-physical.sv" (← IO.ofExcept (NativeSys.physicalAbiVerilog c.system))
  IO.FS.writeFile "{work}/mxu-physical.sv" (← IO.ofExcept (MxuPhysical.emit c.system.board.nativeSlice.mxu))
  IO.FS.writeFile "{work}/params.json" (Lean.Json.compress (Lean.toJson (c.parameters,c.system.parameters)))
  let m := c.system.board.nativeSlice.mxu
  IO.FS.writeFile "{work}/mxu-config.json" (Lean.Json.compress (Lean.toJson [m.d,m.columns,m.chainLength,m.implementation]))
''')
    sources = [path for _, path in import_closure(gen).values()] + [
        gen, Path(__file__).resolve(), ROOT / 'tools/sparkle_compiled_lean.py',
        ROOT / 'tools/sparkle_provenance.py', ROOT / 'tools/sparkle_bounded.py',
        ROOT / 'tools/prove_sparkle_fpga_top.py', ROOT / 'tools/prove_sparkle_slice.py',
        ROOT / 'tools/prove_sparkle_board_composition.py',
        ROOT / 'tools/prove_sparkle_mxu_physical.py', ROOT / 'tools/check_sparkle_board_native_abi.py',
        ROOT / 'rtl/top/otpu_pkg.sv', ROOT / 'rtl/vpu/otpu_fp.sv', RTL, LD,
        ROOT / 'lean-toolchain', ROOT / 'lake-manifest.json', ROOT / 'lakefile.lean']
    before = manifest(sources)
    for path in sources:
        archive(path)
    (work / 'generation-inputs.json').write_text(json.dumps(before, indent=2) + '\n')
    run_generator(gen)
    require(manifest(sources) == before, 'generation sources changed')
    shell = work / 'shell.sv'
    native_key = next(k for k in proof['input_sha256'] if k.endswith('/native.sv'))
    params_key = next(k for k in proof['input_sha256'] if k.endswith('/params.json'))
    require(sha256(shell) == sha256(ROOT / resolved[native_key]),
            'complete FPGA shell differs from exact qualified shell')
    params, projected = json.loads((work / 'params.json').read_text())
    require([params, projected] == json.loads((ROOT / resolved[params_key]).read_text()),
            'complete FPGA/subsystem parameters differ from exact glue proof')
    same_concatenation(work / 'behavioral.sv', [work / 'system-behavioral.sv', shell])
    same_concatenation(work / 'physical.sv', [work / 'system-physical.sv', shell])
    behavioral = module_hashes(work / 'behavioral.sv')
    physical = module_hashes(work / 'physical.sv')
    require_same_global_directives(work / 'behavioral.sv', work / 'physical.sv')
    mxu = module_hashes(work / 'mxu-physical.sv')
    mxu_config = json.loads((work / 'mxu-config.json').read_text())
    require(set(behavioral) <= set(physical), 'physical path drops a native module')
    changed = {k for k, v in behavioral.items() if physical[k] != v}
    expected = {'otpu_mxu_dot_sparkle', 'otpu_slice'} if mxu_config[3] == 2 else set()
    require(changed == expected, f'unexpected hardware/diagnostic module changes: {changed}')
    for mode in ['behavioral', 'physical']:
        synthesis_slice(work / (mode + '.sv'), work / ('slice-' + mode + '-synthesis.sv'))
    require(module_hashes(work / 'slice-behavioral-synthesis.sv') ==
            module_hashes(work / 'slice-physical-synthesis.sv'),
            'physical Slice wrapper changes synthesis-visible hardware')
    require(set(physical) == set(behavioral) | set(mxu), 'unexpected physical helper definitions')
    require(all(physical.get(k) == v for k, v in mxu.items()),
            'physical MXU differs from standalone physical builder')
    require(not VENDORS.intersection(physical), 'vendor hardware unexpectedly emitted')
    vendor, vendor_key = checked_vendor_interfaces(work, proof, resolved)
    model, primitive = functional_dsp(work)
    leaf = bind_physical_leaf(work, mxu_config, physical, model, primitive)
    for mode in ['behavioral', 'physical']:
        command = ['verilator', '--lint-only', '--top-module', 'otpu_fpga_top_ld',
                   '-Wno-fatal', '-DYOSYS', *[f'-G{k}={v}' for k, v in params],
                   str(ROOT / 'rtl/top/otpu_pkg.sv'), str(ROOT / 'rtl/vpu/otpu_fp.sv'), str(vendor)]
        if mode == 'physical':
            command.append(str(primitive))
        command.append(str(work / (mode + '.sv')))
        (work / (mode + '-lint-command.json')).write_text(json.dumps(command, indent=2) + '\n')
        with (work / (mode + '-lint.log')).open('w') as output:
            subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
    require(manifest(sources) == before, 'qualification sources changed after generation')
    require(sha256(proof_path) == glue_sha256, 'bound glue proof summary changed')
    files = [p for p in work.rglob('*') if p.is_file() and p.name != 'summary.json'] + [proof_path, model]
    for path in files:
        archive(path)
    result = {'status': 'passed', 'config': config, 'glue_proof_sha256': archive(proof_path),
              'glue_state_bits': proof['state_bits'], 'vendor_interfaces_from_proof': vendor_key,
              'behavioral_modules': len(behavioral), 'physical_modules': len(physical),
              'changed_modules': sorted(changed), 'physical_leaf': leaf,
              'behavioral_leaf_scope': 'No new behavioral child proofs claimed; exact shell and subsystem composition plus complete lint only.',
              'generation_sha256': before, 'input_sha256': manifest(files),
              'scope': __doc__}
    summary = work / 'summary.json'
    summary.write_text(json.dumps(result, indent=2) + '\n')
    archive(summary)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['all', *[name for name, _ in CONFIGS]], default='all')
    args = parser.parse_args()
    bounded_context()  # Refuse all build, emission, parsing and lint outside the gate.
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / 'summary.json'
    if summary.exists():
        archive(summary)
    records = []
    def report(status, error=None):
        summary.write_text(json.dumps({'status': status, 'results': records, 'error': error,
                                       'scope': __doc__}, indent=2) + '\n')
        archive(summary)
    report('incomplete')  # Remains incomplete if the bounded scope is killed.
    try:
        if (WORK / 'build.log').exists():
            archive(WORK / 'build.log')
        with (WORK / 'build.log').open('w') as output:
            subprocess.run(['lake', 'build', 'opentpu-gen', 'OpenTPU.FpgaTopCompleteABI'],
                           cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
        for name, config in CONFIGS:
            if args.case in ('all', name):
                records.append(run_case(name, config))
                report('incomplete')
        report('passed')
    except BaseException as error:
        report('incomplete', repr(error))
        raise


if __name__ == '__main__':
    main()
