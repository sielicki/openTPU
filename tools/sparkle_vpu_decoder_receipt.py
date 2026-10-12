"""Consume exact reset-reachability evidence without extending its scope.

Historical proof inputs may resolve to their authenticated archives. Consuming
HDL is always checked directly; no archive substitutes for the requested artifact.
"""
import json
from pathlib import Path
from check_sparkle_fpga_top_complete import bounded_context, module_hashes, global_directives
from sparkle_provenance import ROOT, sha256, verify, archive

DEFAULT_RECEIPT=ROOT/'build/sparkle/formal_vpu_decoder_reachability/driver-guards5/summary.json'
MODULE='otpu_vpu_datapath_sparkle'
REFERENCE=('rtl/vpu/otpu_vpu.sv','rtl/top/otpu_pkg.sv')
PROPERTIES={'base_ok','step_ok','onehot_ok','equal_next'}


def require(ok, message):
    if not ok: raise ValueError(message)


def reference_digest(mapping, suffix):
    matches=[h for p,h in mapping.items() if str(p).replace('\\','/').endswith('/'+suffix) or str(p)==suffix]
    require(len(matches)<=1, 'ambiguous reference digest: '+suffix)
    return matches[0] if matches else None


def compare_reference(proved, consumed):
    result={}
    for name in REFERENCE:
        expected=reference_digest(proved,name)
        require(expected is not None,'decoder receipt lacks reference '+name)
        actual=reference_digest(consumed,name)
        origin='assembly proof input'
        if actual is None:
            actual=sha256(ROOT/name);origin='current reference (not present in assembly map)'
        require(actual==expected,'decoder reference mismatch: '+name)
        result[name]={'sha256':actual,'binding':origin}
    return result


class DecoderReceipt:
    def __init__(self, path=DEFAULT_RECEIPT):
        bounded_context()
        self.path=Path(path).resolve();self.before=sha256(self.path)
        self.record=json.loads(self.path.read_text())
        require(self.record.get('status')=='passed','decoder receipt incomplete')
        self.inputs=self.record['input_sha256']
        for name in ['prove_sparkle_vpu_decoder_reachability.py','sparkle_vpu_decoder_cone.lean',
                     'sparkle_transition.py','sparkle_compiled_lean.py','check_sparkle_fpga_top_complete.py']:
            path=ROOT/'tools'/name
            require(self.inputs.get(str(path))==sha256(path),'decoder proof implementation changed/unbound: '+name)
        self.resolved={k:ROOT/v for k,v in verify(self.inputs).items()}
        self.cases={};self.consumed={};self.bindings=[]
        for case in self.record['configurations']:
            cfg=tuple(case['config'])
            require(len(cfg)==3 and cfg not in self.cases,'duplicate/invalid decoder configuration')
            lanes,cl,se=cfg
            require(lanes in (2,4,8,16) and type(cl) is int and cl>0 and type(se) is bool,'invalid decoder configuration')
            width=102+lanes+(256//lanes-1).bit_length()
            require(case['state_bits_per_design']==width+28,'incomplete decoder state inventory')
            require(case.get('projection_guard_mutations')==4,'missing executable projection guards')
            require(set(case['proofs'])==PROPERTIES,'incomplete induction properties')
            require(set(case['mutations'])==({'reset','update','stream'} if se else {'reset','update'}),'incomplete fault coverage')
            for path in case['proofs'].values():
                log=self.artifact(path).read_text()
                require('SAT proof finished - no model found: SUCCESS!' in log,'missing terminal induction proof')
            for path in case['mutations'].values():
                require('proof did fail' in self.artifact(path).read_text(),'missing rejected decoder fault')
            native=self.artifact(case['full_native'])
            actual=module_hashes(native);context=global_directives(native)
            require(actual==case['full_native_module_hashes'],'recorded decoder module hash mismatch')
            require(json.loads(json.dumps(context))==case['full_native_directives'],'recorded decoder context mismatch')
            require(set(actual)=={MODULE},'unexpected full native module inventory')
            case['_identity']=(actual[MODULE],context[1][MODULE])
            self.cases[cfg]=case
        require(bool(self.cases),'empty decoder receipt')

    def artifact(self,path):
        key=str(Path(path).resolve())
        require(key in self.resolved,'unbound decoder artifact: '+key)
        return self.resolved[key]

    def bind(self,config,source,reference_inputs):
        cfg=tuple(config)
        require(len(cfg)==3 and cfg in self.cases,'decoder configuration not proved: '+str(cfg))
        case=self.cases[cfg];source=Path(source).resolve();digest=sha256(source)
        require(str(source) not in self.consumed or self.consumed[str(source)]==digest,'consuming artifact changed')
        actual=module_hashes(source);context=global_directives(source)
        require(MODULE in actual and MODULE in context[1],'missing consuming datapath module')
        require((actual[MODULE],context[1][MODULE])==case['_identity'],'decoder datapath module/context mismatch: '+str(source))
        ref=compare_reference(self.inputs,reference_inputs)
        for name,item in ref.items():
            if item['binding'].startswith('current reference'):
                self.consumed[str(ROOT/name)]=item['sha256']
        require(sha256(source)==digest,'consuming artifact changed during comparison')
        self.consumed[str(source)]=digest
        binding={'config':list(cfg),'artifact':str(source),'artifact_sha256':digest,
                 'module':MODULE,'module_sha256':actual[MODULE],'reference':ref}
        self.bindings.append(binding)
        return binding

    def finish(self):
        require(sha256(self.path)==self.before,'decoder receipt changed')
        for original,resolved in self.resolved.items():
            require(sha256(resolved)==self.inputs[original],'decoder proof input changed: '+original)
        for path,digest in self.consumed.items():
            require(sha256(path)==digest,'consuming artifact changed: '+path)
        archive(self.path)
        return {'receipt':str(self.path),'receipt_sha256':self.before,'bindings':self.bindings,
                'scope':'m0d=fdec(m0.func) and onehot-or-zero fh after a sampled reset; exact enumerated configurations and full datapath module identities only'}
