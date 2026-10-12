"""Reuse exact prior diagnostic inputs with a private bit-demand closure only."""
import types
from pathlib import Path
import diagnose_physical as baseline
from precise_frontier import precise_closure

if __name__=='__main__':
    # Preserve the complete baseline alias/field/state/source joins unchanged.
    # Do not patch the baseline module globals or any passed checker source.
    namespace={**baseline.main.__globals__,'closure':precise_closure}
    types.FunctionType(baseline.main.__code__,namespace,'bit_demand_diagnostic')()
