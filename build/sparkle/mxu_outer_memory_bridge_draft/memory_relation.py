"""One-way extension of a stated discrete memory relation; no SV/event parity."""
import copy
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_expansion_draft'),
    str(ROOT/'build/sparkle/mxu_outer_initial_ownership_draft')]
from memory_expansion import ALL_D,PREFIX
from outer_initial_ownership import inventory,RESIDUAL
from dot_initial_store import need


def authenticate_memory_model(source,freeze):
    from constant_read_refinement import authenticate_read_rule
    from dot_definedness_mux_slices import audit_mux_model
    read_rule=authenticate_read_rule(source,freeze)
    simlib=Path(source)/'techlibs/common/simlib.v';text=simlib.read_text()
    start=text.index('module \\$mem_v2 ');body=text[start:text.index('endmodule',start)]
    for anchor in ('reg [WIDTH-1:0] memory [SIZE-1:0];',
        'memory[i] = INIT >>> (i*WIDTH);','if (WR_EN[i*WIDTH+j]) begin',
        'memory[WR_ADDR[i*ABITS +: ABITS] - OFFSET][j] = WR_DATA[i*WIDTH+j];'):
        need(anchor in body,'pinned memory coordinate rule differs')
    cc=Path(source)/'kernel/satgen.cc';header=Path(source)/'kernel/satgen.h'
    cc_sha=freeze(cc);header_sha=freeze(header);freeze(simlib)
    need('Unsupported internal cell types: $pow $fsm $mem*' in cc.read_text(),'native memory SAT support changed')
    htext=header.read_text();mux_rule=audit_mux_model(htext)
    need('ez->vec_or(vec_undef, ez->vec_iff(vec_y, vec_yy))' in htext,'actual undefined-output gating changed')
    return {'simlib_read_equation':read_rule,'satgen_cc_sha256':cc_sha,'satgen_header_sha256':header_sha,
        'mux_mask_equation':mux_rule,'known_selector_extension':scalar_certificate(),
        'memory_relation_is_explicit_discrete_lift_not_a_native_SatGen_cell':True,
        'known_full_Q_and_certified_controls_required':True,'OOB_value_choices_shared_by_original_RD_identity':True,
        'source_SV_equivalence_proven':False,'event_region_equivalence_proven':False,'raw_model_identity_proven':False}


def known_mux_extension(a,ua,b,ub,s,y,uy):
    need(all(type(v)is int and v in (0,1) for v in (a,ua,b,ub,s,y,uy)),'invalid Boolean value/mask')
    chosen,mask=(b,ub) if s else (a,ua)
    # Exact known-selector SatGen undef mask + undefGating relation.
    return uy==mask and (uy==1 or y==chosen)


def scalar_certificate():
    cases=0
    for a in (0,1):
        for ua in (0,1):
            for b in (0,1):
                for ub in (0,1):
                    for s in (0,1):
                        chosen,mask=(b,ub) if s else (a,ua)
                        for y in (0,1):
                            if mask==0 and y!=chosen:continue
                            need(known_mux_extension(a,ua,b,ub,s,y,mask),'known selector extension failed')
                            cases+=1
    return {'admissible_selected_value_mask_assignments':cases,
        'all_selected_undefined_value_representatives_preserved':True,
        'rule':'known selector fixes output mask to selected arm; known Y equals selected value; undefined Y may match any already chosen source value',
        'unknown_selector_rule_claimed':False,'reverse_model_identity_claimed':False}


