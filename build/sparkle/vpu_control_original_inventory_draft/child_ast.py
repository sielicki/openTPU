"""Exact direct-root occurrence names and every typed blackbox parameter export."""
import json,re
from check_sparkle_fpga_top_complete import require
from audit_sparkle_specialized_hierarchy import ast_parameter_bits,ast_integral_type,genvar_exports

def child_ports(body_path,nodes,resolver,aliases):
    ports={}
    for path,symbol in nodes:
        if path[:-2]!=body_path:continue
        name=symbol['name'];require(name not in ports,'Duplicate child AST port')
        require(symbol['direction'] in ('In','Out'),'Unsupported child AST port direction')
        original=symbol['type'];suffix=''
        # Preserve unsupported unpacked layouts, while still resolving exact
        # scalar typedef identity. Do not infer array order or packed structs.
        base=original
        if re.match(r'^\d+ ',original) and '$[' in original:
            base,suffix=original.split('$[',1);suffix='$['+suffix
        resolved,chain=resolver(base,aliases);resolved+=suffix
        p={'declared_type':original,'resolved_type':resolved,'typedef_chain':chain,
           'direction':{'In':'input','Out':'output'}[symbol['direction']],
           'symbol_id':symbol['addr'],'ast_path':list(path),'array_order_bridge_proven':False}
        if resolved in ('int','int signed','int unsigned') or re.fullmatch(r'(bit|logic)( signed| unsigned)?(?:\[-?\d+:-?\d+\])?',resolved):
            p['integral_geometry']=ast_integral_type(resolved);p['typed_layout_status']='integral_width_available'
        else:
            p['integral_geometry']=None;p['typed_layout_status']='inventory_only_nonintegral_layout_unresolved'
        ports[name]=p
    return ports

def bind_child_ports(child,declaration,metadata):
    actual=child['connections'];directions=child['port_directions'];typed=metadata['ports']
    require(set(actual)==set(directions)==set(declaration)==set(typed),'Complete child AST/JSON/declaration port inventory differs')
    unresolved={};different={}
    for name,bits in actual.items():
        ast=typed[name];generic=declaration[name]
        require(directions[name]==ast['direction']==generic['direction'],'Actual child AST/JSON/declaration direction differs')
        shape=ast['integral_geometry']
        if shape is not None:require(len(bits)==shape['width'],'Actual child AST/JSON specialized integral width differs')
        else:unresolved[name]={'actual_width':len(bits),'declared_type':ast['declared_type'],'resolved_type':ast['resolved_type'],'usable_as_proof_premise':False,'typed_layout_equivalence_proven':False}
        if len(bits)!=generic['width']:different[name]={'actual_width':len(bits),'generic_declaration_width':generic['width'],'typed_integral_width':shape['width'] if shape else None}
    child['generic_declaration_ports']=declaration
    child['specialized_ast_ports']=typed;child['generic_specialized_shape_differences']=different
    child['unresolved_specialized_port_layouts']=unresolved;child['complete_specialized_port_widths_verified']=not unresolved
    child['specialized_port_layout_equivalence_proven']=False

EXPORT_VISITOR='''sym.body.visit(ast::makeVisitor([&](auto&, const ast::ParameterSymbol &symbol) {
    auto converted = netlist.convert_const(symbol.getValue(), symbol.location);
    if (converted) {
        if (symbol.isImplicitString(slang::SourceRange(sym.location, sym.location))
                && converted->size() % 8 == 0) {
            converted->raw_rtlil().flags |= RTLIL::CONST_FLAG_STRING;
        }
        cell->setParam(RTLIL::escape_id(std::string(symbol.name)), converted->to_rtlil());
    }
}, [&](auto&, const ast::TypeParameterSymbol &symbol) {
    netlist.add_diag(diag::BboxTypeParameter, symbol.location);
}, [&](auto&, const ast::InstanceSymbol&) {
    // no-op
}));'''
SCOPE_VISITOR='''if constexpr (std::is_base_of_v<Scope, T>) {
    for (auto& member : t.members())
        member.visit(DERIVED);
}'''
SERIALIZER_SKIP='''else if constexpr (std::is_same_v<GenerateBlockSymbol, T>) {
    if (elem.isUninstantiated)
        return;
}'''

