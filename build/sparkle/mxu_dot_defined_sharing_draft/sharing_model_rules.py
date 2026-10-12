"""Fail-closed linkage of sharing rules to the installed Yosys source derivation."""
import json
from pathlib import Path
import re
import shutil
import subprocess
from defined_expression_sharing import RULES
from dot_initial_store import need

YOSYS=Path('/nix/store/4sxr7d1kf8v1wjkfkxhv7d0ssmvd64nf-yosys-0.69/bin/yosys')
DERIVATION=Path('/nix/store/f24p332m45cn9kfzi95i0sq7sjbbw85m-yosys-0.69.drv')
SOURCE_DERIVATION=Path('/nix/store/x2q2509a921d640gxy7chwkrbp7w8m39-source.drv')
SOURCE=Path('/nix/store/fiq6rwpyasp5f401gdaws45pl3biq68s-source')
SOURCE_NAR_SHA='563ca4e9a30ac27244136e6d43448a5907177c9c63a42568bbee077fc73e20be'
SATGEN_CC_SHA='ee9c3f7b6268f192ad33f8f9117ddde4fa683400d936afef483da6fb31c8c98b'
SATGEN_HEADER_SHA='a3cc919b23f8a5fe6794cc20699a29ae8c6070b6ed782b204eb44efe9583d86a'

MUL_BLOCK='''if (cell->type == ID($mul))
	{
		std::vector<int> a = importDefSigSpec(cell->getPort(ID::A), timestep);
		std::vector<int> b = importDefSigSpec(cell->getPort(ID::B), timestep);
		std::vector<int> y = importDefSigSpec(cell->getPort(ID::Y), timestep);
		extendSignalWidth(a, b, y, cell);

		std::vector<int> yy = model_undef ? ez->vec_var(y.size()) : y;

		std::vector<int> tmp(a.size(), ez->CONST_FALSE);
		for (int i = 0; i < int(a.size()); i++)
		{
			std::vector<int> shifted_a(a.size(), ez->CONST_FALSE);
			for (int j = i; j < int(a.size()); j++)
				shifted_a.at(j) = a.at(j-i);
			tmp = ez->vec_ite(b.at(i), ez->vec_add(tmp, shifted_a), tmp);
		}
		ez->assume(ez->vec_eq(tmp, yy));

		if (model_undef) {
			log_assert(arith_undef_handled);
			std::vector<int> undef_y = importUndefSigSpec(cell->getPort(ID::Y), timestep);
			undefGating(y, yy, undef_y);
		}
		return true;
	}'''

# These source anchors describe why zero input undefined masks force zero output
# masks. Full source/header files and derivations are also frozen, not just tokens.
ANCHORS=[
 'int undef_y_bit = ez->OR(undef_any_a, undef_any_b);',
 'std::vector<int> undef_y_bits(undef_y.size(), undef_y_bit);',
 'ez->assume(ez->vec_eq(undef_y_bits, undef_y));',
 'ez->vec_and(a, b)', 'ez->vec_or(a, b)', 'ez->vec_xor(a, b)',
 'ez->vec_add(a, b)', 'ez->vec_sub(a, b)',
 'std::vector<int> yX = ez->vec_or(undef_a, undef_b);',
 'cell->type.in(ID($eq), ID($ne))',
]

def model_rules(binary,freeze,source=SOURCE):
    need(binary.resolve()==YOSYS,'sharing model belongs to another binary')
    source=Path(source).resolve()
    need((source/'kernel/satgen.cc').is_file(),
         'exact Yosys derivation source is not materialized; model rule authentication pending')
    # Local hashing only: never a Nix build or store daemon acquisition. A build
    # directory checkout is accepted only with the exact derivation NAR digest.
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    hasher=shutil.which('nix-hash');need(hasher is not None,'missing local NAR hasher')
    freeze(Path(hasher).resolve())
    hashed=subprocess.run([hasher,'--type','sha256',str(source)],text=True,capture_output=True,timeout=180)
    need(hashed.returncode==0 and hashed.stdout.strip()==SOURCE_NAR_SHA,'actual source NAR differs from pinned derivation')
    for path in (DERIVATION,SOURCE_DERIVATION):freeze(path)
    derivation=DERIVATION.read_text();source_derivation=SOURCE_DERIVATION.read_text()
    need(str(SOURCE_DERIVATION) in derivation and str(SOURCE) in derivation,'installed binary/source derivation linkage differs')
    need(str(SOURCE) in source_derivation and SOURCE_NAR_SHA in source_derivation,'fixed source identity differs')
    cc=source/'kernel/satgen.cc';header=source/'kernel/satgen.h'
    installed=YOSYS.parent.parent/'share/yosys/include/kernel/satgen.h'
    cc_sha=freeze(cc,SATGEN_CC_SHA);header_sha=freeze(header,SATGEN_HEADER_SHA);installed_sha=freeze(installed,SATGEN_HEADER_SHA)
    need(header_sha==installed_sha,'source and actual installed SAT headers differ')
    text=cc.read_text()
    need(text.count(MUL_BLOCK)==1,'actual multiplication model block differs')
    need(all(anchor in text for anchor in ANCHORS),'defined-primitive model rule anchor differs')
    return set(RULES),{'binary':str(YOSYS),'source_derivation':str(SOURCE_DERIVATION),
        'actual_source_tree':str(source),
        'source_nar_sha256':SOURCE_NAR_SHA,'satgen_cc_sha256':cc_sha,'satgen_header_sha256':header_sha,
        'rules':sorted(RULES),'premise':'every primitive input coordinate is defined; exact full parameters and ordered inputs match',
        'undefined_cell_outputs_eligible':False,
        'justification':'For audited finite primitives, zero input undefined masks yield zero output masks; value equations are total deterministic finite-vector functions. Exact typed expression identity preserves every output coordinate.'}