def audit_equations(original,expanded,manifest,expected=RESIDUAL):
    records=inventory(original,expected)
    need(records==manifest['original_memory_inventory'],'actual memory mode/address inventory differs')
    words={};q_seen=set()
    for word in manifest['word_state']:
        key=(word['memory'],word['address']);qs=word['q']
        need(key not in words and len(qs)==records[key[0]]['width'] and word['initial']=='x'*len(qs),
            'word ownership/initial predicate differs')
        need(all(type(q)is int and q not in q_seen for q in qs) and len(set(qs))==len(qs),'word Q alias collision')
        words[key]=qs;q_seen.update(qs)
    need(set(words)=={(name,a) for name,r in records.items() for a in range(r['size'])},'complete physical words missing')
    original_reads={}
    for name,r in records.items():
        pins=original['cells'][name]['connections']
        for port,address in enumerate(r['read_address_vectors']):
            for bit in range(r['width']):
                q=pins['RD_DATA'][port*r['width']+bit];meaning=(name,tuple(address),bit)
                need(type(q)is int,'constant original RD driver')
                if q in original_reads:need(original_reads[q]['meaning']==meaning,'aliased original RD bits have different memory meanings')
                else:original_reads[q]={'meaning':meaning,'occurrences':[]}
                original_reads[q]['occurrences'].append({'memory':name,'read_port':port,'bit_lsb':bit})
    created=manifest['expansion']['new_mux_cells'];need(len(created)==len(set(created)),'duplicate expansion cell')
    drivers={}
    for name in created:
        c=expanded['cells'][name];p=c['connections']
        need(c['type']=='$mux' and set(c['parameters'])=={'WIDTH'} and int(c['parameters']['WIDTH'],2)==1 and
            c['port_directions']=={'A':'input','B':'input','S':'input','Y':'output'} and
            set(p)=={'A','B','S','Y'} and all(len(v)==1 for v in p.values()),'added scalar mux contract differs')
        y=p['Y'][0];need(type(y)is int and y not in drivers,'added mux driver alias');drivers[y]=(name,p)
    used=set()
    def mux(bit):
        need(bit in drivers,'missing concrete expansion mux');name,p=drivers[bit]
        need(name not in used,'unexpected shared expansion tree owner');used.add(name);return p
    seen_reads=set();out_of_range=0;leaves_checked=0
    for read in manifest['expansion']['reads']:
        q=read['original_read_bit'];need(q not in seen_reads and q in original_reads,'missing/duplicate original RD identity');seen_reads.add(q)
        expected_read=original_reads[q];name,address,bit=expected_read['meaning'];r=records[name];depth=r['read_address_bits']
        need(read['occurrences']==expected_read['occurrences'] and read['address']==list(address),'original RD alias/fanout coordinate differs')
        need(address[depth:]==('0',)*(len(address)-depth),'nonliteral high address discarded')
        leaves=[words[name,a][bit] if a<r['size'] else 'x' for a in range(1<<depth)]
        need(read['leaves_lsb_order']==leaves and read['out_of_range_leaves_are_X'] is True,'complete read leaves or OOB value differ')
        def tree(root,level,base):
            if level<0:
                need(root==leaves[base],'actual read-tree leaf differs');return
            p=mux(root);need(p['S']==[address[level]],'read selector or bit ordering differs')
            tree(p['A'][0],level-1,base);tree(p['B'][0],level-1,base+(1<<level))
        if depth:tree(q,depth-1,0)
        else:
            p=mux(q);need(p=={'A':[leaves[0]],'B':['0'],'S':['0'],'Y':[q]},'zero-depth read output driver differs')
        out_of_range+=sum(v=='x' for v in leaves);leaves_checked+=len(leaves)
    need(seen_reads==set(original_reads),'original RD identity inventory incomplete')
    writes={}
    for row in manifest['expansion']['writes']:
        key=(row['memory'],row['address'],row['bit_lsb']);name,address,bit=key;r=records[name]
        need(key not in writes and 0<=bit<r['width'],'duplicate/invalid physical write coordinate')
        port=r['write_addresses'].index(address);pins=original['cells'][name]['connections']
        q=words[name,address][bit];data=pins['WR_DATA'][port*r['width']+bit];enable=pins['WR_EN'][port*r['width']+bit]
        need(row['write_port']==port and row['q']==q and row['data']==data and row['enable']==enable,
            'actual masked write coordinate differs')
        p=mux(row['d']);need(p=={'A':[q],'B':[data],'S':[enable],'Y':[row['d']]},'complete masked write mux differs')
        writes[key]=row['d']
    expected_writes={(n,a,b) for (n,a),qs in words.items() for b in range(len(qs))}
    need(set(writes)==expected_writes and used==set(created),'missing write bit or unexplained expansion cell')
    ordinary={name for name,c in original['cells'].items() if c['type'] not in ('$dff','$mem_v2')}
    need(set(expanded['cells'])==ordinary|set(created),'unexplained or missing ordinary/expansion owner')
    state=manifest['full_state_coordinates'];qs=[r['q'] for r in state]
    need(len(qs)==len(set(qs)) and expanded['ports'][ALL_D]['bits']==[r['d'] for r in state],'full physical Q/D coverage differs')
    need({(r['memory'],r['address'],r['bit_lsb']) for r in state if r['kind']=='array_word'}==expected_writes,
         'full word-state coordinate inventory differs')
    need({(r['cell'],r['bit_lsb']) for r in state if r['kind']=='ordinary_DFF'}==
         {(name,i) for name,c in original['cells'].items() if c['type']=='$dff' for i in range(len(c['connections']['Q']))},
         'full ordinary-state coordinate inventory differs')
    for row in state:
        if row['kind']=='array_word':
            need(row['q']==words[row['memory'],row['address']][row['bit_lsb']] and
                 row['d']==writes[row['memory'],row['address'],row['bit_lsb']],'word full-Q/D observation differs')
        else:
            need(row['kind']=='ordinary_DFF','unknown physical state kind')
            c=original['cells'][row['cell']]
            need(c['type']=='$dff' and c['connections']['Q'][row['bit_lsb']]==row['q'] and
                c['connections']['D'][row['bit_lsb']]==row['d'],'ordinary physical state changed')
    for name,c in original['cells'].items():
        if c['type'] not in ('$dff','$mem_v2'):need(expanded['cells'][name]==c,'ordinary cell body/fanout changed')
    for name,p in original['ports'].items():need(expanded['ports'][name]==p,'original public input/output changed')
    for name,n in original['netnames'].items():
        old=copy.deepcopy(n);old.get('attributes',{}).pop('init',None)
        need(expanded['netnames'][name]==old,'original alias/fanout changed')
    return {'original_memories':len(records),'word_count':len(words),'word_bits':len(q_seen),'original_RD_bit_ids':len(original_reads),
        'read_occurrence_count':sum(len(v['occurrences']) for v in original_reads.values()),'finite_read_leaves_audited':leaves_checked,
        'out_of_range_X_leaves_preserved':out_of_range,'all_masked_write_bits':len(writes),'physical_Q_D_bits':len(state),
        'all_original_ordinary_consumers_ports_aliases_preserved':True,'all_original_RD_aliases_share_one_value_undef_pair':True,
        'relation':'in-range reads equal existing defined word Q; OOB read U=1 with source-chosen value per original RD bit shared across every consumer; known write enables select old Q or actual data',
        'extension_direction':'every coherent source relation assignment extends to added muxes preserving every original wire; extra source OOB correlations are not removed',
        'source_value_choices_reselected':False,'reverse_raw_model_identity_proven':False,'SV_event_region_equivalence_proven':False,
        'source_SV_parity_proven':False,'in_range_assumption':False}
