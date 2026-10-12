"""Mock project-selection regression; execute through sparkle_bounded.py only.

No Vivado, Python verifier, Git subprocess, HDL generation, or project build runs.
The real create_project.tcl is sourced; only external commands/BD are mocked.
"""
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'boards/ypcb-00338/vivado/create_project.tcl'
LEGACY = '''rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/top/otpu_pkg.sv
rtl/mem/otpu_tmem.sv rtl/mem/otpu_actram.sv rtl/seq/otpu_seq.sv rtl/vpu/otpu_vtree.sv
rtl/dma/otpu_dma.sv rtl/mxu/otpu_mxu.sv rtl/tech/xilinx7/otpu_tech_dsp.sv
rtl/tech/generic/otpu_tech_ram.sv rtl/vpu/otpu_quant.sv rtl/vpu/otpu_se_comp.sv
rtl/vpu/otpu_se_tail.sv rtl/vpu/otpu_vpu.sv rtl/top/otpu_coll.sv rtl/top/otpu_slice.sv
rtl/shell/otpu_ctrl.sv rtl/shell/otpu_trace.sv
rtl/shell/otpu_board.sv rtl/mem/otpu_native_dram.sv
rtl/shell/otpu_afifo.sv rtl/shell/otpu_mem_ch.sv
rtl/shell/otpu_axi_split2.sv rtl/boards/ypcb-00338/otpu_native_sys.sv
rtl/boards/ypcb-00338/otpu_fpga_top_ld.sv'''.split()
MOCK = r'''
proc event {args} {
  puts "EVENT:[join [lmap x $args {binary encode hex [encoding convertto utf-8 $x]}] ,]"
}
rename exec real_exec
proc exec {args} {
  event exec {*}$args
  if {[lindex $args 0] eq "git"} {return fedcba9876543210}
  if {[lindex $args 0] ne "python3" || [file tail [lindex $args 1]] ne "prepare_sparkle_fpga_bundle.py"} {
    error "unexpected external execution: $args"
  }
  if {[info exists ::env(MOCK_PREFLIGHT_FAIL)]} {error "mock preflight rejected bundle"}
  return verified
}
rename source real_source
proc source {path} {
  if {[file tail $path] eq "bd_native.tcl"} {
    event bd $path
    set ::PCIE_GEN [expr {[info exists ::env(PCIE_GEN)] && $::env(PCIE_GEN) ne "" ? $::env(PCIE_GEN) : 2}]
    if {[info exists ::env(MOCK_BD_PCIE)]} {set ::PCIE_GEN $::env(MOCK_BD_PCIE)}
    return
  }
  uplevel 1 [list real_source $path]
}
proc create_project {args} {event create_project {*}$args}
proc set_param {args} {event set_param {*}$args}
proc config_ip_cache {args} {event config_ip_cache {*}$args}
proc current_project {} {return project}
proc current_fileset {} {return sources_1}
proc get_filesets {args} {return [lindex $args end]}
proc get_files {args} {return [lindex $args end]}
proc get_runs {args} {return [lindex $args end]}
proc set_property {name value object} {
  event property $name $value $object
  set ::properties($name,$object) $value
}
proc get_property {name object} {
  if {[info exists ::properties($name,$object)]} {return $::properties($name,$object)}
  if {$name eq "FILE_TYPE"} {return TCL}
  error "unmocked property: $name $object"
}
proc add_files {args} {event add_files {*}$args}
proc make_wrapper {args} {event make_wrapper {*}$args}
rename glob real_glob
proc glob {args} {return [lindex $args end]}
set argv [lrange $argv 1 end]
real_source $::env(MOCK_PROJECT)
'''


