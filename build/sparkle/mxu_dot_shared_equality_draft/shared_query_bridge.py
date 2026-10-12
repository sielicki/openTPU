"""Pure representation bridge and exact resume-artifact binding."""
from pathlib import Path
from defined_expression_sharing import share, verify_rewrite
from check_defined_sharing import read_graph
from audit_sparkle_rtlil_roundtrip import require
from qualify_sparkle_specialization_binding import save


def certify(original, rewritten, certificate, rules, freeze):
    raw=read_graph(original)
    transformed,proof=share(raw,rules)
    verify_rewrite(raw,transformed,proof,rules)
    save(rewritten,transformed);save(certificate,proof)
    graph_sha=freeze(rewritten);certificate_sha=freeze(certificate)
    # Re-read the published bytes; a receipt certifies the artifacts, not just
    # the earlier Python values. No solver starts while graphs remain retained.
    verify_rewrite(raw,read_graph(rewritten),read_graph_json(certificate),rules)
    return {'kind':'exact_defined_expression_substitution',
            'proof_graph':str(rewritten),'proof_graph_sha256':graph_sha,
            'certificate':str(certificate),'certificate_sha256':certificate_sha,
            'removed_cells':len(proof['removed_cells']),
            'substituted_bits':len(proof['substitutions'])}


def read_graph_json(path):
    from qualify_sparkle_specialization_binding import read
    return read(path)


def bind_shared_resume(old,fresh,hashes,freeze):
    require(old['kind']==fresh['kind']=='exact_defined_expression_substitution',
            'resume representation differs')
    for name in ('proof_graph','certificate'):
        path=Path(old[name]).resolve();digest=old[name+'_sha256']
        require(digest==fresh[name+'_sha256']==hashes.get(str(path)),
                'resume shared artifact differs from authenticated closure')
        freeze(path,digest)
    require(old['removed_cells']==fresh['removed_cells'] and
            old['substituted_bits']==fresh['substituted_bits'],
            'resume rewrite accounting differs')
