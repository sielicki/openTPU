"""Exercise the reviewed I/O helper on real receipts; no circuit theorem."""
import argparse
import json
from pathlib import Path
import sys
import time
from efficient_historical_evidence import EfficientHistoricalEvidence, ROOT, ARCHIVE
from check_sparkle_fpga_top_complete import bounded_context, require
from qualify_sparkle_specialization_binding import normalized_hashes, save
from sparkle_provenance import archive

RECEIPTS = (
    ('vpu-control-initial-binding-second', '704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8'),
    ('vpu-joint-control-initial-fifth', '3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352'),
    ('vpu-control-comb-third', '7271adaaafc7d1b53c1a4c1aa969a046d8efe1f369a465f5994805b8a76e1203'),
)


def main(output):
    bounded_context()
    require(not output.exists(), 'Preserve earlier exercise')
    output.mkdir(parents=True)
    report = {'status': 'incomplete', 'circuit_theorem_proven': False}
    save(output / 'summary.json', report)
    evidence = EfficientHistoricalEvidence()
    start = time.monotonic()
    expected = set()
    try:
        for module in list(sys.modules.values()):
            path = getattr(module, '__file__', None)
            if path and Path(path).resolve().is_relative_to(ROOT):
                evidence.direct(Path(path).resolve())
        for folder, digest in RECEIPTS:
            path = ROOT / 'build/sparkle' / folder / 'summary.json'
            record, _ = evidence.record(path, digest)
            expected.update(normalized_hashes(record['input_sha256']).items())
        require(set(evidence.authenticated) == expected, 'Owner resolutions differ')
        for (_, digest), path in evidence.authenticated.items():
            require(Path(path) == ARCHIVE / digest, 'Owner resolved outside its snapshot')
        initial = time.monotonic() - start
        evidence.finish()
        report.update(status='real_receipt_closure_authentication_exercised',
                      owner_resolutions=len(expected), observed_files=len(evidence.observed),
                      initial_seconds=initial, total_seconds=time.monotonic() - start,
                      input_sha256=dict(evidence.observed))
    except BaseException as error:
        report.update(status='incomplete', error=repr(error), input_sha256=dict(evidence.observed))
        raise
    finally:
        save(output / 'summary.json', report)
        archive(output / 'summary.json')
    print(json.dumps({k: v for k, v in report.items() if k != 'input_sha256'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output.resolve())