def run_project(tmp_path, native=True, args=None, extra_env=None):
    script = tmp_path / 'mock.tcl'
    script.write_text(MOCK)
    bundle = tmp_path / 'bundle'
    bundle.mkdir(exist_ok=True)
    (bundle / 'manifest.json').write_text('{"mock":true}\n')
    (tmp_path / 'project').mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ['OTPU_SPARKLE_BUNDLE', 'PCIE_GEN', 'ULANES', 'OTPU_FAST', 'OTPU_IP_CACHE']
           and not k.startswith('MOCK_')}
    env['MOCK_PROJECT'] = str(PROJECT)
    if native: env['OTPU_SPARKLE_BUNDLE'] = str(bundle)
    env.update(extra_env or {})
    argv = args if args is not None else ['1066', str(tmp_path / 'project'), '4', '133.33', 'deadbeef', '2', '8', '4', '1', 'systolic']
    result = subprocess.run(['tclsh', str(script), 'placeholder', *argv], env=env,
                            text=True, capture_output=True)
    events = [[bytes.fromhex(x).decode() for x in line[6:].split(',')]
              for line in result.stdout.splitlines() if line.startswith('EVENT:')]
    return result, events, bundle


def properties(events, name):
    return [(e[2], e[3]) for e in events if e[:2] == ['property', name]]


def test_native_exact_selection_and_order(tmp_path):
    result, events, bundle = run_project(tmp_path)
    assert result.returncode == 0, result.stderr
    verify = next(e for e in events if e[:2] == ['exec', 'python3'])
    assert verify == ['exec', 'python3', str(ROOT / 'tools/prepare_sparkle_fpga_bundle.py'),
                      'verify', '--bundle', str(bundle), '--parameters',
                      '4', '4', '2', '2', '8', '8', '133333', '3735928559', '1066', '1', '2']
    assert events.index(verify) < next(i for i, e in enumerate(events) if e[0] == 'create_project')
    files = [e[-1] for e in events if e[:2] == ['add_files', '-norecurse']]
    assert files == [str(ROOT / 'boards/ypcb-00338/litedram/otpu_litedram.v'),
                     str(ROOT / 'boards/ypcb-00338/litedram/otpu_litedram_mem.init'),
                     str(ROOT / 'rtl/top/otpu_pkg.sv'), str(ROOT / 'rtl/vpu/otpu_fp.sv'),
                     str(bundle / 'native.sv'),
                     str(tmp_path / 'project/otpu.gen/sources_1/bd/otpu_bd/hdl/otpu_bd_wrapper.v')]
    constraints = [e[-1] for e in events if e[:3] == ['add_files', '-fileset', 'constrs_1']]
    assert constraints == [f'{bundle}/board.xdc {ROOT}/boards/ypcb-00338/litedram/otpu_litedram.xdc',
                           f'{bundle}/mem_channel.tcl {bundle}/top.tcl']
    assert properties(events, 'SCOPED_TO_REF') == [('otpu_mem_ch', f'{bundle}/mem_channel.tcl')]
    assert properties(events, 'PROCESSING_ORDER') == [('LATE', constraints[1])]
    assert properties(events, 'USED_IN_SYNTHESIS') == [('false', constraints[1])]
    assert ['set_param', 'general.maxThreads', '1'] in events
    generic = dict(s.split('=', 1) for s in properties(events, 'generic')[-1][0].split())
    assert generic == dict(MCOLS='4', ACT_ROWS='4', VPU_CL='2', LANES='8', CORE_KHZ='133333',
        BUILD_ID="32'hdeadbeef", DDR_MTS='1066', DSTEP="1'b1", MXU_IMPL='2', PCIE_GEN='2', ULANES='8')
    assert (tmp_path / 'project/sparkle-manifest.json').read_bytes() == (bundle / 'manifest.json').read_bytes()


