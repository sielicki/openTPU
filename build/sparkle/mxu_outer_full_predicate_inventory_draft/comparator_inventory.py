"""Complete comparator inventory; exact-wire shortlist is diagnostic, never a lemma."""
import hashlib
import json

TYPES={'$lt','$gt','$le','$ge','$eq','$ne','$eqx','$nex'}

def need(value,message):
    if not value:raise ValueError(message)

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))

def vector_key(bits):
    # Unknown literals do not identify one shared nondeterministic choice.
    if any(type(b)is str and b not in ('0','1') for b in bits):return None
    need(all(type(b)is int and b>=0 or type(b)is str and b in ('0','1') for b in bits),'invalid operand coordinate')
    return canonical(bits)

def eligible(name,cell):
    expected='$gt' if name.startswith('gold:') else '$lt' if name.startswith('gate:') else None
    if cell['type']!=expected:return False
    params=cell['parameters']
    if set(params)!={'A_WIDTH','B_WIDTH','Y_WIDTH','A_SIGNED','B_SIGNED'}:return False
    return {k:int(v,2) for k,v in params.items()}==dict(A_WIDTH=32,B_WIDTH=32,Y_WIDTH=1,A_SIGNED=0,B_SIGNED=0)

def init_tables(db):
    db.execute('CREATE TABLE inventory_comparator(name TEXT PRIMARY KEY,side TEXT,eligible INTEGER,a TEXT,b TEXT,body TEXT)')
    db.execute('CREATE INDEX inventory_a ON inventory_comparator(side,eligible,a)')
    db.execute('CREATE INDEX inventory_b ON inventory_comparator(side,eligible,b)')
    db.execute('CREATE TABLE inventory_candidate(gold TEXT,gate TEXT,ab INTEGER,ba INTEGER,PRIMARY KEY(gold,gate))')

def add(db,name,cell):
    if cell['type'] not in TYPES:return False
    side='gold' if name.startswith('gold:') else 'gate' if name.startswith('gate:') else 'other'
    db.execute('INSERT INTO inventory_comparator VALUES(?,?,?,?,?,?)',
        (name,side,int(eligible(name,cell)),vector_key(cell['connections']['A']),vector_key(cell['connections']['B']),canonical(cell)))
    return True

def shortlist(db):
    # Exact complete-vector keys, not digests: no collision-based pairing.
    db.execute("""INSERT INTO inventory_candidate
        SELECT g.name,n.name,(g.a IS NOT NULL AND g.a=n.b),(g.b IS NOT NULL AND g.b=n.a)
        FROM inventory_comparator g JOIN inventory_comparator n
        ON n.side='gate' AND n.eligible=1 AND
           ((g.a IS NOT NULL AND g.a=n.b) OR (g.b IS NOT NULL AND g.b=n.a))
        WHERE g.side='gold' AND g.eligible=1""")
    db.commit()

def output(db,inventory_path,candidates_path,groups_path,driver):
    counts={};shape={};groups={'unmatched':0,'unique':0,'ambiguous':0,'unsupported':0}
    def emit(stream,row):stream.write(canonical(row)+'\n')
    with inventory_path.open('w') as stream:
        for name,side,ok,body in db.execute('SELECT name,side,eligible,body FROM inventory_comparator ORDER BY name'):
            cell=json.loads(body);key=side+':'+cell['type'];counts[key]=counts.get(key,0)+1
            shape[side]=shape.get(side,0)+ok
            producers={pin:[driver(bit) if type(bit)is int else {'literal':bit} for bit in bits]
                       for pin,bits in cell['connections'].items()}
            emit(stream,{'name':name,'side':side,'body':cell,'body_sha256':hashlib.sha256(body.encode()).hexdigest(),
                'eligible_unsigned32_opposite_schema':bool(ok),'actual_coordinate_drivers':producers})
    with candidates_path.open('w') as stream:
        for gold,gate,ab,ba in db.execute('SELECT gold,gate,ab,ba FROM inventory_candidate ORDER BY gold,gate'):
            emit(stream,{'gold':gold,'gate':gate,'gold_A_gate_B_complete_identity':bool(ab),
                'gold_B_gate_A_complete_identity':bool(ba),'operand_totality_proven':False,'operand_equality_proven':False})
    with groups_path.open('w') as stream:
        for name,side,ok in db.execute('SELECT name,side,eligible FROM inventory_comparator ORDER BY name'):
            column='gold' if side=='gold' else 'gate';other='gate' if side=='gold' else 'gold'
            count=db.execute('SELECT COUNT(*) FROM inventory_candidate WHERE '+column+'=?',(name,)).fetchone()[0] if ok else 0
            classification='unsupported' if not ok else 'unmatched' if count==0 else 'unique' if count==1 else 'ambiguous'
            groups[classification]+=1
            # Stream each group, avoiding an unbounded list for ambiguous vectors.
            stream.write('{"name":'+canonical(name)+',"classification":'+canonical(classification)+',"candidate_count":'+str(count)+',"candidates":[')
            first=True
            if ok:
                for row in db.execute('SELECT '+other+' FROM inventory_candidate WHERE '+column+'=? ORDER BY '+other,(name,)):
                    if not first:stream.write(',')
                    first=False;stream.write(canonical(row[0]))
            stream.write(']}\n')
    shortlisted=db.execute('SELECT COUNT(*) FROM inventory_candidate').fetchone()[0]
    all_shapes=shape.get('gold',0)*shape.get('gate',0)
    return {'complete_comparator_counts':counts,'eligible_counts':shape,'all_exact_schema_opposite_pairs':all_shapes,
        'complete_vector_identity_shortlist_count':shortlisted,'other_schema_compatible_pairs_not_shortlisted':all_shapes-shortlisted,
        'group_classification_counts':groups,'all_comparators_reported':True,'shortlist_exhaustive_for_stated_identity_criterion':True,
        'all_semantically_equivalent_pairs_identified':False,'unmatched_does_not_mean_inequivalent':True,
        'details_truncated':False,'transform_applied':False,'operand_equality_proven':False}
