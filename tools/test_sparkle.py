"""Run native Sparkle generation and cycle-level RTL differential tests (stdlib only)."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / ".lake/build/bin/opentpu-gen"


def run(*args, **kwargs):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, capture_output=True,
                            text=True, timeout=600, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def compile_simulation(work, top, sources, *options):
    run("verilator", "--binary", "--timing", "-j", "4", "-Wno-fatal",
        "--top-module", top, "--Mdir", work / "obj", *options, *sources,
        ROOT / "tests/sparkle" / f"{top}.sv")
    return work / "obj" / f"V{top}"


def simulate(work, top, sources, *options, run_args=()):
    print(run(compile_simulation(work, top, sources, *options), *run_args), end="")


def tmem_tests():
    for words, lanes, nrp, nwp, wpb, gr, gw, host, guests in [
        (64, 4, 4, 3, 1, 15, 7, 0, 0),
        (64, 4, 4, 3, 1, 0, 0, 0, 0),
        (128, 8, 8, 4, 1, 1, 2, 1, 160),
        (64, 4, 4, 3, 2, 5, 7, 0, 10),
        (4, 2, 2, 2, 1, 1, 0, 0, 2),
        (128, 16, 8, 4, 2, 1, 2, 1, 160),
    ]:
        with tempfile.TemporaryDirectory(prefix="otpu_sparkle_tmem_") as tmp:
            work = Path(tmp)
            generated = work / "tmem.sv"
            run(GEN, "tmem-core", words, lanes, nrp, nwp, wpb, gr, gw, host, guests, generated)
            simulate(work, "tb_tmem", [ROOT / "rtl/mem/otpu_tmem.sv", generated],
                     f"-GWORDS={words}", f"-GLANES={lanes}", f"-GNRP={nrp}", f"-GNWP={nwp}",
                     f"-GWPB={wpb}", f"-GGEN_R={gr}", f"-GGEN_W={gw}",
                     f"-GSH_HOST={host}", f"-GSH_MASK={guests}")


def tmem_abi_test():
    # Run the project's original standalone scoreboard through the native ABI,
    # including its simulation startup under randomized Verilator initialization.
    with tempfile.TemporaryDirectory(prefix="otpu_sparkle_tmem_abi_") as tmp:
        work = Path(tmp)
        generated = work / "tmem.sv"
        run(GEN, "tmem", 256, 4, 3, 2, 1, 7, 3, 0, 0, generated)
        run("verilator", "--binary", "--timing", "-j", "4", "-Wno-fatal",
            "--top-module", "tb_tmem", "--Mdir", work / "obj", generated,
            ROOT / "sim/verilator/tb_tmem.sv")
        print(run(work / "obj/Vtb_tmem", "+verilator+rand+reset+2", "+verilator+seed+271828"), end="")


def vtree_tests():
    for lanes, latency in [(1, 4), (2, 4), (4, 4), (8, 4), (16, 4), (8, 5), (4, 7)]:
        with tempfile.TemporaryDirectory(prefix="otpu_sparkle_vtree_") as tmp:
            work = Path(tmp)
            generated = work / "vtree.sv"
            run(GEN, "vtree-core", lanes, latency, generated)
            simulate(work, "tb_vtree", [ROOT / "rtl/vpu/otpu_fp.sv",
                     ROOT / "rtl/vpu/otpu_fpipe.sv", ROOT / "rtl/vpu/otpu_vtree.sv", generated],
                     f"-GLANES={lanes}", f"-GLA={latency}", "-DSYNTHESIS")


def seq_dispatch_tests():
    from prove_sparkle_seq_dispatch import harness
    for depth, slices in [(32, 1), (96, 3), (128, 4)]:
        with tempfile.TemporaryDirectory(prefix="otpu_sparkle_dispatch_") as tmp:
            work = Path(tmp)
            generated = work / "dispatch.sv"
            reference = work / "reference.sv"
            run(GEN, "seq-dispatch", depth, slices, generated)
            reference.write_text(harness(depth, slices).split("module seq_dispatch_miter", 1)[0])
            simulate(work, "tb_seq_dispatch", [ROOT / "rtl/top/otpu_pkg.sv", reference, generated],
                     f"-GD={depth}", f"-GS={slices}", "-DSYNTHESIS",
                     run_args=("+verilator+rand+reset+2", "+verilator+seed+271828"))


def seq_tests():
    for words, depth, slices, slots in [(1024, 32, 1, 2), (1024, 64, 2, 8),
                                       (3072, 96, 3, 16), (1024, 128, 4, 32)]:
        with tempfile.TemporaryDirectory(prefix="otpu_sparkle_seq_") as tmp:
            work = Path(tmp)
            generated = work / "seq.sv"
            run(GEN, "seq-core", words, depth, slices, slots, generated)
            simulate(work, "tb_seq", [ROOT / "rtl/top/otpu_pkg.sv", ROOT / "rtl/seq/otpu_seq.sv", generated],
                     f"-GIMEM_WORDS={words}", f"-GD={depth}", f"-GS={slices}", f"-GWIN={slots}",
                     run_args=("+verilator+rand+reset+2", "+verilator+seed+271828"))


def actram_tests():
    from sparkle_actram_reference import reference
    for d, m, r, b, l in [(32, 2, 6, 8, 8), (128, 4, 16, 8, 16),
                           (32, 1, 1, 8, 4), (32, 3, 3, 8, 8), (32, 8, 8, 64, 8),
                           (96, 2, 2, 8, 24), (8, 2, 4, 4, 1)]:
        with tempfile.TemporaryDirectory(prefix="otpu_sparkle_act_") as tmp:
            work = Path(tmp)
            generated = work / "actram.sv"
            run(GEN, "actram-core", d, m, r, b, l, generated)
            simulate(work, "tb_actram", [reference(work), generated],
                     f"-GD={d}", f"-GMCOLS={m}", f"-GROWS={r}", f"-GBLOCKS={b}", f"-GLANES={l}",
                     run_args=("+verilator+rand+reset+2", "+verilator+seed+271828"))


def actram_startup_self_test():
    from sparkle_actram_reference import reference
    with tempfile.TemporaryDirectory(prefix="otpu_sparkle_act_startup_") as tmp:
        work = Path(tmp)
        generated = work / "actram.sv"
        run(GEN, "actram-core", 8, 2, 4, 4, 1, generated)
        source, count = re.subn(
            r"`ifndef SYNTHESIS\n    initial for \(integer a=0;[^\n]+\n`endif\n",
            "", generated.read_text())
        if count == 0:
            raise RuntimeError("ACT RAM startup mutation target missing")
        generated.write_text(source)
        exe = compile_simulation(work, "tb_actram", [reference(work), generated],
                                 "-GD=8", "-GMCOLS=2", "-GROWS=4", "-GBLOCKS=4", "-GLANES=1")
        try:
            run(exe, "+verilator+rand+reset+2", "+verilator+seed+271828")
        except RuntimeError as error:
            if "ACT RAM mismatch" not in str(error):
                raise
        else:
            raise RuntimeError("ACT RAM checker did not reject missing simulation initialization")
        print("PASS ACT RAM startup checker: missing memory clearing rejected", flush=True)


def actram_boundary_self_test():
    from sparkle_actram_reference import reference
    with tempfile.TemporaryDirectory(prefix="otpu_sparkle_act_boundary_") as tmp:
        work = Path(tmp)
        generated = work / "actram.sv"
        run(GEN, "actram-core", 32, 2, 4, 2, 8, generated)
        original = "assign _gen_placed_data = ({192'd0, w_data_h} << {w_idx_h[4:0], 3'd0});"
        # Reintroduce the original data-wrap defect. The unchanged reference RTL
        # synthesis semantics discard these overflowing bytes.
        mutated = "assign _gen_placed_data = (({192'd0, w_data_h, 192'd0, w_data_h} << {w_idx_h[4:0], 3'd0}) >> 256);"
        code = generated.read_text()
        if code.count(original) != 1:
            raise RuntimeError("ACT RAM boundary mutation target missing")
        generated.write_text(code.replace(original, mutated))
        exe = compile_simulation(work, "tb_actram", [reference(work), generated],
                                 "-GD=32", "-GMCOLS=2", "-GROWS=4", "-GBLOCKS=2", "-GLANES=8")
        try:
            run(exe, "+verilator+rand+reset+2", "+verilator+seed+271828")
        except RuntimeError as error:
            if "ACT RAM mismatch" not in str(error):
                raise
        else:
            raise RuntimeError("ACT RAM checker did not reject data wraparound")
        print("PASS ACT RAM boundary checker: data wraparound rejected", flush=True)


def main():
    run("lake", "build", "OpenTPU", "opentpu-gen", "opentpu-test")
    print(run(ROOT / ".lake/build/bin/opentpu-test"), end="")
    for slices, lanes in [(1, 1), (1, 8), (2, 4), (3, 8), (4, 16)]:
        with tempfile.TemporaryDirectory(prefix="otpu_sparkle_") as tmp:
            work = Path(tmp)
            generated = work / "collective.sv"
            run(GEN, "collective-core", slices, lanes, generated)
            simulate(work, "tb_collective", [ROOT / "rtl/top/otpu_pkg.sv",
                     ROOT / "rtl/top/otpu_coll.sv", generated],
                     f"-GS={slices}", f"-GLANES={lanes}")

    for lm, la in [(2, 4), (3, 7)]:
        with tempfile.TemporaryDirectory(prefix="otpu_sparkle_fp_") as tmp:
            work = Path(tmp)
            generated = work / "float.sv"
            run(GEN, "float", lm, la, generated)
            simulate(work, "tb_float", [ROOT / "rtl/vpu/otpu_fp.sv",
                     ROOT / "rtl/vpu/otpu_fpipe.sv", generated],
                     f"-GLM={lm}", f"-GLA={la}", f"-DDUT_MUL=otpu_fmul_sparkle_{lm}",
                     f"-DDUT_ADD=otpu_fadd_sparkle_{la}")

    with tempfile.TemporaryDirectory(prefix="otpu_sparkle_fpipe_") as tmp:
        work = Path(tmp)
        generated = work / "fpipe.sv"
        run(GEN, "fpipe", generated)
        simulate(work, "tb_fpipe", [ROOT / "rtl/vpu/otpu_fp.sv", generated,
                 ROOT / "rtl/vpu/otpu_fpipe.sv"])

    actram_tests()
    actram_startup_self_test()
    actram_boundary_self_test()
    tmem_tests()
    tmem_abi_test()
    vtree_tests()
    seq_dispatch_tests()
    seq_tests()


if __name__ == "__main__":
    main()