def test_legacy_exact_selection(tmp_path):
    result, events, _ = run_project(tmp_path, native=False)
    assert result.returncode == 0, result.stderr
    assert not any(e[:2] == ['exec', 'python3'] for e in events)
    files = [e[-1] for e in events if e[:2] == ['add_files', '-norecurse']]
    assert files[2:-1] == [str(ROOT / p) for p in LEGACY]
    cons = ROOT / 'boards/ypcb-00338/constraints'
    assert properties(events, 'SCOPED_TO_REF') == [('otpu_mem_ch', f'{cons}/otpu_mem_ch.tcl')]
    assert properties(events, 'PROCESSING_ORDER') == [('LATE', f'{cons}/otpu_mem_ch.tcl {cons}/otpu_top_native.tcl')]
    constraints = [e[-1] for e in events if e[:3] == ['add_files', '-fileset', 'constrs_1']]
    assert constraints == [f'{cons}/otpu_top_ld.xdc {ROOT}/boards/ypcb-00338/litedram/otpu_litedram.xdc',
                           f'{cons}/otpu_mem_ch.tcl {cons}/otpu_top_native.tcl']
    assert 'ULANES=' not in properties(events, 'generic')[-1][0]


@pytest.mark.parametrize('hex_id,decimal', [('ffffffff', '4294967295'), ('00000008', '8'), ('80000000', '2147483648')])
def test_all_parameters_custom_geometry_clock_pcie(tmp_path, hex_id, decimal):
    args = ['1066', str(tmp_path / 'project'), '2', '125', hex_id, '4', '16', '8', '0', 'tree']
    result, events, _ = run_project(tmp_path, args=args, extra_env={'PCIE_GEN': '1', 'ULANES': '4'})
    assert result.returncode == 0, result.stderr
    verify = next(e for e in events if e[:2] == ['exec', 'python3'])
    assert verify[verify.index('--parameters')+1:] == ['2', '8', '4', '0', '16', '4', '125490', decimal, '1066', '0', '1']
    assert 'ULANES=4' in properties(events, 'generic')[-1][0]
    assert 'PCIE_GEN=1' in properties(events, 'generic')[-1][0]


def test_preflight_failure_before_project(tmp_path):
    result, events, _ = run_project(tmp_path, extra_env={'MOCK_PREFLIGHT_FAIL': '1'})
    assert result.returncode != 0 and 'mock preflight rejected' in result.stderr
    assert not any(e[0] in ['create_project', 'add_files', 'bd'] for e in events)


@pytest.mark.parametrize('index,value', [(8, '2'), (9, 'unknown')])
def test_bad_native_arguments_before_project(tmp_path, index, value):
    args = ['1066', str(tmp_path / 'project'), '4', '133.33', '1', '2', '8', '4', '1', 'systolic']
    args[index] = value
    result, events, _ = run_project(tmp_path, args=args)
    assert result.returncode != 0
    assert not any(e[0] in ['create_project', 'exec'] for e in events)


def test_bad_pcie_before_project(tmp_path):
    result, events, _ = run_project(tmp_path, extra_env={'PCIE_GEN': '3'})
    assert result.returncode != 0
    assert not any(e[0] in ['create_project', 'exec'] for e in events)


def test_bd_pcie_change_rejected(tmp_path):
    result, events, _ = run_project(tmp_path, extra_env={'MOCK_BD_PCIE': '1'})
    assert result.returncode != 0 and 'block design PCIe generation changed' in result.stderr
    assert not properties(events, 'generic')


def test_default_git_build_id_forwarded(tmp_path):
    result, events, _ = run_project(tmp_path, args=['1066', str(tmp_path / 'project')])
    assert result.returncode == 0, result.stderr
    verify = next(e for e in events if e[:2] == ['exec', 'python3'])
    assert verify[verify.index('--parameters')+1:] == ['4', '4', '2', '2', '8', '8', '133333', '4275878552', '1066', '1', '2']


def test_legacy_removes_native_marker(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'sparkle-manifest.json').write_text('{}')
    result, _, _ = run_project(tmp_path, native=False)
    assert result.returncode == 0, result.stderr
    assert not (project / 'sparkle-manifest.json').exists()


