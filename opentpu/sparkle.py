"""Generate native Sparkle hardware for use by the existing RTL simulation harness."""
from __future__ import annotations

import hashlib
import os
import shutil
import re
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def _generation_inputs() -> dict[str, str]:
    """Fingerprint the generator's source closure, including local Sparkle imports."""
    pending = [ROOT / 'OpenTPU/Generate.lean', ROOT / 'lakefile.lean',
               ROOT / 'lake-manifest.json', ROOT / 'lean-toolchain']
    result = {}
    while pending:
        path = pending.pop().resolve()
        if str(path) in result:
            continue
        data = path.read_bytes()
        result[str(path)] = hashlib.sha256(data).hexdigest()
        if path.suffix != '.lean':
            continue
        for module in re.findall(r'^import\s+([\w.]+)', data.decode(), re.M):
            relative = Path(module.replace('.', '/') + '.lean')
            for base in [ROOT, ROOT.parent / 'sparkle']:
                dependency = base / relative
                if dependency.is_file():
                    pending.append(dependency)
                    break
    return result


_EMISSIONS = {}  # process-local only: identity -> (artifact path, full SHA256)


def _sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _emission_identity(kind, args, sources):
    executable = ROOT / '.lake/build/bin/opentpu-gen'
    tools = []
    for name in ('lake', 'lean'):
        found = shutil.which(name)
        if not found:
            raise RuntimeError('Missing generator tool: ' + name)
        path = Path(found).resolve()
        tools.append((name, str(path), _sha256(path)))
    # Conservative: all environment values affect the key. PYTEST_CURRENT_TEST
    # causes one fresh emission per test, but repeated host operations within
    # that test reuse output. No unproven environment-independence assumption.
    return (str(ROOT.resolve()), kind, tuple(args), tuple(sorted(sources.items())),
            _sha256(executable), _sha256(__file__), tuple(tools),
            tuple(sorted((k, hashlib.sha256(v.encode()).hexdigest())
                         for k, v in os.environ.items())))


def _source(kind: str, *args: int) -> Path:
    directory = ROOT / 'build/sparkle'
    directory.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        before = _generation_inputs()
        result = subprocess.run(['lake', 'build', 'opentpu-gen'], cwd=ROOT,
                                capture_output=True, text=True)
        if before != _generation_inputs():
            continue
        if result.returncode:
            raise RuntimeError(f'Sparkle build failed:\n{result.stdout}\n{result.stderr}')
        identity = _emission_identity(kind, args, before)
        cached = _EMISSIONS.get(identity)
        if cached is not None:
            artifact, expected = cached
            valid = artifact.is_file() and not artifact.is_symlink() and _sha256(artifact) == expected
            # Check after reading the artifact too; don't publish across revisions.
            if before != _generation_inputs() or identity != _emission_identity(kind, args, before):
                continue
            if valid:
                return artifact
            del _EMISSIONS[identity]
        with tempfile.TemporaryDirectory(dir=directory) as tmp:
            source = Path(tmp) / f'{kind}.sv'
            result = subprocess.run([str(ROOT / '.lake/build/bin/opentpu-gen'), kind,
                                     *map(str, args), str(source)], cwd=ROOT,
                                    capture_output=True, text=True)
            if before != _generation_inputs() or identity != _emission_identity(kind, args, before):
                continue
            if result.returncode:
                raise RuntimeError(f'Sparkle emission failed:\n{result.stdout}\n{result.stderr}')
            digest = _sha256(source)
            artifact = directory / f'{kind}_{digest[:20]}.sv'
            source.replace(artifact)
            _EMISSIONS[identity] = (artifact, digest)
            return artifact
    raise RuntimeError('Sparkle generator sources changed during three build/emission attempts; retry once sources are stable')


def collective_source(slices: int, lanes: int) -> Path:
    if slices < 1 or lanes < 1:
        raise ValueError("Sparkle collective requires positive S and LANES")
    return _source("collective", slices, lanes)


def float_source() -> Path:
    return _source("fpipe")


def actram_source(depth: int, columns: int, rows: int, blocks: int, lanes: int) -> Path:
    return _source("actram", depth, columns, rows, blocks, lanes)


def tmem_source(words: int, lanes: int, writes_per_bank: int) -> Path:
    # Port layout and sharing are fixed by otpu_slice; all other dimensions come
    # from the resolved top-level configuration.
    return _source("tmem", words, lanes, 8, 4, writes_per_bank, 1, 2, 1, 160)


def vtree_source(lanes: int, latency: int = 4) -> Path:
    return _source("vtree", lanes, latency)


def seq_source(words: int, depth: int, slices: int, slots: int) -> Path:
    return _source("seq", words, depth, slices, slots)


def qscale_source() -> Path:
    # Quantizer uses fixed LM=2, LA=4 and four block-buffer tags (TW=2).
    return _source("qscale", 2, 4, 2)


def qread_source(lanes: int) -> Path:
    return _source("qread", lanes)


def qwrite_source(lanes: int) -> Path:
    return _source("qwrite", lanes)


def quant_source(depth: int, lanes: int) -> Path:
    return _source("quant", depth, lanes)


def dma_source(chunk_bytes: int, lanes: int, depth: int = 128, streams: bool = True) -> Path:
    return _source("dma", chunk_bytes, lanes, depth, int(streams))


def se_composite_source(lanes: int, metadata: int, stages: int = 3,
                        look_ahead: int = 2, external: bool = True) -> Path:
    return _source("se-comp", lanes, metadata, stages, look_ahead, int(external))


