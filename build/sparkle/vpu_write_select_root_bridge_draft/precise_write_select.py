"""Read-only strict bit-demand adapter; the passed whole-cell probe is unchanged."""
from precise_frontier import precise_closure
from physical_slices import require


def closure(bound):
    result={}
    require(len(bound['manifest'])==1924,'Complete measured observation occurrence count differs')
    for side in ('original','gold'):
        graph=bound[side+'_graph']
        producer=graph.producer if side=='original' else lambda b:graph.drivers.get(b)
        # Preserve each occurrence, including duplicate raw/normalized outputs.
        observations={str(i):[row[side]] for i,row in enumerate(bound['manifest'])}
        result[side]=precise_closure(graph,observations,{},bound[side+'_cuts'],bound[side+'_q'],producer)
        require(result[side]['complete_D_count']==1924,'Observation root inventory lost')
    return result