def run_build_preflight(tmp_path, native=True, marker=True, jobs='1', fail=False,
                        generics=None, reject_values=False):
    out = tmp_path / 'project'
    out.mkdir()
    if marker: (out / 'sparkle-manifest.json').write_text('{}')
    env = {k: v for k, v in os.environ.items() if k != 'OTPU_SPARKLE_BUNDLE' and not k.startswith('MOCK_')}
    if native: env['OTPU_SPARKLE_BUNDLE'] = str(tmp_path / 'bundle')
    if fail: env['MOCK_PREFLIGHT_FAIL'] = '1'
    if generics is not None:
        env['MOCK_GENERICS'] = generics
        env['PCIE_GEN'] = '2'
    env['MOCK_PROJECT'] = str(ROOT / 'boards/ypcb-00338/vivado/build.tcl')
    script = tmp_path / 'build-mock.tcl'
    # Stop exactly at the first real Vivado project operation; later build code is not mocked.
    hooks = 'proc open_project {args} {event open_project {*}$args; exit 0}\n'
    if generics is not None:
        hooks = r'''
proc open_project {args} {
  event open_project {*}$args
  set ::properties(generic,sources_1) $::env(MOCK_GENERICS)
}
rename file real_file
proc file {sub args} {
  if {$sub eq "mkdir" && [real_file tail [lindex $args end]] eq "reports"} {
    event qualified_pcie $::env(PCIE_GEN)
    exit 0
  }
  uplevel 1 [list real_file $sub {*}$args]
}
'''
    mock = MOCK
    if reject_values:
        mock = mock.replace('return verified',
            'if {[lsearch -exact $args --parameters] >= 0} {error "mock actual generic mismatch"}\n  return verified')
    script.write_text(mock.replace('real_source $::env(MOCK_PROJECT)', hooks + 'real_source $::env(MOCK_PROJECT)'))
    result = subprocess.run(['tclsh', str(script), 'placeholder', str(out), jobs, 'impl', ''],
                            env=env, text=True, capture_output=True)
    events = [[bytes.fromhex(x).decode() for x in line[6:].split(',')]
              for line in result.stdout.splitlines() if line.startswith('EVENT:')]
    return result, events


def test_project_reuse_preflight_before_open(tmp_path):
    result, events = run_build_preflight(tmp_path)
    assert result.returncode == 0, result.stderr
    assert events == [['exec', 'python3', str(ROOT / 'tools/prepare_sparkle_fpga_bundle.py'),
        'verify', '--bundle', str(tmp_path / 'bundle'), '--project', str(tmp_path / 'project')],
        ['set_param', 'general.maxThreads', '1'], ['open_project', str(tmp_path / 'project/otpu.xpr')]]


@pytest.mark.parametrize('native,marker,jobs,fail', [(True, False, '1', False),
    (False, True, '1', False), (True, True, '2', False), (True, True, '1', True)])
def test_project_reuse_rejected_before_open(tmp_path, native, marker, jobs, fail):
    result, events = run_build_preflight(tmp_path, native, marker, jobs, fail)
    assert result.returncode != 0
    assert not any(e[0] == 'open_project' for e in events)


def test_legacy_project_reuse(tmp_path):
    result, events = run_build_preflight(tmp_path, native=False, marker=False, jobs='8')
    assert result.returncode == 0, result.stderr
    assert events == [['open_project', str(tmp_path / 'project/otpu.xpr')]]


def run_launcher(tmp_path, options):
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    log = tmp_path / 'commands.log'
    for name in ['python3', 'vivado', 'docker']:
        script = fake_bin / name
        script.write_text('#!/bin/bash\nprintf "%s\\n" "CALL:' + name + '" "$@" >> "$MOCK_LOG"\n'
                          + ('exit "${MOCK_VERIFY_EXIT:-0}"\n' if name == 'python3' else 'exit 0\n'))
        script.chmod(0o755)
    git = fake_bin / 'git'
    git.write_text('#!/bin/bash\necho 1234abcd0123456789abcdef\n')
    git.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ['JOBS', 'VIVADO_DOCKER', 'STEP', 'MXU',
        'ULANES', 'PCIE_GEN', 'MCOLS', 'ACT_ROWS', 'VPU_CL', 'LANES', 'CORE_MHZ', 'BUILD_ID',
        'DSTEP', 'OTPU_SPARKLE_BUNDLE', 'OTPU_IP_CACHE'] and not k.startswith('MOCK_')}
    env.update(PATH=f'{fake_bin}:{env["PATH"]}', OTPU_SPARKLE_BUNDLE=str(tmp_path / 'bundle'),
               OUT_DIR=str(tmp_path / 'out'), BUILD_ID='1234abcd', MOCK_LOG=str(log), OTPU_IP_CACHE='')
    env.update(options)
    # None explicitly removes the default build ID for STEP=impl checks.
    env = {k: v for k, v in env.items() if v is not None}
    result = subprocess.run(['bash', str(ROOT / 'boards/ypcb-00338/run_vivado.sh')], env=env,
                            text=True, capture_output=True)
    return result, log.read_text() if log.exists() else ''