def se_tail_source(lanes: int = 8, input_latency: int = 7, tree_delay: int = 1) -> Path:
    return _source("se-tail", lanes, input_latency, tree_delay)


def dram_source(words: int, depth: int, latency: int) -> Path:
    return _source("dram", words, depth, latency)


def native_dram_source(depth: int = 128) -> Path:
    # otpu_top uses the adapter's production defaults for all queue dimensions.
    return _source("native-dram", depth, 16, 32, 1, 4, 128, 64, 32)


def vpu_test_source(lanes: int, composite_lanes: int, streams: bool, buffered: bool) -> Path:
    """Whole native VPU adapter, shared by isolated and combined simulation."""
    return _source("vpu-test", lanes, composite_lanes, int(streams), int(buffered))


def mxu_test_source(depth: int, columns: int, rows: int, fifo_depth: int,
                    lanes: int, implementation: int, chain_length: int) -> Path:
    """Whole behavioral MXU adapter with native controller storage hints."""
    return _source("mxu-test", depth, columns, rows, fifo_depth, lanes, implementation, chain_length)


def board_assembly_source(params: dict, *, native_slice: bool = False) -> Path:
    """Native board wiring/support, optionally including the complete native Slice."""
    p = params
    lanes = p.get("LANES", 8)
    columns = p.get("MCOLS", 4)
    return _source("board-native" if native_slice else "board-assembly", p.get("D", 128), columns,
        p.get("ACT_BLOCKS", 128), p.get("ACT_ROWS", columns),
        p.get("TMEM_WORDS", 65536), p.get("IMEM_WORDS", 32768),
        1024, lanes, p.get("WIN", 16), 8 * lanes, 1, p.get("MXU_IMPL", 2),
        16, p.get("VPU_CL", lanes // 4 if lanes >= 8 else 1),
        p.get("ULANES", lanes), p.get("CORE_KHZ", 100000),
        p.get("BUILD_ID", 0x0B0A4D00), p.get("DDR_MTS", 0),
        p.get("TRACE_DEPTH", 16384), p.get("TRACE_QD", 32),
        p.get("PQ_WIN", 1024), 1, 1, p.get("DSTEP", 1), p.get("HOSTCAL", 0))


def top_source(params: dict) -> Path:
    """Complete native simulation top, including slices and collective wiring."""
    p = params
    lanes = p["LANES"]
    return _source("top", p["S"], p["D"], p["MCOLS"], p["ACT_BLOCKS"],
        p["ACT_ROWS"], p["TMEM_WORDS"], p["IMEM_WORDS"], p["DRAM_WORDS"],
        p["DRAM_LAT"], p.get("FIFO_DEPTH", 128), lanes, p["WIN"], p["RPB"],
        p["WPB"], p.get("MXU_IMPL", 0), p.get("MXU_CL", 16),
        p.get("VPU_CL", lanes // 4 if lanes >= 8 else 1),
        p.get("ULANES", lanes), p["AXI"])


def board_support_sources(params: dict) -> dict[str, Path]:
    """Native support modules with tb_board/otpu_board's resolved defaults."""
    p = params
    sources = {"otpu_ctrl.sv": _source("control", p.get("D", 128), p.get("MCOLS", 4),
        p.get("LANES", 8), p.get("ACT_ROWS", p.get("MCOLS", 4)),
        p.get("CORE_KHZ", 100000), p.get("BUILD_ID", 0x0B0A4D00), p.get("DDR_MTS", 0),
        p.get("TRACE_DEPTH", 16384), p.get("PQ_WIN", 1024), 1, 1, 1,
        p.get("DSTEP", 1), p.get("HOSTCAL", 0)),
        "otpu_afifo.sv": _source("async-fifo-family", 64, 16)}
    if p.get("TRACE_DEPTH", 16384):
        sources["otpu_trace.sv"] = _source("trace", p.get("TRACE_DEPTH", 16384),
            p.get("TRACE_QD", 32), p.get("WIN", 16))
    return sources


def mem_channel_source(id_width: int = 4, accelerator_depth: int = 64,
                       xdma_depth: int = 16, run_length: int = 32,
                       command_depth: int = 32, data_depth: int = 32) -> Path:
    """Closed native channel plus the original shared FIFO for external consumers.

    The reference file also declares otpu_sfifo, used by the unchanged AXI split.
    Retain that standalone declaration when replacing the channel source. The
    channel itself instantiates only its specialized native FIFO modules.
    """
    native = _source("mem-channel", id_width, accelerator_depth, xdma_depth,
                     run_length, command_depth, data_depth)
    reference = ROOT / "rtl/boards/ypcb-00338/otpu_mem_ch.sv"
    leaves = re.findall(r"^module otpu_sfifo\b.*?^endmodule\s*$", reference.read_text(),
                        flags=re.MULTILINE | re.DOTALL)
    if len(leaves) != 1:
        raise RuntimeError("Expected exactly one original otpu_sfifo declaration")
    text = native.read_text() + "\n// Original shared FIFO for unchanged external consumers.\n" + leaves[0] + "\n"
    digest = hashlib.sha256(text.encode()).hexdigest()[:20]
    artifact = native.parent / f"mem-channel-with-shared-fifo_{digest}.sv"
    if not artifact.exists():
        with tempfile.TemporaryDirectory(dir=native.parent) as temporary:
            staging = Path(temporary) / "channel.sv"
            staging.write_text(text)
            staging.replace(artifact)
    return artifact
