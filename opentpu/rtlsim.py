"""Build and run the SystemVerilog RTL with Verilator."""
from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import simtmp, simmemory
from . import target as _target

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
TB = ROOT / "sim" / "verilator"
BUILD = ROOT / "build" / "verilator"

RTL_SOURCES = [
    "vpu/otpu_fp.sv", "vpu/otpu_fpipe.sv", "top/otpu_pkg.sv", "mem/otpu_dram.sv", "mem/otpu_tmem.sv",
    "mem/otpu_native_dram.sv", "mem/otpu_actram.sv", "seq/otpu_seq.sv",
    "vpu/otpu_vtree.sv", "dma/otpu_dma.sv", "mxu/otpu_mxu.sv", "tech/generic/otpu_tech_dsp.sv",
    "tech/generic/otpu_tech_ram.sv",
    "vpu/otpu_quant.sv", "vpu/otpu_se_comp.sv", "vpu/otpu_se_tail.sv", "vpu/otpu_vpu.sv",
    "top/otpu_coll.sv", "top/otpu_slice.sv", "top/otpu_top.sv",
]


# Verilator's flags (in the build cache's key, with its version and the sources' names)
VFLAGS = ["--binary", "-j", "0", "-Wno-fatal", "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC",
          "-Wno-UNUSEDSIGNAL", "-Wno-UNUSEDPARAM", "-O3", "--x-assign", "0", "--x-initial", "0"]
_VERSION: str | None = None


def verilator_version() -> str:
    """`verilator --version` (once per process); "" without Verilator."""
    global _VERSION
    if _VERSION is None:
        try:
            _VERSION = subprocess.run(["verilator", "--version"], capture_output=True,
                                      text=True).stdout.strip()
        except FileNotFoundError:
            _VERSION = ""
    return _VERSION


def verilator_jobs() -> int:
    """Compiler parallelism override, also used for linker recovery."""
    try:
        jobs = int(os.environ.get("OTPU_VERILATOR_JOBS", "0"))
    except ValueError as error:
        raise ValueError("OTPU_VERILATOR_JOBS must be a nonnegative integer") from error
    if jobs < 0:
        raise ValueError("OTPU_VERILATOR_JOBS must be a nonnegative integer")
    return jobs


def verilator_flags() -> list[str]:
    flags = list(VFLAGS)
    flags[flags.index("-j") + 1] = str(verilator_jobs())
    return flags


def build_dir(top: str, sources: list[Path], params: dict | None = None) -> Path:
    """The build's directory: keyed on the sources' names (in the tree: OTPU_REMOTE_BUILD shares
    build/ between trees) and contents, the parameters, VFLAGS and Verilator's version."""
    h = hashlib.sha1()
    for s in sources:
        s = Path(s).resolve()
        name = s.relative_to(ROOT).as_posix() if s.is_relative_to(ROOT) else str(s)
        h.update(name.encode() + b"\0" + s.read_bytes() + b"\0")
    h.update(repr(sorted((params or {}).items())).encode())
    h.update(repr(verilator_flags()).encode() + b"\0" + verilator_version().encode())
    return BUILD / f"{top}_{h.hexdigest()[:12]}"