@pytest.mark.parametrize('options', [{'VIVADO_DOCKER': 'image'}, {'JOBS': '2'}])
def test_launcher_rejects_resource_escape_before_tools(tmp_path, options):
    result, log = run_launcher(tmp_path, options)
    assert result.returncode == 2
    assert log == ''


def test_launcher_rejects_failed_preflight_before_vivado(tmp_path):
    result, log = run_launcher(tmp_path, {'MOCK_VERIFY_EXIT': '7'})
    assert result.returncode == 7
    assert 'CALL:python3' in log and 'CALL:vivado' not in log


def test_launcher_forwards_mxu_and_single_job(tmp_path):
    result, log = run_launcher(tmp_path, {'MXU': 'tree'})
    assert result.returncode == 0, result.stderr
    assert log.count('CALL:vivado') == 2
    assert log.index('CALL:python3') < log.index('CALL:vivado')
    assert '\ntree\n' in log
    assert f'\n{tmp_path}/out\n1\nfull\n' in log


PROJECT_GENERICS = ("MCOLS=4 ACT_ROWS=4 VPU_CL=2 MXU_IMPL=2 LANES=8 ULANES=8 "
                    "CORE_KHZ=133333 BUILD_ID=32'hffffffff DDR_MTS=1066 DSTEP=1'b1 PCIE_GEN=1")


def test_actual_project_generics_verified_and_gen1_restored(tmp_path):
    result, events = run_build_preflight(tmp_path, generics=PROJECT_GENERICS)
    assert result.returncode == 0, result.stderr
    checks = [e for e in events if e[:2] == ['exec', 'python3']]
    assert len(checks) == 2
    assert checks[1] == checks[0] + ['--parameters', '4', '4', '2', '2', '8', '8',
                                   '133333', '4294967295', '1066', '1', '1']
    opened = next(e for e in events if e[0] == 'open_project')
    assert events.index(checks[0]) < events.index(opened) < events.index(checks[1])
    assert events[-1] == ['qualified_pcie', '1']


@pytest.mark.parametrize('mutation', [
    lambda x: x + ' LANES=8',
    lambda x: x.replace(' ULANES=8', ''),
    lambda x: x + ' EXTRA=1',
    lambda x: x.replace('LANES=8', 'LANES'),
    lambda x: x.replace('LANES=8', 'LANES='),
])
def test_actual_project_generic_inventory_rejected(tmp_path, mutation):
    result, events = run_build_preflight(tmp_path, generics=mutation(PROJECT_GENERICS))
    assert result.returncode != 0
    assert 'project generic' in result.stderr
    assert len([e for e in events if e[:2] == ['exec', 'python3']]) == 1
    assert not any(e[0] == 'qualified_pcie' for e in events)


@pytest.mark.parametrize('old,new', [('LANES=8', 'LANES=16'),
    ("BUILD_ID=32'hffffffff", "BUILD_ID=32'h1"), ('PCIE_GEN=1', 'PCIE_GEN=2'),
    ("DSTEP=1'b1", "DSTEP=1'b0"), ('CORE_KHZ=133333', 'CORE_KHZ=100000')])
