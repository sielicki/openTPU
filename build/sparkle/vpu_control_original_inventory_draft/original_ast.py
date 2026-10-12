"""Local exact typedef-array adapter; shared hierarchy parser stays unchanged."""
import re
from audit_sparkle_specialized_hierarchy import ast_integral_type,ast_parameter_bits,genvar_exports
from audit_sparkle_rtlil_roundtrip import Owners
from check_sparkle_fpga_top_complete import require
from child_ast import child_metadata

DIMENSION=re.compile(r'\$\[(-?\d+):(-?\d+)\]')

def resolve_array_type(text,aliases):
    seen=set();chain=[];pending=''
    while re.match(r'^\d+ ',text):
        address,qualified=text.split(' ',1)
        require(address in aliases,'Missing AST typedef symbol: '+text)
        require(address not in seen,'Cyclic AST typedef reference');seen.add(address)
        alias=aliases[address];base=qualified;suffix=''
        if '$[' in qualified:
            base,suffix=qualified.split('$[',1);suffix='$['+suffix
            require(DIMENSION.fullmatch(suffix) is not None,'Unsupported AST unpacked alias dimensions')
            require(not pending,'Nested unpacked typedef arrays require explicit order audit')
            pending=suffix
        if alias['qualified_name']!=base:
            scope=alias.get('direct_root_scope')
            require(type(scope)is dict and scope.get('kind')=='InstanceBody' and scope.get('name')=='otpu_vpu' and type(scope.get('addr'))is int and scope['addr']>0,'AST alias is not declared directly in the actual root module')
            require(alias.get('declaration_addr')==int(address) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',alias.get('declaration_name','')) is not None,'AST declaration identity differs')
            require(alias['qualified_name']=='otpu_vpu::'+alias['declaration_name'] and base=='otpu_vpu.'+alias['declaration_name'],'AST typedef symbol scope/name mismatch')
        chain.append({'symbol_id':address,**alias,'reference_qualified_name':qualified,'unpacked_suffix':suffix})
        text=alias['target']
    if pending:
        require('$[' not in text,'Nested unpacked typedef targets require explicit order audit')
        text+=pending
    return text,chain

def array_geometry(text):
    """One actual unpacked range; preserve its declared order independently.

    No array linearization/permutation theorem is inferred from total width.
    Multiple unpacked ranges fail closed until their AST nesting is audited.
    """
    require(type(text)is str and text.count('$')==1,'Unsupported unpacked array type')
    base,suffix=text.split('$',1);match=DIMENSION.fullmatch('$'+suffix)
    require(match is not None,'Malformed unpacked array range')
    element=ast_integral_type(base);left,right=map(int,match.groups());size=abs(left-right)+1
    require(size<=65536 and element['width']*size<=65536,'Unpacked array width exceeds inventory bound')
    return {'width':element['width']*size,'element_type':base,'element_shape':element,
            'unpacked_dimensions':[{'left':left,'right':right,'size':size,'ascending':left<right}],
            'array_order_bridge_proven':False}

def scoped_ast_metadata(log,top,resolver=resolve_array_type):
    """Stream AST embedded in frontend log, retaining only local typed symbols.

    Child AST bodies may exist despite RTLIL blackboxing: never load a complete
    AST JSON owner. Original expressions are consumed but not interpreted.
    """
    captures={};symbols={};counter=0;alias_nodes=[];scopes={};scope_nodes={};local_nodes=[];parameter_nodes=[];port_nodes=[]
    with log.open() as stream:
        while True:
            line=stream.readline();require(line!='','Missing frontend AST dump')
            if line.strip()=='{':break
        parser=Owners(stream,limit=1024*1024);parser.buf='{\n'
        def visit(path,depth=0):
            nonlocal counter
            require(depth<128,'AST nesting exceeds audited bound');counter+=1
            require(counter<=10000000,'AST node count exceeds audited bound')
            parser.whitespace();first=parser.buf[parser.pos]
            if first=='{':
                scalars={};seen=set()
                for key in parser.object():
                    require(key not in seen,'Duplicate AST field');seen.add(key)
                    value=visit(path+(key,),depth+1)
                    if value is not None:scalars[key]=value
                if scalars.get('kind') in ('Instance','InstanceArray','InstanceBody','GenerateBlockArray','GenerateBlock'):scope_nodes[path]=scalars
                if scalars.get('kind')=='Parameter':parameter_nodes.append((path,scalars))
                if scalars.get('kind')=='Port':port_nodes.append((path,scalars))
                if scalars.get('kind')=='Genvar' or (scalars.get('kind')=='Parameter' and scalars.get('isLocal')):local_nodes.append((path,scalars))
                if scalars.get('kind') in ('Package','InstanceBody','GenerateBlock') and scalars.get('name'):
                    scopes[path]={'name':scalars['name'],'kind':scalars['kind'],'addr':scalars.get('addr')}
                if scalars.get('kind')=='TypeAlias':alias_nodes.append((path,scalars))
                if path==() or (len(path)==2 and path[0]=='members') or (len(path)==3 and path[0]=='members' and path[2]=='body'):
                    captures[path]=scalars
                if len(path)==5 and path[0]=='members' and path[2:4]==('body','members') and scalars.get('kind') in ('Parameter','Port'):
                    symbols.setdefault(path[1],[]).append(scalars)
                return None
            if first=='[':
                parser.char('[');index=0
                while True:
                    parser.whitespace()
                    if parser.buf[parser.pos]==']':parser.pos+=1;break
                    if index:parser.char(',')
                    visit(path+(index,),depth+1);index+=1
                return None
            return parser.value()
        visit(())
    require(captures[()].get('kind')=='Root','Unexpected AST root')
    choices=[(p,v) for p,v in captures.items() if len(p)==2 and v.get('kind')=='Instance']
    require(len(choices)==1 and choices[0][1].get('name')==top,'Unexpected AST top instances')
    index=choices[0][0][1];body=captures.get(('members',index,'body'),{})
    require(body.get('name')==top and body.get('kind')=='InstanceBody','Unexpected AST top body')
    aliases={}
    for path,symbol in alias_nodes:
        address=str(symbol['addr']);require(address not in aliases,'Duplicate AST typedef symbol')
        parents=[scopes[path[:i]] for i in range(len(path)) if path[:i] in scopes]
        qualified='::'.join([s['name'] for s in parents]+[symbol['name']])
        root_path=('members',index,'body')
        direct_scope=scopes.get(root_path) if path[:-2]==root_path else None
        aliases[address]={'qualified_name':qualified,'target':symbol['target'],
                          'declaration_addr':symbol['addr'],'declaration_name':symbol['name'],
                          'declaration_path':list(path),'scope_chain':parents,
                          'direct_root_scope':direct_scope}
    parameters={};ports={}
    for symbol in symbols.get(index,[]):
        name=symbol['name']
        resolved_type,alias_chain=resolver(symbol['type'],aliases)
        original_type=symbol['type'];symbol=dict(symbol,type=resolved_type)
        if symbol['kind']=='Parameter':
            if symbol.get('isLocal') is True:continue
            require(symbol.get('isPort') is True and symbol.get('isBody') is False,'Unsupported AST parameter declaration')
            require(name not in parameters,'Repeated AST parameter')
            bits,shape=ast_parameter_bits(symbol)
            parameters[name]={'bits':bits,'value':symbol['value'],**shape,
                              'declared_type':original_type,'typedef_chain':alias_chain}
        else:
            require(name not in ports,'Repeated AST port')
            integral=(symbol['type'] in ('int','int signed','int unsigned') or
                      re.fullmatch(r'(bit|logic)( signed| unsigned)?(?:\[-?\d+:-?\d+\])?',symbol['type']) is not None)
            shape=ast_integral_type(symbol['type']) if integral else {'type':symbol['type']}
            shape['geometry_source']='AST integral type checked against RTLIL' if integral else 'Independently specialized RTLIL port; typed ABI layout proof remains separate'
            require(symbol['direction'] in ('In','Out','InOut'),'Unsupported AST port direction')
            ports[name]={**shape,'declared_type':original_type,'typedef_chain':alias_chain,'direction':{'In':'input','Out':'output','InOut':'inout'}[symbol['direction']]}
    root_path=('members',index,'body')
    return {'parameters':parameters,'ports':ports,
            'generated_local_exports':genvar_exports(root_path,scope_nodes,local_nodes),
            'direct_children':child_metadata(root_path,scope_nodes,local_nodes,parameter_nodes,resolver,aliases,port_nodes)}



def original_root_metadata(log,top,resolver=resolve_array_type):
    metadata=scoped_ast_metadata(log,top,resolver)
    for port in metadata['ports'].values():
        if '$[' in port['type']:
            port.update(array_geometry(port['type']))
            port['geometry_source']='Exact typed unpacked range and total RTLIL width; array order correspondence unproved'
    return metadata