def build(top: str, sources: list[Path], params: dict | None = None) -> Path:
    """Compile `top` with Verilator (--binary); cached (build_dir). The build runs in a
    temporary directory, renamed into place once linked, under a lock per build: a concurrent
    build of the same waits for it instead of running a half-linked executable, and a build
    killed or failed leaves no executable for the next to take."""
    params = params or {}
    jobs = verilator_jobs()
    if audit_path := os.environ.get("OTPU_SIM_BUILD_AUDIT"):
        from .simcache import build_audited
        return build_audited(top, sources, params, jobs, audit_path)
    out = build_dir(top, sources, params)
    exe = out / f"V{top}"
    if exe.exists():
        return exe
    BUILD.mkdir(parents=True, exist_ok=True)
    with open(BUILD / f".{out.name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if exe.exists():                        # built while this one waited
            return exe
        for d in BUILD.glob(f".{out.name}.*"):  # a killed build's (none runs: the lock)
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=BUILD))
        try:
            cmd = ["verilator", *verilator_flags(), "--top-module", top, "-Mdir", str(tmp)]
            cmd += [f"-G{k}={v}" for k, v in params.items()]
            cmd += [str(s) for s in sources]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 and "linker command failed" in r.stdout + r.stderr:
                # the parallel make occasionally archives a stale object: rebuild the archive once
                for f in tmp.glob("*__ALL.a"):
                    f.unlink()
                r = subprocess.run(["make", "-C", str(tmp), "-f", f"V{top}.mk", "-j", str(jobs or 8)],
                                   capture_output=True, text=True)
            if r.returncode != 0 or not (tmp / f"V{top}").exists():
                raise RuntimeError(f"verilator failed:\n{r.stdout[-4000:]}\n{r.stderr[-4000:]}")
            if out.exists():                    # an unfinished build's (no executable)
                shutil.rmtree(out)
            tmp.rename(out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return exe


# A simulator whose Python parent dies (killed, or os._exit) would run on under launchd for
# hours: the child is started under a shell that kills it once the parent is gone (macOS has
# no PR_SET_PDEATHSIG), and in its own process group, killed on any exception here (a timeout,
# KeyboardInterrupt).
_WATCH = ('"$@" & c=$!; (while kill -0 "$OTPU_PARENT" 2>/dev/null; do sleep 1; done; '
          'kill -9 $c 2>/dev/null) & w=$!; wait $c; r=$?; kill $w 2>/dev/null; exit $r')


def run_sim(cmd: list, timeout: float | None = None) -> subprocess.CompletedProcess:
    """subprocess.run(cmd, capture_output=True, text=True, timeout=timeout) for a simulator
    binary, which never outlives this process (see _WATCH)."""
    import signal
    env = {**os.environ, "OTPU_PARENT": str(os.getpid())}
    p = subprocess.Popen(["/bin/sh", "-c", _WATCH, "sh", *map(str, cmd)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    simtmp.track(p.pid)                 # (killed on SIGTERM / SIGHUP: simtmp)
    try:
        out, err = p.communicate(timeout=timeout)
    except BaseException:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait()
        raise
    finally:
        simtmp.untrack(p.pid)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def run_fp_vectors(vec_path: Path) -> str:
    exe = build("tb_fp", [RTL / "vpu/otpu_fp.sv", TB / "tb_fp.sv"])
    r = subprocess.run([str(exe), f"+vec={vec_path}"], capture_output=True, text=True, timeout=600)
    return r.stdout + r.stderr


def _write_hex(path: Path, words: np.ndarray) -> None:
    nz = np.nonzero(words)[0]
    n = int(nz[-1]) + 1 if len(nz) else 1
    path.write_text("\n".join(f"{int(w):08x}" for w in words[:n]) + "\n")


def _read_hex(path: Path, n: int) -> np.ndarray:
    toks = [t for t in path.read_text().split() if not t.startswith(("@", "//"))]
    if len(toks) != n:                  # a short dump (e.g. a full disk) is an error
        raise RuntimeError(f"{path.name}: {len(toks)} words, expected {n}")
    out = np.zeros(n, dtype=np.uint32)
    vals = np.fromiter((int(t, 16) for t in toks), dtype=np.uint64, count=len(toks))
    out[: len(vals)] = vals.astype(np.uint32)
    return out


# Micro-architecture knobs that change timing only (never results). Tests and tools may
# override them through `rtlsim.UARCH` or the `uarch` argument of run().
UARCH = {"WIN": 32, "RPB": 4, "WPB": 2}
# The board build: TMEM is replicated per read port (reads never conflict), one write per bank
# per cycle (simple dual-port block RAM), a 16-entry dispatch window, and a 1024-chunk MXU
# prefetch FIFO (128 KiB of block RAM: the weight stream runs ahead through the serial
# norm -> quantize -> MM dependency chains).
# RPB covers every read lane (8 ports x up to 16 lanes), which selects the slice's shallow
# write-mask arbiter, as on the board. The values are the selected target's (OTPU_TARGET,
# default the card: targets/ypcb-00338.toml; opentpu.target.sim_uarch).
BOARD_UARCH = _target.sim_uarch(_target.current())
if os.environ.get("OTPU_UARCH") == "board":
    UARCH = dict(BOARD_UARCH)
# MXU dot-product implementation (timing only): the 2D systolic array, as the board builds it
# (weights hop column to column; docs/mxu_systolic.md); OTPU_MXU=tree the adder tree,
# OTPU_MXU=cascade the DSP cascade chains (OTPU_MXU_CL products per chain).
UARCH["MXU_IMPL"] = {"tree": 0, "cascade": 1}.get(os.environ.get("OTPU_MXU", "systolic"), 2)
if UARCH["MXU_IMPL"] == 1:
    UARCH["MXU_CL"] = int(os.environ.get("OTPU_MXU_CL", "16"))
# VPU lanes with the composite functions (exp2, recip, rsqrt; timing only): OTPU_VPU_CL=4
if os.environ.get("OTPU_VPU_CL"):
    UARCH["VPU_CL"] = int(os.environ["OTPU_VPU_CL"])
# TMEM lanes of the MXU and the quantizer when fewer than LANES (timing only): OTPU_ULANES=8
if os.environ.get("OTPU_ULANES"):
    UARCH["ULANES"] = int(os.environ["OTPU_ULANES"])

# The memory path. AXI: the board's memory path -- its adapter (otpu_native_dram) in front of a
# two-channel native memory model (sim/verilator/otpu_native_mem.sv) with random stalls (percent)
# and latency (D = 128 only; other configurations keep the behavioural DRAM). BOOT: the program is
# placed in DRAM and copied into IMEM by the slice's loader, as on the board. The environment
# (OTPU_AXI=1, OTPU_BOOT=1, OTPU_STALL=n) sets the defaults, so the whole suite can be run on the
# board's memory path. NATIVE: the board model's channels -- by default (OTPU_NATIVE=ld) the
# LiteDRAM build's (otpu_mem_ch in front of a LiteDRAM native-port model: sim/verilator/
# otpu_chmem.sv, tb_board MEM_NATIVE=2), with OTPU_NATIVE=1 otpu_native_mem alone (MEM_NATIVE=1).
MEMORY = {"AXI": os.environ.get("OTPU_AXI", "0") == "1",
          "NATIVE": True if os.environ.get("OTPU_NATIVE", "ld") == "1" else "ld",
          "BOOT": os.environ.get("OTPU_BOOT", "0") == "1",
          "STALL": int(os.environ.get("OTPU_STALL", "20")),
          "SEED": int(os.environ.get("OTPU_SEED", "1")),
          "BW": int(os.environ.get("OTPU_BW", "100")),        # percent of a beat/cycle/channel
          "LAT": int(os.environ.get("OTPU_LAT", "20")),
          "LDC": int(os.environ.get("OTPU_LDC", "0")),
          "LDC_MHZ": float(os.environ.get("OTPU_LDC_MHZ", "0"))}
# LDC: the channels behind the adapter are the card's instead of otpu_native_mem's model -- per
# channel the board's bridge (otpu_mem_ch) and LiteDRAM's own controller, generated with the
# production core's settings (tools/litedram/gen_ldc.py; sim/verilator/otpu_ldc_mem.sv holds the
# data) -- at DDR3-LDC (OTPU_LDC=1066, the card's and the board's only rate), in its controller
# clock (the rate / 8) with the core at LDC_MHZ (OTPU_LDC_MHZ; 0: the controller's clock). The
# stall, bandwidth and latency settings do not apply.
LDC_MODELS = {1066: "otpu_ldc_ch.v"}


def ldc_plusargs(mts: int, mhz: float = 0) -> list[str]:
    """Simulator arguments of the co-simulated controller (AXI with LDC): its clock, DDR3-`mts` /
    8, against the core's `mhz` (0: the same clock)."""
    ctl = {1066: 3200 / 3}[mts] / 8
    return [f"+ldc_ratio={round(1e6 * (mhz or ctl) / ctl)}"]


def top_params(cfg, dram_lat: int = 8, uarch: dict | None = None, axi: bool | int = False,
               dram_bytes: int | None = None) -> dict:
    p = {"S": cfg.S, "D": cfg.D, "MCOLS": cfg.MCOLS, "ACT_BLOCKS": cfg.ACT_BLOCKS,
         "ACT_ROWS": cfg.act_rows,
         "TMEM_WORDS": cfg.TMEM_WORDS, "IMEM_WORDS": cfg.IMEM_WORDS,
         "DRAM_WORDS": (dram_bytes or cfg.DRAM_BYTES) // 4, "DRAM_LAT": dram_lat,
         "LANES": cfg.LANES,
         "AXI": int(axi)}                                # otpu_top's memory path (2: LDC)
    p.update(UARCH)
    p.update(uarch or {})
    return p


def build_top(cfg, dram_lat: int = 8, uarch: dict | None = None, axi: bool = False,
              dram_bytes: int | None = None, ldc: int | None = None) -> Path:
    ldc = (MEMORY["LDC"] if ldc is None else ldc) if axi else 0
    shell = RTL / "shell"
    mem = ([shell / "otpu_afifo.sv", shell / "otpu_mem_ch.sv", TB / LDC_MODELS[ldc],
            TB / "otpu_ldc_mem.sv"] if ldc else [TB / "otpu_native_mem.sv"] if axi else [])
    params = top_params(cfg, dram_lat, uarch, 2 if ldc else axi, dram_bytes)
    sources = [RTL / s for s in RTL_SOURCES]
    sparkle = os.environ.get("OTPU_SPARKLE", "0")
    if sparkle == "top-test":
        from .sparkle import top_source, mem_channel_source
        if ldc:
            mem = [mem_channel_source(), TB / LDC_MODELS[ldc], TB / "otpu_ldc_mem.sv"]
        # Only packages and explicit simulation memory models remain external.
        sources = [RTL / "vpu/otpu_fp.sv", RTL / "top/otpu_pkg.sv", top_source(params)]
        return build("tb_top", sources + mem + [TB / "tb_top.sv"], params)
    if sparkle not in ("0", "collective", "float", "actram", "tmem", "vtree", "seq", "qscale", "qread", "qwrite", "quant", "dma", "secomp", "setail", "dram", "native-dram", "vpu-test", "mxu-test", "all"):
        raise ValueError("OTPU_SPARKLE must be 0, collective, float, actram, tmem, vtree, seq, qscale, qread, qwrite, quant, dma, secomp, setail, dram, native-dram, vpu-test, mxu-test, or all")
    if sparkle in ("mxu-test", "all"):
        from .sparkle import mxu_test_source
        sources[sources.index(RTL / "mxu/otpu_mxu.sv")] = mxu_test_source(
            params["D"], params["MCOLS"], params["ACT_ROWS"], params.get("FIFO_DEPTH", 128),
            params.get("ULANES", params["LANES"]), params.get("MXU_IMPL", 0),
            params.get("MXU_CL", 16))
    if sparkle in ("vpu-test", "all"):
        from .sparkle import vpu_test_source
        lanes = params["LANES"]
        # Match otpu_slice's HAS_SS and ARB_MASK elaboration constants.
        streams = bool(params.get("HAS_DSTEP", 1) and lanes == 8 and params["D"] >= 32)
        buffered = params["RPB"] >= 8 * lanes and params["WPB"] == 1
        sources[sources.index(RTL / "vpu/otpu_vpu.sv")] = vpu_test_source(
            lanes, params.get("VPU_CL", lanes // 4 if lanes >= 8 else 1), streams, buffered)
    if sparkle in ("native-dram", "all") and params["AXI"]:
        from .sparkle import native_dram_source
        sources[sources.index(RTL / "mem/otpu_native_dram.sv")] = native_dram_source(params["D"])
    if sparkle in ("dram", "all") and not params["AXI"]:
        from .sparkle import dram_source
        sources[sources.index(RTL / "mem/otpu_dram.sv")] = dram_source(
            params["DRAM_WORDS"], params["D"], params["DRAM_LAT"])
    if sparkle in ("collective", "all"):
        from .sparkle import collective_source
        sources[sources.index(RTL / "top/otpu_coll.sv")] = collective_source(params["S"], params["LANES"])
    if sparkle in ("float", "all"):
        from .sparkle import float_source
        sources.insert(sources.index(RTL / "vpu/otpu_fpipe.sv"), float_source())
    if sparkle in ("actram", "all"):
        from .sparkle import actram_source
        sources[sources.index(RTL / "mem/otpu_actram.sv")] = actram_source(
            params["D"], params["MCOLS"], params["ACT_ROWS"], params["ACT_BLOCKS"],
            params.get("ULANES", params["LANES"]))
    if sparkle in ("tmem", "all"):
        from .sparkle import tmem_source
        sources[sources.index(RTL / "mem/otpu_tmem.sv")] = tmem_source(
            params["TMEM_WORDS"], params["LANES"], params["WPB"])
    if sparkle == "vtree":
        from .sparkle import vtree_source
        # LA is a fixed localparam (4) in otpu_vpu.
        sources[sources.index(RTL / "vpu/otpu_vtree.sv")] = vtree_source(params["LANES"])
    if sparkle == "qscale":
        from .sparkle import qscale_source
        sources.insert(sources.index(RTL / "vpu/otpu_quant.sv"), qscale_source())
    if sparkle == "qread":
        from .sparkle import qread_source
        sources.insert(sources.index(RTL / "vpu/otpu_quant.sv"),
                       qread_source(params.get("ULANES", params["LANES"])))
    if sparkle == "qwrite":
        from .sparkle import qwrite_source
        sources.insert(sources.index(RTL / "vpu/otpu_quant.sv"),
                       qwrite_source(params.get("ULANES", params["LANES"])))
    if sparkle in ("quant", "all"):
        from .sparkle import quant_source
        sources[sources.index(RTL / "vpu/otpu_quant.sv")] = quant_source(
            params["D"], params.get("ULANES", params["LANES"]))
    if sparkle in ("dma", "all"):
        from .sparkle import dma_source
        streams = params["LANES"] == 8 and params["D"] >= 32
        sources[sources.index(RTL / "dma/otpu_dma.sv")] = dma_source(
            params["D"], params["LANES"], streams=streams)
    if sparkle in ("seq", "all"):
        from .sparkle import seq_source
        sources[sources.index(RTL / "seq/otpu_seq.sv")] = seq_source(
            params["IMEM_WORDS"], params["D"], params["S"], params["WIN"])
    if sparkle == "secomp":
        from .sparkle import se_composite_source
        # VPU fixes AW=20, CNS=3 and HA=2, and shares its arithmetic stages.
        sources[sources.index(RTL / "vpu/otpu_se_comp.sv")] = se_composite_source(
            params["LANES"], 21)
    if sparkle == "setail":
        from .sparkle import se_tail_source
        # The tail is instantiated only in the eight-lane stream configuration.
        sources[sources.index(RTL / "vpu/otpu_se_tail.sv")] = se_tail_source()
    return build("tb_top", sources + mem + [TB / "tb_top.sv"], params)


def run(cfg, programs: list, images: list, *args, keep: Path | None = None, **kw):
    """Run the RTL; returns (drams as uint8 arrays, tmems as uint32 arrays, stats). The run's
    files (DRAM images, up to the machine's DRAM size) live in a temporary directory that is
    removed afterwards, on any exit (simtmp.tempdir: on disk where /tmp is in RAM), unless
    `keep` names a directory to leave them in."""
    if keep:
        return _run(cfg, programs, images, *args, keep=keep, **kw)
    with simtmp.tempdir("otpu_") as d:
        return _run(cfg, programs, images, *args, keep=d, **kw)


def _write_dram_image(path: Path, image: np.ndarray, program: np.ndarray | None = None,
                      boot_at: int | None = None, chunk_bytes: int = 1 << 20) -> None:
    """Write the original big-endian word image without image-sized temporaries.

    The final partial word is zero padded before the optional boot gap/program.
    Each conversion owns at most chunk_bytes; input arrays remain unchanged.
    """
    if chunk_bytes <= 0 or chunk_bytes % 4:
        raise ValueError("DRAM serialization chunk must be a positive multiple of four")
    padded = (len(image) + 3) // 4 * 4
    if boot_at is not None and (boot_at < padded or boot_at % 4):
        raise ValueError("boot address must follow the padded image on a word boundary")
    with path.open("wb") as stream:
        full = len(image) // 4 * 4
        for start in range(0, full, chunk_bytes):
            block = np.ascontiguousarray(image[start:min(start + chunk_bytes, full)])
            block.view("<u4").astype(">u4").tofile(stream)
        if full != len(image):
            tail = np.zeros(4, np.uint8)
            tail[:len(image) - full] = image[full:]
            tail.view("<u4").astype(">u4").tofile(stream)
        if boot_at is not None:
            gap = boot_at - padded
            zeros = bytes(min(gap, chunk_bytes))
            while gap:
                count = min(gap, chunk_bytes)
                stream.write(zeros[:count])
                gap -= count
            for start in range(0, len(program), chunk_bytes // 4):
                program[start:start + chunk_bytes // 4].astype(">u4").tofile(stream)


def _run(cfg, programs: list, images: list, dram_lat: int = 8, max_cycles: int = 50_000_000,
        keep: Path | None = None, trace: bool = False, uarch: dict | None = None,
        axi: bool | None = None, boot: bool | None = None, stall: int | None = None,
        seed: int | None = None, bw: int | None = None, lat: int | None = None,
        plusargs: list | None = None, args=None, ldc: int | None = None,
        pokes: dict | None = None, again: list | None = None, reload: bool = False,
        error_ok: bool = False):
    """Run the RTL; returns (drams as uint8 arrays, tmems as uint32 arrays, stats). args: the
    run's arguments (R8..R15 at the start, as isasim.Machine). ldc: MEMORY's LDC for this run
    (the core at MEMORY's LDC_MHZ unless `plusargs` set +ldc_ratio: ldc_plusargs). pokes:
    {slice: [(cycle, DRAM byte address, uint32 word)]}, the host's writes during the run (the
    behavioural DRAM, or the native memory model: not the LDC). again: more runs of the same
    programs in the same simulation, after the first halts, as the host runs a program again
    (the memory path is not reset between them; tb_top +runs), each {"args": its arguments
    (default: the run before's), "pokes": {slice: [(DRAM byte address, uint32 word)]}, the
    host's writes before it (the native memory model only)}; reload: the programs loaded again
    before each (boot only). error_ok: a run that stops with an error (an illegal instruction,
    a WAITW timeout) returns its state too, stats["error"] set. The result is the state after
    the last run."""
    from . import isa as I
    run_args = args
    axi = MEMORY["AXI"] if axi is None else axi
    axi = axi and cfg.D == 128
    boot = MEMORY["BOOT"] if boot is None else boot
    stall = MEMORY["STALL"] if stall is None else stall
    seed = MEMORY["SEED"] if seed is None else seed
    ldc = (MEMORY["LDC"] if ldc is None else ldc) if axi else 0
    tmp = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="otpu_"))
    tmp.mkdir(parents=True, exist_ok=True)
    imgs, progs, image_lengths = [], [], []
    for s in range(cfg.S):
        words = I.assemble(programs[s])
        if len(words) > cfg.IMEM_WORDS:
            raise ValueError("program does not fit IMEM")
        _write_hex(tmp / f"prog_{s}.hex", words)
        img = np.asarray(images[s], np.uint8)
        imgs.append(img)
        image_lengths.append((len(img) + 3) // 4 * 4)
        progs.append(np.asarray(words, "<u4"))
    # boot: every slice's program right after the largest image (one loader address), or, if
    # there is no room, above the machine's DRAM (the simulated DRAM is then doubled)
    at = -(-max(image_lengths) // cfg.D) * cfg.D
    grow = boot and at + 4 * max(len(p) for p in progs) > cfg.DRAM_BYTES
    if grow:
        at = cfg.DRAM_BYTES
    exe = build_top(cfg, 20 if axi else dram_lat, uarch, axi,
                    2 * cfg.DRAM_BYTES if grow else None, ldc)
    for s in range(cfg.S):
        if boot and 4 * len(progs[s]) > cfg.DRAM_BYTES:
            raise ValueError("no room in DRAM for the program")
        _write_dram_image(tmp / f"dram_{s}.bin", imgs[s],
                          progs[s] if boot else None, at if boot else None)
    # Only lengths are needed for output validation. Release any dtype-converted
    # images before starting the simulator; caller-owned inputs stay untouched.
    del imgs, img
    for s, pk in (pokes or {}).items():
        if axi and ldc:
            raise ValueError("pokes: the behavioural DRAM or the native memory model (not LDC)")
        (tmp / f"poke_{s}.txt").write_text("".join(
            f"{int(c):x} {int(a) // 4:x} {int(v) & 0xFFFFFFFF:x}\n" for c, a, v in sorted(pk)))
    again = list(again or [])
    between = {}
    for r, a in enumerate(again, 1):
        for s, pk in (a.get("pokes") or {}).items():
            if not axi or ldc:
                raise ValueError("again's pokes: the native memory model only (axi, not LDC)")
            between.setdefault(s, []).extend((r, int(ad), int(v)) for ad, v in pk)
    for s, pk in between.items():
        (tmp / f"pokeb_{s}.txt").write_text("".join(
            f"{r:x} {ad // 4:x} {v & 0xFFFFFFFF:x}\n" for r, ad, v in pk))
    args = [str(exe), f"+dir={tmp}", f"+max_cycles={max_cycles}"] + (["+trace"] if trace else [])
    args += list(plusargs or [])
    args += [f"+arg{k}={int(v) & 0xFFFFFFFF}" for k, v in enumerate(run_args or [])]
    if again:
        args += [f"+runs={1 + len(again)}"] + (["+reload"] if reload else [])
        for r, a in enumerate(again, 1):
            args += [f"+r{r}_arg{k}={int(v) & 0xFFFFFFFF}" for k, v in enumerate(a.get("args") or [])]
    if axi:
        args += [f"+axi_stall={stall}", f"+axi_seed={seed}",
                 f"+axi_bw={MEMORY['BW'] if bw is None else bw}",
                 f"+axi_lat={MEMORY['LAT'] if lat is None else lat}"]
    if ldc:                            # the first of a plusarg wins: the caller's
        args += ldc_plusargs(ldc, MEMORY["LDC_MHZ"])
    if boot:
        args += ["+boot", f"+boot_addr={at}", f"+boot_n={max(len(p) for p in progs) // 8}"]
    for image in images:
        simmemory.flush(image)
    r = run_sim(args, timeout=3600)
    out = r.stdout + r.stderr
    import re
    m = re.search(r"RESULT cycles=(\d+) halted=(\d+) error=(\d+)", out)
    if not m:
        raise RuntimeError(f"RTL simulation failed:\n{out[-3000:]}")
    cycles, halted, err = (int(x) for x in m.groups())
    if not halted or (err and not error_ok):
        raise RuntimeError(f"RTL did not halt cleanly (halted={halted} error={err}):\n{out[-2000:]}")
    icounts = [int(x) for x in re.findall(r"SLICE \d+ icount=(\d+)", out)]
    drams = [simmemory.read_dump(tmp / f"dram_out_{s}.bin") for s in range(cfg.S)]
    for s in range(cfg.S):             # a short dump (e.g. a full disk) is an error, not a result
        if len(drams[s]) < image_lengths[s]:
            raise RuntimeError(f"dram_out_{s}.bin has {len(drams[s])} bytes, fewer than the "
                               f"{image_lengths[s]}-byte image: the dump was cut short")
    if boot:                           # the program is not part of the result
        drams = [d[:cfg.DRAM_BYTES] for d in drams]
        for s in range(cfg.S):
            drams[s][at:at + 4 * len(progs[s])] = 0
    tmems = [_read_hex(tmp / f"tmem_{s}.hex", cfg.TMEM_WORDS) for s in range(cfg.S)]
    stats = {"cycles": cycles, "instructions": icounts}
    if error_ok:
        stats["error"] = bool(err)
    if axi:
        # per channel: the model's reads, writes, row opens and partial writes, and the adapter's
        # counters; reads and writes as (commands, beats) (a native command is one beat), ar_a:
        # the A runs and SW fill reads, rmw_a: the A and SW writes with a partial byte mask
        mem = [dict(zip(("rd", "wr", "row_miss", "rmw"), map(int, m))) for m in
               re.findall(r"MEM ch\d rd=(\d+) wr=(\d+) row_miss=(\d+) rmw=(\d+)", out)]
        nat = [dict(kv.split("=") for kv in m.split()) for m in
               re.findall(r"NATIVE ch\d (.*)", out)]
        nat = [{k: int(v) for k, v in d.items()} for d in nat]
        stats["native"] = nat
        stats["axi_reads"] = [(m["rd"], m["rd"]) for m in mem]
        stats["axi_writes"] = [(m["wr"], m["wr"]) for m in mem]
        stats["axi_detail"] = [{"ar_a": n["a_runs"] + n["sw_rd"], "row_miss": m["row_miss"],
                                "rmw": m["rmw"], "rmw_a": n["part_a"] + n["part_sw"]}
                               for m, n in zip(mem, nat)]
    if trace:
        stats["trace"] = out
    return drams, tmems, stats
