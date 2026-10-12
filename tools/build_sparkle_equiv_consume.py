"""Build experimental, guarded gold-consuming equiv_make from pinned Yosys v0.69.

Build alone does not qualify production proof use. The source transformation leaves
matching, undriven handling, rewiring, and equivalence generation byte-identical.
Only input guards, pass naming/help and module copy/ownership change. MIT notices
remain in the vendored source and generated plugin. Run under sparkle_bounded.py.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'tools/yosys_equiv_consume/upstream-equiv_make.cc'
KERNEL = ROOT / 'tools/yosys_equiv_consume/upstream-rtlil.cc'
PINNED = {
    'upstream-equiv_make.cc': '8847304d0310d538cd6ec9f9537edc81e9dc8d90ca21f2a695c99256da4adfb7',
    'upstream-rtlil.cc': '140b9be6f834a294103a601ed8ca2342d84f6c53079f7b9def3dc4146f0866b1'}
GUARD = r'''
		// Experimental destructive mode. Reject every state cloneInto would
		// discard or whose observers could distinguish in-place ownership.
		if (args.size() != 4 || args[1].empty() || args[2].empty() || args[3].empty() ||
		    args[1][0] == '-' || args[2][0] == '-' || args[3][0] == '-')
			log_cmd_error("equiv_make_consume supports exactly three module names and no flags.\n");
		if (RTLIL::escape_id(args[1]) == RTLIL::escape_id(args[2]) ||
		    RTLIL::escape_id(args[1]) == RTLIL::escape_id(args[3]) ||
		    RTLIL::escape_id(args[2]) == RTLIL::escape_id(args[3]))
			log_cmd_error("equiv_make_consume requires distinct gold, gate, and output names.\n");
		if (design->modules_.size() != 2 || !design->full_selection() ||
		    design->flagBufferedNormalized || !design->monitors.empty() ||
		    !design->bindings_.empty() || design->refcount_modules_ != 0)
			log_cmd_error("equiv_make_consume requires exactly two fully selected, unbuffered, unobserved modules.\n");
		for (auto mod : design->modules()) {
			if (!mod->monitors.empty() || !mod->bindings_.empty() ||
			    mod->refcount_wires_ != 0 || mod->refcount_cells_ != 0 ||
			    !mod->avail_parameters.empty() || !mod->parameter_default_values.empty() ||
			    !mod->buf_norm_cell_queue.empty() || !mod->buf_norm_cell_port_queue.empty() ||
			    !mod->buf_norm_wire_queue.empty() || !mod->pending_deleted_cells.empty() ||
			    !mod->buf_norm_connect_index.empty())
				log_cmd_error("equiv_make_consume rejects parameters, observers, bindings, or buffered module bookkeeping.\n");
			for (auto wire : mod->wires())
				if (wire->known_driver())
					log_cmd_error("equiv_make_consume rejects cached wire drivers.\n");
			for (auto cell : mod->cells())
				if (design->module(cell->type) != nullptr || cell->type.empty() || cell->type.str()[0] != '$')
					log_cmd_error("equiv_make_consume requires flat internal cells only.\n");
		}
'''


def require(ok, message):
    if not ok: raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def replace_one(text, old, new):
    require(text.count(old) == 1, 'Pinned transformation anchor changed: ' + old[:100])
    return text.replace(old, new, 1)


def transform(original):
    text = replace_one(original, 'Pass("equiv_make", "prepare a circuit for equivalence checking")',
        'Pass("equiv_make_consume", "experimental in-place gold equivalence preparation")')
    start = text.index('\tvoid help() override\n')
    end = text.index('\tvoid execute(', start)
    text = text[:start] + '''\tvoid help() override
\t{
\t\tlog("\\n    equiv_make_consume gold_module gate_module equiv_module\\n\\n");
\t\tlog("Experimental: consumes gold in place; exactly two flat modules; no flags.\\n");
\t\tlog("Matching, undriven handling and equivalence obligations use pinned Yosys v0.69.\\n");
\t}
''' + text[end:]
    text = replace_one(text, '\t\tEquivMakeWorker worker;\n', GUARD + '\n\t\tEquivMakeWorker worker;\n')
    text = replace_one(text, '\t\tModule *gold_clone = gold_mod->clone();\n',
        '\t\tgold_mod->fixup_ports(); // same normalization as stock gold cloneInto\n'
        '\t\tModule *gold_clone = gold_mod; // consumed, never copied or deleted\n')
    text = replace_one(text, '\t\tgold_clone->cloneInto(equiv_mod);\n', '')
    text = replace_one(text, '\t\tdelete gold_clone;\n', '')
    text = replace_one(text, '\t\tworker.equiv_mod = design->addModule(RTLIL::escape_id(args[argidx+2]));\n',
        '\t\tworker.equiv_mod = worker.gold_mod;\n'
        '\t\tdesign->rename(worker.equiv_mod, RTLIL::escape_id(args[argidx+2]));\n')
    # Explicit invariant: the complete proof-construction algorithm is unchanged.
    first, last = '\tvoid add_eq_assertion(', '\nstruct EquivMakePass'
    require(original[original.index(first):original.index(last)] == text[text.index(first):text.index(last)],
            'Equivalence worker semantics changed')
    return text


def build(work):
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    work = Path(work).resolve()
    require(not work.exists(), 'Build directory must be new to preserve evidence')
    for path in [UPSTREAM, KERNEL]: require(sha(path) == PINNED[path.name], 'Pinned upstream source differs')
    work.mkdir(parents=True)
    source, plugin = work / 'equiv_make_consume.cc', work / 'equiv_make_consume.so'
    original = UPSTREAM.read_text(); generated = transform(original)
    source.write_text(generated)
    patch = work / 'source.patch'
    patch.write_text(''.join(difflib.unified_diff(original.splitlines(keepends=True), generated.splitlines(keepends=True),
                                                fromfile='upstream-equiv_make.cc', tofile='equiv_make_consume.cc')))
    config = Path(shutil.which('yosys-config') or '').resolve()
    yosys = Path(shutil.which('yosys') or '').resolve()
    require(config.is_file() and yosys.is_file(), 'Yosys toolchain unavailable')
    compiler = Path(subprocess.check_output([str(config), '--cxx'], text=True).strip()).resolve()
    require(compiler.is_file(), 'Resolved compiler unavailable')
    flags = {name: shlex.split(subprocess.check_output([str(config), name], text=True))
             for name in ['--cxxflags', '--ldflags', '--libs']}
    before = {str(p): sha(p) for p in [UPSTREAM, KERNEL, Path(__file__).resolve(), source, patch, config, yosys, compiler]}
    command = [str(compiler), *flags['--cxxflags'], *flags['--ldflags'], '-o', str(plugin),
               '-shared', str(source), *flags['--libs']]
    record = {'status': 'incomplete', 'scope': __doc__, 'input_sha256': before, 'command': command,
              'compiler': str(compiler), 'config_flags': flags,
              'upstream_urls': ['https://raw.githubusercontent.com/YosysHQ/yosys/v0.69/passes/equiv/equiv_make.cc',
                                'https://raw.githubusercontent.com/YosysHQ/yosys/v0.69/kernel/rtlil.cc']}
    manifest = work / 'build.json'; manifest.write_text(json.dumps(record, indent=2) + '\n')
    with (work / 'build.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    require(all(sha(path) == digest for path, digest in before.items()), 'Build input changed')
    record.update(status='built_not_qualified', plugin_sha256=sha(plugin),
                  yosys_version=subprocess.check_output([str(yosys), '-V'], text=True).strip())
    manifest.write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('work', type=Path)
    args = parser.parse_args(); print(json.dumps(build(args.work), indent=2))


if __name__ == '__main__': main()