def serializer_policy(source):
    require(''.join(source.split()).count(''.join(SERIALIZER_SKIP.split()))==1,'Actual inactive-generate AST serialization policy differs')
    return {'uninstantiated_generate_blocks_serialized':False,'complete_export_witness_guaranteed':False}
LOOP_CONSTRUCTION=(
'''auto genvarSymbol = comp.emplace<GenvarSymbol>(genvar.valueText(), genvar.location());
genvarSymbol->setSyntax(*genvarSyntax);
result->addMember(*genvarSymbol);
genvarSym = genvarSymbol;''',
'''auto implicitParam = comp.emplace<ParameterSymbol>(genvar.valueText(), genvar.location(),
true /* isLocal */, false /* isPort */);''',
'''implicitParam->setType(comp.getIntegerType());
implicitParam->setValue(comp, std::move(value), /* needsCoercion */ false);
implicitParam->setIsFromGenvar(true);
block->arrayIndex = &implicitParam->getValue().integer();''',
'''auto& local = *comp.emplace<VariableSymbol>(genvar.valueText(), genvar.location(),
VariableLifetime::Automatic);
local.setType(comp.getIntegerType());
local.flags |= VariableFlags::CompilerGenerated;''',
'''iterScope.addMember(local);''',
'''result->loopVariable = &local;''',
'''serializer.writeLink("loopVariable", *loopVariable);''')

def loop_policy(source):
    compact=lambda text:''.join(text.split());text=compact(source);positions=[]
    for fragment in LOOP_CONSTRUCTION:
        fragment=compact(fragment);require(text.count(fragment)==1,'Actual loop symbol construction policy differs');positions.append(text.index(fragment))
    require(positions==sorted(positions),'Loop construction/serialization order differs')
    return {'array_index_source':'actual implicit integer ParameterSymbol value',
            'loopVariable_source':'separately fabricated compiler-generated VariableSymbol',
            'loop_reference_address_bridge_proven':False,'generic_compiler_correctness_proven':False}

def export_policy(frontend,visitor):
    start='sym.body.visit(ast::makeVisitor([&](auto&, const ast::ParameterSymbol &symbol) {'
    require(frontend.count(start)==1,'Blackbox parameter visitor absent/ambiguous')
    actual=frontend[frontend.index(start):frontend.index('transfer_attrs(netlist, sym, cell);',frontend.index(start))]
    compact=lambda text:''.join(text.split())
    require(compact(actual)==compact(EXPORT_VISITOR),'Blackbox parameter export policy differs')
    require(compact(visitor).count(compact(SCOPE_VISITOR))==1,'AST source-member visitation policy differs')
    return {'scope_order':'source members; nested InstanceSymbol visitor is no-op',
            'parameter_rule':'retain every typed export; exact final-by-name map checked against actual JSON',
            'generic_compiler_correctness_proven':False}

def body_owner(path,scopes):
    owners=[path[:i] for i in range(len(path)) if scopes.get(path[:i],{}).get('kind')=='InstanceBody']
    return owners[-1] if owners else None

def actual_loop_parameters(body_path,scopes,locals_):
    """Select only the implicit variable, retaining other locals elsewhere.

    Ordinary scoped localparams such as AU are not generated loop variables.
    Their full typed values remain in the ordered export inventory below.
    """
    selected=set()
    for path,block in scopes.items():
        if block.get('kind')!='GenerateBlock' or block.get('branchKind')!='LoopIteration' or body_owner(path,scopes)!=body_path:continue
        array_path=path[:-2];array=scopes.get(array_path,{})
        require(array.get('kind')=='GenerateBlockArray' and block.get('isUninstantiated') is False,'Unsupported generated parameter scope')
        loop=re.fullmatch(r'(\d+) ([A-Za-z_][A-Za-z0-9_]*)',array.get('loopVariable',''))
        require(loop is not None and int(loop[1])>0,'Actual loop-variable reference absent')
        declarations=[s for p,s in locals_ if p[:-2]==array_path and s.get('kind')=='Genvar' and s.get('name')==loop[2]]
        candidates=[(p,s) for p,s in locals_ if p[:-2]==path and s.get('kind')=='Parameter' and s.get('name')==loop[2]]
        require(len(declarations)==len(candidates)==1,'Implicit loop variable lacks unique lexical declaration/iteration')
        p,s=candidates[0]
        require(s.get('type')=='integer' and s.get('isLocal') is True and s.get('isPort') is False and s.get('isBody') is True,'Implicit loop variable type/flags differ')
        ids=(declarations[0].get('addr'),s.get('addr'),int(loop[1]))
        require(all(type(i)is int and i>0 for i in ids) and len(set(ids))==3,'Generated loop symbol roles are not distinct')
        selected.add(p)
    return selected

