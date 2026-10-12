"""Explicit reviewed pair list; no heuristic pairing or implicit theorem extension."""
from configured_operands import need


def validate(config):
    need(type(config)is dict and set(config)=={'schema_version','source','diagnostic','interval','pairs'} and
         type(config['schema_version'])is int and config['schema_version']==1,'exact configured predicate schema required')
    for name in ('source','diagnostic'):
        ref=config[name]
        need(type(ref)is dict and set(ref)=={'path','sha256'} and type(ref['path'])is str and ref['path'],
             'explicit receipt path/digest required')
        sha=ref['sha256'];need(type(sha)is str and len(sha)==64 and all(c in '0123456789abcdef' for c in sha),
                              'exact receipt SHA256 required')
    interval=config['interval'];need(type(interval)is list and len(interval)==2 and all(type(i)is int for i in interval) and
        2412<=interval[0]<interval[1]<=5928 and interval[1]==interval[0]+1,'one actual failed coordinate required')
    pairs=config['pairs']
    need(type(pairs)is list and 1<=len(pairs)<=64 and
         all(type(p)is list and len(p)==2 and all(type(n)is str for n in p) and
             p[0].startswith('gold:') and p[1].startswith('gate:') for p in pairs) and
         len({n for pair in pairs for n in pair})==2*len(pairs),'distinct ordered actual target pairs required')
    return len(pairs)
