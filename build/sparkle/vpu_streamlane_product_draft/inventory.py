"""Unexecuted source-derived inventory for production streaming VPU lane bank.

These counts are proof obligations, not a completed initialized product theorem.
The external SeComposite cut is explicit; it is not a Moore-output leaf.
"""
PRODUCTION=(8,2,True)
HISTORICAL=(8,8,True)
FP_PORTS={'clk':('input',1),'en':('input',1),'a':('input',32),'b':('input',32),'y':('output',32)}
OUTPUTS={'mo':33,'lres':256,'lmm':8,'lmv':256,'pacc':256,'o_c_hold':1,'o_c_sel':3,
         **{'o_c_s'+n:768 for n in ['a','b','c','e']}}
COMPOSITE_PORTS={'clk':('input',1),'rst':('input',1),'en':('input',1),'in_v':('input',1),
    'in_c':('input',3),'in_a':('input',256),'in_b':('input',256),'in_m':('input',8),
    'in_meta':('input',21),'st_y':('input',768),'hold':('output',1),'st_sel':('output',3),
    **{'st_'+n:('output',768) for n in ['a','b','c','e']},
    'out_v':('output',1),'out_d':('output',256),'out_m':('output',8),'out_meta':('output',21)}


def require(ok,message):
    if not ok:raise ValueError(message)


def local_fields(config=PRODUCTION):
    require(tuple(config)==PRODUCTION,'Only exact production8/2/true is admitted')
    fields=[]
    for i in range(7):
        suffix='g_regs.qr' if i==6 else f'g_regs.r[{i}]'
        fields.append((f'meta_slot0_{i}',33,'g_mdel[0].g_d0.u_d.'+suffix,0))
    for lane in range(8):
        for field in ['ra','rb','rc','re']:
            fields.append((f'lane{lane}_slot0_{field}',32,f'g_slane[{lane}].{field}',
                           0x80000000 if field=='rc' else 0))
    require(sum(w for _,w,_,_ in fields)==1255 and len(fields)==39,'Incomplete source-derived local inventory')
    return fields


def fp_instances():
    return [(f'lane{lane}_slot0_{suffix}',f'g_slane[{lane}].u_ma.{unit}',kind,latency)
            for lane in range(8) for suffix,unit,kind,latency in
            [('ab','u_m','mul',2),('ce','u_c','mul',2),('sum','u_a','add',4)]]


def local_initial_witness():
    return {name:format(initial,'0'+str(width)+'b') for name,width,_,initial in local_fields()}


def candidate_counts():
    fp=sum(125 if kind=='mul' else 191 for _,_,kind,_ in fp_instances())
    return {'local':1255,'mul_instances':16,'add_instances':8,'fp':fp,
            'conditional_lane_fp_product':1255+fp,'external_composite_pending':17727,
            'joint_nonfp_parent_candidate':1255+17727,'closed_lane_subtree_candidate':1255+17727+fp,
            'external_output_bits':sum(OUTPUTS.values()),
            'parent_checked_bits_with_composite_cut':1255+sum(OUTPUTS.values())+24*65+
                sum(w for n,(d,w) in COMPOSITE_PORTS.items() if d=='input' and n!='clk')}


def audit_local_q_mapping(modules):
    """Audit complete actual local Q/D; caller must first audit all25 cuts.

    No alias creation, netname deletion, pruning, or initializer transformation.
    Returns all source aliases for an independent all-alias initialization audit.
    """
    require(set(modules)=={'gold','gate'},'Exact paired parent modules required')
    result={}
    for side,module in modules.items():
        qd={};owners={}
        for name,cell in module['cells'].items():
            if cell['type']!='$dff':continue
            c=cell['connections'];p=cell['parameters']
            require(cell['port_directions']=={'CLK':'input','D':'input','Q':'output'} and
                    c['CLK']==module['ports']['clk']['bits'] and int(p['CLK_POLARITY'],2)==1,
                    'Actual local DFF contract differs')
            require(len(c['Q'])==len(c['D'])==int(p['WIDTH'],2),'Actual D/Q width differs')
            for q,d in zip(c['Q'],c['D']):
                require(type(q)is int and q not in qd,'Duplicate/constant state Q')
                qd[q]=d;owners[q]=name
        mapped={};covered=set()
        for native,width,reference,_ in local_fields():
            key=native if side=='gate' else reference;bits=module['netnames'][key]['bits']
            require(len(bits)==width and len(set(bits))==width and set(bits)<=qd.keys() and
                    not set(bits)&covered,'Incomplete/overlapping actual local field')
            mapped[native]={'Q':list(bits),'D':[qd[q] for q in bits]};covered.update(bits)
        require(covered==qd.keys() and len(covered)==1255,'Unmapped actual retained local state')
        result[side]=mapped
    return result