def occurrence_name(body_path,root_path,scopes,locals_):
    require(body_owner(body_path,scopes)==root_path,'Not a direct-root child')
    instance_path=body_path[:-1];instance=scopes.get(instance_path,{})
    require(body_path[-1]=='body' and instance.get('kind')=='Instance','Child body lacks actual instance owner')
    pieces=[];evidence=[]
    for i in range(len(root_path)+1,len(body_path)):
        path=body_path[:i];scope=scopes.get(path)
        if scope is None:continue
        kind=scope['kind']
        if kind=='GenerateBlockArray':
            require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',scope.get('name','')) is not None,'Unsupported generated array name')
            continue
        if kind=='GenerateBlock':
            require(scope.get('isUninstantiated') is False,'Uninstantiated child scope')
            if scope.get('branchKind')=='LoopIteration':
                array_path=path[:-2];array=scopes.get(array_path,{})
                require(array.get('kind')=='GenerateBlockArray','Loop child lacks actual array owner')
                loop=re.fullmatch(r'(\d+) ([A-Za-z_][A-Za-z0-9_]*)',array.get('loopVariable',''))
                require(loop is not None,'Loop-variable identity absent')
                require(int(loop[1])>0,'Invalid synthetic loop-variable reference address')
                declarations=[s for p,s in locals_ if p[:-2]==array_path and s.get('kind')=='Genvar' and s.get('name')==loop[2]]
                iterations=[s for p,s in locals_ if p[:-2]==path and s.get('kind')=='Parameter' and s.get('name')==loop[2]]
                require(len(declarations)==len(iterations)==1,'Loop-variable declaration/iteration ambiguity: '+json.dumps({
                    'array_path':list(array_path),'array':array,'iteration_path':list(path),'iteration':scope,
                    'matching_declarations':declarations,'matching_iterations':iterations,
                    'actual_genvars_at_array':[s for p,s in locals_ if p[:-2]==array_path and s.get('kind')=='Genvar'],
                    'actual_iteration_locals':[s for p,s in locals_ if p[:-2]==path]},sort_keys=True))
                symbol=iterations[0];require(symbol.get('type')=='integer' and symbol.get('isLocal') is True and symbol.get('isPort') is False and symbol.get('isBody') is True,'Loop parameter schema differs')
                require(type(declarations[0].get('addr'))is int and declarations[0]['addr']>0 and str(declarations[0]['addr'])!=loop[1],'Lexical Genvar and fabricated iteration variable are not distinct symbols')
                require(type(symbol.get('addr'))is int and symbol['addr']>0 and symbol['addr'] not in (declarations[0]['addr'],int(loop[1])),'Implicit iteration parameter symbol identity differs')
                bits,_=ast_parameter_bits(dict(symbol,type='int'));index=int(bits,2);index-=1<<32 if index&(1<<31) else 0
                pieces.append(array['name']+'['+str(index)+']')
                evidence.append({'array_path':list(array_path),'array':array,'lexical_genvar':declarations[0],
                                 'synthetic_loop_reference':{'symbol_id':loop[1],'name':loop[2],'address_bridge_proven':False},
                                 'iteration':scope,'symbol':symbol,'bits':bits})
            else:
                require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',scope.get('name','')) is not None,'Unnamed/unsupported generated child scope')
                pieces.append(scope['name'])
        elif kind=='Instance':
            require(path==instance_path and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',scope.get('name','')) is not None,'Unsupported nested/array instance')
            pieces.append(scope['name'])
        else:raise RuntimeError('Unsupported child scope '+kind)
    require(pieces and pieces[-1]==instance['name'],'Missing actual child instance name')
    return '.'.join(pieces),evidence

def child_metadata(root_path,scopes,locals_,parameters,resolver,aliases,port_nodes=()):
    result={}
    for path,body in scopes.items():
        if body.get('kind')!='InstanceBody' or body_owner(path,scopes)!=root_path:continue
        name,occurrence=occurrence_name(path,root_path,scopes,locals_)
        require(name not in result,'Duplicate reconstructed child occurrence')
        implicit=actual_loop_parameters(path,scopes,locals_)
        loop_nodes=[(p,s) for p,s in locals_ if s.get('kind')=='Genvar' or p in implicit]
        try:groups=genvar_exports(path,scopes,loop_nodes)
        except RuntimeError as error:
            failures=[]
            for symbol_path,symbol in locals_:
                if symbol.get('kind')!='Parameter' or not symbol.get('isLocal') or body_owner(symbol_path,scopes)!=path:continue
                parent=symbol_path[:-2];block=scopes.get(parent,{})
                if block.get('kind')!='GenerateBlock' or block.get('branchKind')!='LoopIteration':continue
                array_path=parent[:-2];array=scopes.get(array_path,{})
                if array.get('kind')!='GenerateBlockArray':continue
                matching=[{'path':list(p),**s} for p,s in locals_ if p[:-2]==array_path and s.get('kind')=='Genvar' and s.get('name')==symbol['name']]
                if len(matching)!=1:
                    failures.append({'array_path':list(array_path),'array':array,'block_path':list(parent),'block':block,
                                     'implicit_parameter':symbol,'matching_genvars':matching})
            actual=[{'path':list(p),**s} for p,s in locals_ if s.get('kind')=='Genvar' and body_owner(p,scopes)==path]
            raise RuntimeError('Child generated export diagnostic: '+json.dumps({'original_error':str(error),'child':name,'body_path':list(path),'body':body,'failing_groups':failures,'all_lexical_genvars_in_child':actual},sort_keys=True)) from error
        exports=[];declared={};local={};final={};scoped={};classes={}
        for symbol_path,symbol in parameters:
            if body_owner(symbol_path,scopes)!=path:continue
            s=dict(symbol);resolved,chain=resolver(s['type'],aliases);s['type']=resolved
            parent=symbol_path[:-2];kind='declared'
            if s.get('isLocal') is True:
                require(s.get('isPort') is False and s.get('isBody') is True,'Unsupported local parameter flags')
                if parent==path:kind='local_constant'
                else:
                    block=scopes.get(parent,{})
                    require(block.get('kind')=='GenerateBlock' and block.get('branchKind')=='LoopIteration' and block.get('isUninstantiated') is False,'Unsupported nested local parameter export')
                    if symbol_path in implicit:
                        require(s['type']=='integer','Implicit loop type differs');s['type']='int';kind='generated_loop_local'
                    else:kind='scoped_local_constant'
            else:
                require(parent==path and s.get('isLocal') is False and s.get('isPort') is True and s.get('isBody') is False,'Unsupported declared parameter owner/flags')
            bits,shape=ast_parameter_bits(s)
            row={'name':s['name'],'symbol_id':s['addr'],'path':list(symbol_path),'classification':kind,'bits':bits,'shape':shape,'declared_type':symbol['type'],'typedef_chain':chain,'value':s['value']}
            if kind=='declared':require(s['name'] not in declared,'Duplicate declared child parameter');declared[s['name']]=row
            if kind=='local_constant':require(s['name'] not in local,'Duplicate direct local constant');local[s['name']]=row
            if kind=='scoped_local_constant':
                key=(parent,s['name']);require(key not in scoped,'Duplicate scoped local constant');scoped[key]=row
            classes.setdefault(s['name'],set()).add(kind)
            require(len(classes[s['name']])==1,'Parameter export changes declaration classification')
            exports.append(row);final[s['name']]=row
        require(not(set(declared)&set(local)),'Declared/local parameter name collision')
        for n,row in final.items():
            if n in declared:require(row==declared[n],'Declared child parameter overwritten')
            if n in local:require(row==local[n],'Direct child local constant overwritten')
            if row['classification']=='generated_loop_local':
                matching=[g for g in groups.get(n,[]) if g['iterations'][-1]['parameter_symbol_id']==row['symbol_id']]
                require(len(matching)==1 and matching[0]['bits']==row['bits'],'Final generated export lacks exact terminal iteration evidence')
                row['selected_generated_group']=matching[0]
        result[name]={'body':body,'body_path':list(path),'instance_scope':scopes[path[:-1]],'occurrence_evidence':occurrence,
                      'ports':child_ports(path,port_nodes,resolver,aliases),
                      'declared_parameters':declared,'local_constants':local,'generated_local_exports':groups,
                      'scoped_local_constants':list(scoped.values()),'ordered_parameter_exports':exports,'final_parameter_exports':final}
    return result

def bind_child_parameters(child,definition,metadata,declared):
    require(metadata['body']['name']==child['original_definition'],'Child AST/JSON original definition differs')
    actual_decl=metadata['declared_parameters'];require(set(actual_decl)==set(declared),'Complete typed declared child parameters differ')
    for n,kind in declared.items():
        shape=actual_decl[n]['shape']
        require(kind in ('int','bit') and shape['type']==kind and shape['width']==(32 if kind=='int' else 1) and shape['signed']==(kind=='int'),'Child parameter declaration/evaluated type differs')
    defaults=definition.get('parameter_default_values',{});raw=child['parameters']
    for n in defaults.keys()&raw.keys():require(defaults[n]==raw[n],'Child default/actual parameter disagreement')
    effective={**defaults,**raw};expected={n:v['bits'] for n,v in metadata['final_parameter_exports'].items()}
    require(set(declared)<=set(effective),'Missing declared child parameter')
    for n in declared:require(effective[n]==actual_decl[n]['bits'],'Actual declared child parameter value differs from typed AST')
    for n,value in effective.items():require(type(value)is str and value and set(value)<=set('01'),'Unknown/nonintegral raw child parameter')
    child['declared_parameter_values_verified']=True
    child['complete_export_semantics_verified']=effective==expected
    child['unresolved_non_declared_exports']={}
    if effective!=expected:
        changed={n:{'actual_bits':effective[n],'actual_width':len(effective[n]),'expected_bits':expected[n],'expected_width':len(expected[n]),
                    'final_export':metadata['final_parameter_exports'][n],
                    'all_same_name_export_owners':[{'path':v['path'],'symbol_id':v['symbol_id'],'classification':v['classification'],'bits':v['bits']} for v in metadata['ordered_parameter_exports'] if v['name']==n]}
                 for n in sorted(effective.keys()&expected.keys()) if effective[n]!=expected[n]}
        difference={
            'child':child.get('cell',metadata['instance_scope'].get('name')),'definition':child['original_definition'],
            'missing_names':sorted(expected.keys()-effective.keys()),'extra_names':sorted(effective.keys()-expected.keys()),
            'changed_values':changed}
        # This is a complete inventory, not an export-semantics theorem. The
        # source policies suggest inactive VTree branches account for exports
        # omitted from this AST; that value correspondence is not proved.
        # Retain the exact known discrepancy explicitly and prohibit a
        # complete semantic claim. No other mismatch receives this exception.
        known=(child.get('cell')=='u_vt' and child['original_definition']=='otpu_vtree'
               and declared=={'LANES':'int','LA':'int'}
               and effective['LANES']==format(8,'032b') and effective['LA']==format(4,'032b')
               and difference['missing_names']==[] and difference['extra_names']==['q'] and set(changed)=={'j','k'}
               and all(n not in declared and len(effective[n])==32 for n in ('j','k','q'))
               and all(metadata['final_parameter_exports'][n]['classification']=='generated_loop_local' for n in ('j','k')))
        require(known,'Complete child evaluated/exported parameter map differs: '+json.dumps(difference,sort_keys=True))
        child['unresolved_non_declared_exports']={n:{'actual_bits':effective[n],'ast_final_bits':expected.get(n),
                'reason':'Exact nondeclared export witness unavailable in archived AST',
                'diagnostic_inference':'Serializer omits inactive generate blocks; exporter traversal may explain these extra or overwritten values',
                'semantic_equivalence_proven':False,'usable_as_proof_premise':False} for n in ('j','k','q')}
        child['non_declared_export_difference']=difference
    child['effective_parameters']=effective;child['typed_parameter_evidence']=metadata
