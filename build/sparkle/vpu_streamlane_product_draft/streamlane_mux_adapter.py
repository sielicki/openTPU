"""Exact paired-graph mux slicing, using explicitly authenticated shared rules."""
import ast
import copy
import json
from streamlane_step_cones import Index
from check_sparkle_fpga_top_complete import require


def load_rule(source,filename):
    # Caller authenticates and archives the complete reviewed source before here.
    tree=ast.parse(source,filename=filename);picked=[]
    for name in ['mux_slice','audit_mux_model']:
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
        require(len(nodes)==1 and not nodes[0].decorator_list,'Shared mux rule contract differs');picked.append(nodes[0])
    model=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and
           isinstance(n.targets[0],ast.Name) and n.targets[0].id=='MUX_MODEL']
    require(len(model)==1 and isinstance(model[0].value,ast.Constant) and type(model[0].value.value)is str,
            'Shared mux model anchor differs')
    # No module imports, classes or top-level execution. Exactly two pure reviewed
    # functions and literal model anchor; builtin access needed for their schema audit.
    namespace={'copy':copy,'need':require}
    exec(compile(ast.Module(body=model+picked,type_ignores=[]),filename,'exec'),namespace)
    return namespace['mux_slice'],namespace['audit_mux_model']


class SlicedIndex(Index):
    def __init__(self,store,side,manifest,rule):
        self.rule=rule;super().__init__(store,side,manifest)
    def cone(self,lo,hi):
        require(0<=lo<hi<=len(self.vector),'Invalid interval')
        cells={};roots={};seen=set();todo=list(self.vector[lo:hi])
        while todo:
            bit=todo.pop()
            if bit in seen:continue
            seen.add(bit);kind,name,idx=self.driver(bit)
            if kind=='input':roots[(name,idx)]=bit
            elif kind=='cell':
                cell=self.store.get(self.side,'cells',name)
                if cell['type']=='$mux':
                    self.rule(cell,[idx]) # exact WIDTH/pins before coordinate dependence
                    cells.setdefault(name,set()).add(idx);pins=cell['connections']
                    todo.extend([pins['A'][idx],pins['B'][idx],pins['S'][0]])
                elif name not in cells:
                    cells[name]=None;todo.extend(self.dependencies(name))
        return cells,roots
    def projected(self,name,indices):
        cell=self.store.get(self.side,'cells',name)
        return cell if indices is None else self.rule(cell,sorted(indices))
    def cost(self,cells):
        return sum(sum(len(bits) for bits in self.projected(n,i)['connections'].values()) for n,i in cells.items())


def project_pair(path,indexes,lo,hi,pin_budget=50000,cell_budget=10000):
    cones={s:indexes[s].cone(lo,hi) for s in ['gold','gate']}
    costs={s:indexes[s].cost(cones[s][0]) for s in cones}
    counts={s:len(cones[s][0]) for s in cones}
    if sum(costs.values())>pin_budget or sum(counts.values())>cell_budget:
        require(hi-lo>1,'Single-obligation cone exceeds fixed projected size budget')
        return {'split':[(lo,(lo+hi)//2),((lo+hi)//2,hi)],'pin_bits':costs,'cells':counts}
    keys=sorted(set(cones['gold'][1])|set(cones['gate'][1]));ids={k:i for i,k in enumerate(keys)}
    slices={}
    with path.open('w') as out:
        out.write('{"modules":{')
        for si,side in enumerate(['gold','gate']):
            if si:out.write(',')
            ix=indexes[side];cells,roots=cones[side];slices[side]=[]
            ports={'observed':{'direction':'output','bits':ix.vector[lo:hi]}}
            for key,b in roots.items():ports['root_'+str(ids[key])]={'direction':'input','bits':[b]}
            out.write(json.dumps(side)+':{"attributes":{},"ports":');json.dump(ports,out);out.write(',"netnames":{},"cells":{')
            for ci,name in enumerate(sorted(cells)):
                if ci:out.write(',')
                indices=cells[name];cell=ix.projected(name,indices)
                if indices is not None:slices[side].append({'cell':name,'indices_lsb':sorted(indices),
                    'original_width':len(ix.store.get(side,'cells',name)['connections']['Y']),
                    'projected_width':len(indices)})
                out.write(json.dumps(name)+':');json.dump(cell,out)
            out.write('}}')
        out.write('}}\n')
    return {'lo':lo,'hi':hi,'roots':[{'name':n,'index':i,'id':ids[(n,i)]} for n,i in keys],
            'used':{s:sorted(ids[k] for k in cones[s][1]) for s in cones},'cells':counts,'pin_bits':costs,
            'mux_slices':slices,'projection':'exact_mux_coordinates_other_cells_unchanged'}
