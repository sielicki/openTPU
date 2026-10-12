"""Unexecuted source-derived EXT1 inventory; graph counts remain provisional."""
from inventory import require

IDENTITY_CONTROL = (0x80000000 << 32) | (0x3f800000 << 64) | (1 << 97) | (2 << 101)


def delay_ref(prefix, index, cycles):
    return prefix + ('.g_regs.qr' if index == cycles-1 else f'.g_regs.r[{index}]')


def composite_fields():
    # Native path, original path, source declaration width, native initializer.
    fields=[]
    def add(native, original, width, initial=0):
        fields.append(('u_comp.'+native,'g_comp.u_comp.'+original,width,initial))
    for name in ['vpos','cpos']:add(name,name,25)
    add('ret_r','ret_r',1)
    for name in ['rr_e','rr_g','e1','e2','g1','g2']:add(name,name,1)
    add('uc_rt','uc_rt',105,IDENTITY_CONTROL)
    for s in range(3):
        add(f'uco{s}',f'uco[{s}]',105,IDENTITY_CONTROL)
        for i in range(6):add(f'cp{s}_{i}',delay_ref(f'g_uc[{s}].u_cp',i,6),7)
        for i in range(7):add(f'md{s}_{i}',delay_ref(f'g_sel[{s}].u_md',i,7),36)
    for i in range(3):add(f'mr_{i}',delay_ref('g_sel[0].g_rrm.u_mr',i,3),36)
    add('lp_m','lp_m',36)
    for lane in range(8):
        for stage in range(3):
            for i in range(7):
                add(f'kd{lane}_{stage}_{i}',delay_ref(f'g_lane[{lane}].g_st[{stage}].u_k',i,7),76)
        for q in range(3):add(f'q{q}_{lane}',f'g_lane[{lane}].g_st[0].g_rr.q{q}',108)
        add(f'lp_st{lane}',f'lp_st[{lane}]',108)
    require(len(fields)==256 and sum(w for _,_,w,_ in fields)==17727,'Source inventory incomplete')
    require(len({n for n,_,_,_ in fields})==len(fields),'Native alias overlap')
    require(len({n for _,n,_,_ in fields})==len(fields),'Reference alias overlap')
    return fields


def init_witness_constraints(modules, mapped):
    """Validate complete, independently Q/D-audited mapping against all aliases.

    mapped[side][native_name] must contain the complete same-width actual Q list.
    No alias is replaced. Reference X is existential, native X universal. This
    exact source specifies every native initializer, so missing definitions fail.
    Caller must validate mapped Q equals all actual Q before invoking this helper.
    """
    initial={}
    for side,module in modules.items():
        values={}
        q={b for c in module['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
        for name,net in module['netnames'].items():
            if 'init' not in net.get('attributes',{}):continue
            raw=net['attributes']['init'];bits=net['bits']
            require(isinstance(raw,str) and len(raw)==len(bits),'Initializer width/type: '+name)
            for b,v in zip(bits,reversed(raw)):
                require(v in '01xz','Unsupported initializer digit')
                if v in 'xz':continue
                require(type(b)is int and b in q,'Defined initializer outside Q: '+name)
                require(b not in values or values[b]==v,'Conflicting initializer aliases: '+name)
                values[b]=v
        initial[side]=values
    for native,_,width,value in composite_fields():
        bits={s:mapped[s][native] for s in ['gold','gate']}
        require(all(len(x)==width for x in bits.values()),'Mapped field width differs')
        for i,(g,n) in enumerate(zip(bits['gold'],bits['gate'])):
            v=str((value>>i)&1)
            require(initial['gate'].get(n)==v,'Actual native initializer differs: '+native)
            require(g not in initial['gold'] or initial['gold'][g]==v,'Reference witness conflict: '+native)
    return initial