def test_actual_project_generic_mutation_verifier_failure(tmp_path, old, new):
    result, events = run_build_preflight(tmp_path, generics=PROJECT_GENERICS.replace(old, new),
                                         reject_values=True)
    assert result.returncode != 0 and 'mock actual generic mismatch' in result.stderr
    assert len([e for e in events if e[:2] == ['exec', 'python3']]) == 2
    assert not any(e[0] == 'qualified_pcie' for e in events)


@pytest.mark.parametrize('build_id', ['nothex', '123456789', '0x1234', '-1'])
def test_invalid_native_build_id_rejected_before_project(tmp_path, build_id):
    args = ['1066', str(tmp_path / 'project'), '4', '133.33', build_id]
    result, events, _ = run_project(tmp_path, args=args)
    assert result.returncode != 0
    assert not any(e[0] in ['create_project', 'exec'] for e in events)


@pytest.mark.parametrize('name', ['MCOLS', 'ACT_ROWS', 'VPU_CL', 'MXU', 'LANES', 'ULANES',
                                  'CORE_MHZ', 'BUILD_ID', 'DSTEP', 'PCIE_GEN'])
def test_native_impl_rejects_explicit_configuration_before_tools(tmp_path, name):
    options = {'STEP': 'impl', 'BUILD_ID': None, name: ''}
    result, log = run_launcher(tmp_path, options)
    assert result.returncode == 2
    assert f'omit {name}' in result.stderr
    assert log == ''


def test_native_impl_without_overrides_reuses_saved_configuration(tmp_path):
    result, log = run_launcher(tmp_path, {'STEP': 'impl', 'BUILD_ID': None})
    assert result.returncode == 0, result.stderr
    assert log.count('CALL:vivado') == 1
    assert 'create_project.tcl' not in log
    assert f'\n{tmp_path}/out\n1\nimpl\n' in log


@pytest.mark.parametrize('native,wns,whs,success', [
    (True, '', '0.1', False), (True, '0.1', '', False),
    (True, 'n/a', '0.1', False), (True, '-0.001', '0.2', False),
    (True, 'Inf', '0.1', False), (True, '-Inf', '0.1', False),
    (True, 'NaN', '0.1', False), (True, '0.1', 'Inf', False),
    (True, '0.1', '-Inf', False), (True, '0.1', 'NaN', False),
    (True, '0.1', '-0.001', False), (True, '0.0', '0.0', True),
    (True, '0.125', '0.001', True), (False, '-0.5', '-0.1', True)])
def test_native_bitstream_timing_guard(tmp_path, native, wns, whs, success):
    source = (ROOT / 'boards/ypcb-00338/vivado/build.tcl').read_text()
    marker = '# ---- bitstream, written from the routed design opened above\n'
    assert source.count(marker) == 1
    suffix = source.split(marker, 1)[1]
    write = 'write_bitstream -force $out/otpu.bit'
    assert suffix.count(write) == 1
    # Execute the actual guard through its first bitstream operation, without any synthesis.
    guard = suffix.split(write, 1)[0] + write + '\n'
    script = tmp_path / 'timing.tcl'
    script.write_text('set sparkle $::env(MOCK_NATIVE)\nset wns $::env(MOCK_WNS)\n'
                      'set whs $::env(MOCK_WHS)\nset out mock\n'
                      'proc write_bitstream {args} {puts BITSTREAM_ALLOWED}\n' + guard)
    env = os.environ | {'MOCK_NATIVE': str(int(native)), 'MOCK_WNS': wns, 'MOCK_WHS': whs}
    result = subprocess.run(['tclsh', str(script)], env=env, text=True, capture_output=True)
    assert (result.returncode == 0) == success, result.stderr
    assert ('BITSTREAM_ALLOWED' in result.stdout) == success
    if native and (wns.lower() in ['', 'n/a', 'inf', '-inf', 'nan'] or
                   whs.lower() in ['', 'n/a', 'inf', '-inf', 'nan']):
        assert 'missing finite numeric setup/hold timing results' in result.stderr
