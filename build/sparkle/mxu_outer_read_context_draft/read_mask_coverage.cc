// UNEXECUTED auxiliary coverage audit. Not a memory or controller theorem.
// Build/load only inside sparkle_bounded, against the authenticated Yosys.
#include "kernel/register.h"
#include "kernel/sigtools.h"
#include "kernel/satgen.h"

USING_YOSYS_NAMESPACE
PRIVATE_NAMESPACE_BEGIN

// A fresh actual SatGen instance for every row prevents accidental coupling
// between rows. No synthesis, undef simplification, or assumptions on masks.
static bool coverage_row(int value, int mask, int yvalue, int yundef)
{
    RTLIL::Design design;
    auto module = design.addModule(RTLIL::IdString("\\coverage"));
    auto v = module->addWire(RTLIL::IdString("\\value"), 1);
    auto m = module->addWire(RTLIL::IdString("\\mask"), 1);
    auto y = module->addWire(RTLIL::IdString("\\result"), 1);
    auto cell = module->addCell(RTLIL::IdString("\\read"), ID($mux));
    cell->setParam(ID::WIDTH, 1);
    cell->setPort(ID::A, v);
    cell->setPort(ID::B, RTLIL::SigSpec(RTLIL::State::Sx, 1));
    cell->setPort(ID::S, m);
    cell->setPort(ID::Y, y);
    SigMap sigmap(module);
    ezSatPtr ez;
    SatGen sat(ez.get(), &sigmap);
    sat.model_undef = true;
    if (!sat.importCell(cell))
        log_error("Coverage mux was not imported.\n");
    auto constrain = [&](int expression, bool expected) {
        ez->assume(expected ? expression : ez->NOT(expression));
    };
    constrain(sat.importDefSigSpec(v).at(0), value);
    constrain(sat.importDefSigSpec(m).at(0), mask);
    constrain(sat.importUndefSigSpec(v).at(0), false);
    constrain(sat.importUndefSigSpec(m).at(0), false);
    constrain(sat.importDefSigSpec(y).at(0), yvalue);
    constrain(sat.importUndefSigSpec(y).at(0), yundef);
    ez->setSolverTimeout(10);
    bool result = ez->solve();
    if (ez->getSolverTimeoutStatus())
        log_error("Coverage query timed out; no result accepted.\n");
    return result;
}

struct ReadMaskCoveragePass : Pass {
    ReadMaskCoveragePass() : Pass("outer_read_mask_coverage",
        "audit actual SatGen read value/undef overapproximation") {}
    void execute(std::vector<std::string> args, RTLIL::Design *design) override
    {
        if (args.size() != 1)
            log_error("outer_read_mask_coverage accepts no arguments.\n");
        (void)design;
        int rows = 0, satisfiable = 0;
        for (int v = 0; v < 2; ++v)
        for (int m = 0; m < 2; ++m)
        for (int y = 0; y < 2; ++y)
        for (int u = 0; u < 2; ++u) {
            bool expected = u == m && (m || y == v);
            bool actual = coverage_row(v, m, y, u);
            log("COVERAGE value=%d mask=%d yvalue=%d yundef=%d sat=%d expected=%d\n",
                v, m, y, u, int(actual), int(expected));
            if (actual != expected)
                log_error("Read mask coverage relation differs.\n");
            ++rows;
            satisfiable += actual;
        }
        if (rows != 16 || satisfiable != 6)
            log_error("Incomplete read mask coverage enumeration.\n");
        log("OUTER_READ_MASK_COVERAGE_PASS rows=16 sat=6 unsat=10\n");
    }
} ReadMaskCoveragePass;

PRIVATE_NAMESPACE_END
