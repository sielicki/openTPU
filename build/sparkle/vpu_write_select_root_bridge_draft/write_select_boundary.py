"""Actual424-output frontier probe; coordinate candidates are not a theorem."""
from physical_frontier import layouts,classes
from physical_slices import require
from observation_coordinates import Original,Gold
from joint_partition import owner
from control_comb import SPECS,audit
from issue_bridge import closure
from composition import chain

STATE={'red_act':1,'func':8,'tag':8,'rdb':1,'wr_row':20,'flushing':1,'fl':16,'rows':16,'dst':20}
MEMBERS={'mo_v':('mo','mt_t','v'),'mo_mask':('mo','mt_t','mask'),'mo_waddr':('mo','mt_t','waddr'),
 'mxm_v':('mxm_q','rm_t','v'),'mxm_tag':('mxm_q','rm_t','tag'),'mxm_row_last':('mxm_q','rm_t','row_last'),'mxm_waddr':('mxm_q','rm_t','waddr')}
ARRAYS={'lres','lmv','rbuf_q'}


def original_bits(db,graph,name,width,types):
    alias=name;detail={'layout_proven':False}
    if name in MEMBERS:
        alias,typ,field=MEMBERS[name];shape=types[typ];member=shape['fields'][field];bits=graph.alias(alias)
        require(len(bits)==shape['width'] and width==member['width'],'Actual packed field width differs')
        detail.update(type=typ,member=field,lsb=member['lsb'],complete_packed_width=len(bits))
        bits=bits[member['lsb']:member['lsb']+width]
    else:
        bits=graph.alias(alias);require(len(bits)==width,'Actual alias width differs '+name)
        if name in ARRAYS:
            require(width==256,'Actual eight-lane width differs')
            bits=[b for lane in reversed(range(8)) for b in bits[32*lane:32*(lane+1)]]
            detail['candidate_lane_order']=list(reversed(range(8)))
    detail.update(alias=alias,original_owner=owner(db,'netnames',alias),coordinates=bits)
    return bits,detail


def boundary(db,native,source,providers,initial,joint,writer):
    inputs,outputs=SPECS['write_select'][3:];types=layouts(source)
    expected={**{n:('input',w) for n,w in inputs.items()},**{n:('output',w) for n,w in outputs.items()}}
    require({n:(p['direction'],len(p['bits'])) for n,p in native['ports'].items()}==expected,'Native complete ABI differs')
    require(not native.get('memories') and not native.get('processes') and not any(c['type'].startswith(('$dff','$mem','$dlatch')) for c in native['cells'].values()),'Native combinational owner contains storage')
    original,gold=Original(db),Gold(native);vectors=[];input_audit={};rows=providers['coordinates']
    startup={tuple(n):tuple(o) for o,n in initial['pairs']};require(len(startup)==4231,'Full startup relation absent')
    fields=joint['cases']['none']['inventory']['inventory']['gate']['fields'];internal=[]
    for name,width in inputs.items():
        bits,detail=original_bits(db,original,name,width,types)
        occurrences=[r for r in rows if r['consumer']=='write_select.'+name]
        require(len(occurrences)==width and sorted(r['position'] for r in occurrences)==list(range(width)),'Complete actual input occurrences differ')
        if name in STATE:
            require(width==STATE[name] and len(fields[name])==width,'Exact selected state width differs')
            require(all(startup.get(('joint',q))==('Q',b) for q,b in zip(fields[name],bits)),'Actual state coordinates differ from startup')
            for row in occurrences:
                require(row['classification']=='consumer_actual_domain_missing' and row['provider']['unit']=='sequence' and row['provider']['port']=='o_'+name and row['expression']=='control_'+name,'Actual internal input edge differs')
            detail['kind']='related_sequence_state';detail['native_joint_Q']=fields[name];internal+=occurrences
        else:
            require(all(r['classification']=='external_control_parent_input' and r['provider'] is None and r['expression']==name for r in occurrences),'Actual datapath boundary differs')
            detail['kind']='explicit_shared_datapath_input'
        detail['occurrences']=occurrences;input_audit[name]=detail;vectors.append(('input_'+name,bits,native['ports'][name]['bits']))
    require(len(internal)==91,'Complete91 internal domain differs')
    relation,ocuts,gcuts=classes(original,gold,vectors)
    require(not relation['gold_to_original_conflicts'] and not relation['gold_literal_conflicts'],'Boundary aliases conflict')
    manifest=[];output_audit={};writer_rows={(r['field'],r['position']):r for r in writer['boundary']['coordinates']};consumers=[]
    for name,width in outputs.items():
        bits=original.alias(name);require(len(bits)==width,'Complete actual output width differs');paths=[]
        output_audit[name]={'original_owner':owner(db,'netnames',name),'native_port':native['ports'][name]}
        for i,(a,b) in enumerate(zip(bits,native['ports'][name]['bits'])):
            uses=[r for r in rows if r['provider'] and r['provider']['unit']=='write_select' and r['provider']['port']==name and r['position']==i]
            require(len(uses)==1,'Complete cw consumer occurrence differs');row=uses[0]
            require(row['consumer']=='write_buffer.'+name and row['classification']=='provider_actual_observation_missing' and row['expression']=='control_'+name,'Actual cw edge differs')
            endpoint=writer_rows[('input_'+name,i)]['original_underlying']
            require(row['consumer_proof_endpoint']['original']==endpoint,'Saved actual writer endpoint differs')
            paths.append(chain(original,a,endpoint,original.producer));consumers.append(row)
            manifest.extend([{'kind':'D','field':name,'position':i,'original':a,'gold':b},
                {'kind':'D','field':'writer_normalized_'+name,'position':i,'original':endpoint,'gold':b}])
        output_audit[name]['actual_buffer_paths']=paths
    require(len(consumers)==424 and len(manifest)==848,'Complete output observation inventory differs')
    for row in relation['coordinates']:
        name=row['field'].removeprefix('input_');i=row['position'];manifest.append({'kind':'alias','original':input_audit[name]['coordinates'][i],'gold':native['ports'][name]['bits'][i],**row})
    return {'original_graph':original,'gold_graph':gold,'original_q':dict(db.execute('SELECT q,cell FROM qd WHERE module="otpu_vpu"')),'gold_q':{},
        'original_cuts':ocuts,'gold_cuts':gcuts,'relation':relation,'manifest':manifest,'input_audit':input_audit,'output_audit':output_audit,
        'internal91':internal,'writer424':consumers,'packed_source_rules':types}
