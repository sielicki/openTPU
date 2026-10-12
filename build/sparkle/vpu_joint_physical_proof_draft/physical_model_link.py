"""Concrete installed derivation/source linkage, without invoking a build daemon."""
from pathlib import Path
import shutil
import subprocess
from physical_slices import require
from slice_model import snapshot_model

BINARY = Path('/nix/store/4sxr7d1kf8v1wjkfkxhv7d0ssmvd64nf-yosys-0.69/bin/yosys')
DERIVATION = Path('/nix/store/f24p332m45cn9kfzi95i0sq7sjbbw85m-yosys-0.69.drv')
SOURCE_DERIVATION = Path('/nix/store/x2q2509a921d640gxy7chwkrbp7w8m39-source.drv')
SOURCE = Path('/nix/store/fiq6rwpyasp5f401gdaws45pl3biq68s-source')
NAR = '563ca4e9a30ac27244136e6d43448a5907177c9c63a42568bbee077fc73e20be'
CC = 'ee9c3f7b6268f192ad33f8f9117ddde4fa683400d936afef483da6fb31c8c98b'
HEADER = 'a3cc919b23f8a5fe6794cc20699a29ae8c6070b6ed782b204eb44efe9583d86a'
DERIVATION_SHA = 'c67c5f2b736b43f361d6d7e03df48da4390d89d4b2c2b3a6b2f760fe33f244ec'
SOURCE_DERIVATION_SHA = 'c8b955053133dde3d71612449e316df40b723f95fc0d7ff52f6ffd4d1086b7dc'


def derivation_contract(d, s):
    require(d.startswith('Derive([("out","' + str(BINARY.parent.parent) + '","","")],'),
            'Exact derivation output does not own solver binary')
    require(s.startswith('Derive([("out","' + str(SOURCE) + '","r:sha256","' + NAR + '")],'),
            'Exact source output/NAR declaration differs')
    require(str(SOURCE_DERIVATION) in d and str(SOURCE) in d and str(SOURCE) in s and NAR in s,
            'Actual derivation/source linkage differs')


def link(binary, source, freeze, run):
    require(binary.resolve() == BINARY, 'Solver binary differs from pinned derivation')
    source = source.resolve()
    hasher = shutil.which('nix-hash'); require(hasher is not None, 'Local NAR hasher unavailable')
    freeze(Path(hasher).resolve())
    rc, output = run('source-nar', [hasher, '--type', 'sha256', str(source)], 180)
    require(rc == 0 and output.strip() == NAR, 'Source tree does not match concrete derivation')
    for p, pin in ((DERIVATION, DERIVATION_SHA), (SOURCE_DERIVATION, SOURCE_DERIVATION_SHA)):
        freeze(p, pin)
    d, s = DERIVATION.read_text(), SOURCE_DERIVATION.read_text()
    derivation_contract(d, s)
    receipt = snapshot_model(source)
    for name, pin in (('satgen.cc', CC), ('satgen.h', HEADER)):
        freeze(source / 'kernel' / name, pin)
        freeze(Path(__file__).parent / (name + '.snapshot'), pin)
    freeze(BINARY.parent.parent / 'share/yosys/include/kernel/satgen.h', HEADER)
    backend = source / 'backends/json/json.cc'
    expected = Path(__file__).parent / 'json-backend.cc.snapshot'
    require(freeze(backend) == freeze(expected), 'Post-SigMap JSON writer source differs')
    text = backend.read_text()
    require('sigmap.set(module);' in text and 'for (auto bit : sigmap(sig))' in text,
            'JSON writer no longer emits post-SigMap coordinates')
    freeze(source / 'frontends/json/jsonparse.cc')
    receipt.update(executable_source_link_verified=True, source_nar_sha256=NAR,
                   binary=str(BINARY), derivation=str(DERIVATION), source_derivation=str(SOURCE_DERIVATION),
                   derivation_sha256=DERIVATION_SHA, source_derivation_sha256=SOURCE_DERIVATION_SHA,
                   post_sigmap_backend=str(backend), generic_compiler_correctness_proven=False)
    return receipt
