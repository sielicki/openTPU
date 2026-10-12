"""Exact initialized physical-dot production applicability; no whole-MXU claim."""
import argparse,ast,re,signal,sys
from pathlib import Path
from dot_applicability import *
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from check_sparkle_fpga_top_complete import bounded_context,global_directives
from check_sparkle_fp_state_consumers import selected_modules,digest_tokens
from check_sparkle_mxu_dsp_initial_consumers import production_occurrences,audit_record,audit_projection_identity
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive
import check_sparkle_mxu_dsp_initial as dsp_initial
CURRENT=ROOT/'build/sparkle/se-composite-assemblies-first/summary.json'
CURRENT_SHA='c4536dbec2cfe0522092ac5896a9f809342e7940fead7938b9431b67a7b6d3ef'
TAIL=ROOT/'build/sparkle/se-tail-assertion-assemblies-third/summary.json'
TAIL_SHA='15534eb8506e8010dc6ed0f1ca5c36cb625af69d35dfd23d47e0d79472177e5c'
LEAF=ROOT/'build/sparkle/mxu-dsp-initial-consumer-binding-second/summary.json'
LEAF_SHA='ed768684a2ec256afebc089acca34f7eab6efc526c2d57d973b4993a88ab0cf7'
INITIAL=ROOT/'build/sparkle/mxu-dsp-initial-second/summary.json'
INITIAL_SHA='4925be848d0864d4daf04b129ae199040ceea530f000c99fe469f46bc501de66'

class RecipePath:
    """Closed read-only two-file namespace; no implicit live RTL traversal."""
    def __init__(self,files,key=''):self.files=files;self.key=key
    def __truediv__(self,name):return RecipePath(self.files,(self.key+'/'+name).strip('/'))
    def read_text(self):require(self.key in self.files,'Unbound recipe read '+self.key);return self.files[self.key]
    def exists(self):return self.key in self.files
    def rglob(self,pattern):
        require(self.key=='rtl' and pattern=='*.sv','Unexpected recipe traversal')
        return [RecipePath(self.files,k) for k in sorted(self.files) if k.startswith('rtl/') and k.endswith('.sv')]

def reference_recipe(behavioral,physical,mxu,delay):
    root=RecipePath({'rtl/mxu/otpu_mxu.sv':mxu,'rtl/vpu/otpu_fpipe.sv':delay})
    def load(source,extra):
        tree=ast.parse(source);f=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='reference']
        require(len(f)==1 and not f[0].decorator_list,'Unique undecorated reference function required')
        scope={'ROOT':root,'re':re,**extra};exec(compile(ast.Module(body=f,type_ignores=[]),'<authenticated-reference-recipe>','exec'),scope)
        return scope['reference']
    first=load(behavioral,{})
    return load(physical,{'behavioral_reference':first})(128,4,16)

def chain(old,middle,new):
    require(old['name']==middle['name']==new['name'] and
      old['assembly_sha256']==middle['old_assembly_sha256'] and middle['new_assembly_sha256']==new['old_assembly_sha256'],
      'Exact current/tail/original assembly chain differs')

def main(output,certificate,certificate_sha):
    bounded_context();output=output.resolve();output.mkdir(exist_ok=False);ev=HistoricalEvidence();maps={}
    report={'status':'incomplete','production_parent_applicability':False,'whole_mxu_proven':False,
      'physical_timing_qualified':False,'current_runtime_qualified':False,'cases':[],'certificate':{'path':str(certificate),'sha256':certificate_sha}}
    def checkpoint():report['input_sha256']=dict(ev.observed);save(output/'summary.json',report);archive(output/'summary.json')
    def freeze(p,h=None):
        digest=ev.direct(Path(p),h);require(archive(Path(p))==digest,'Archive race');return digest
    def record(p,h,field='input_sha256'):
        r,_=ev.record(Path(p),h,field=field);maps[id(r)]=normalized_hashes(r[field]);return r
    def artifact(r,p):
        key=str(Path(p).resolve());hashes=maps[id(r)];require(key in hashes,'Missing direct artifact identity '+key)
        return Path(ev.authenticated[(key,hashes[key])])
    def joined(r,p):
        key=str(Path(p).resolve());require(key in maps[id(r)],'Missing direct receipt join '+key)
        return record(Path(key),maps[id(r)][key])
    def identity(source,name):
        parts=selected_modules(source,{name});_,contexts=global_directives(source)
        require(set(parts)=={name},'Missing exact module '+name);return parts[name],contexts[name]
    def suppress():
        for s in (signal.SIGTERM,signal.SIGINT):signal.signal(s,signal.SIG_IGN)
    def stop(s,_):suppress();raise RuntimeError('Interrupted '+str(s))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint()
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and (Path(p).resolve().parent==ROOT/'tools' or Path(p).resolve().parent==Path(__file__).resolve().parent):freeze(Path(p).resolve())
        cert=record(certificate,certificate_sha);certificate_contract(cert)
        for p,h in cert['premises'].items():require(maps[id(cert)].get(str(Path(p).resolve()))==h,'Certificate premise identity differs')
        require(cert['premises'].get(str(INITIAL))==INITIAL_SHA,'Certificate DSP initial theorem differs')
        initial=record(INITIAL,INITIAL_SHA);audit_record(initial)
        parentref=initial['historical_composition'];parent=record(Path(parentref['summary']),parentref['sha256'])
        require(maps[id(cert)].get(str(Path(parentref['summary']).resolve()))==parentref['sha256'],'Certificate parent identity differs')
        require(parent['status']==parent['solver_status']=='passed' and parent['mutation'] is None and parent['config']==[128,4,16], 'Wrong original parent proof')
        folder=Path(parentref['summary']).parent;native=artifact(parent,folder/'native.sv');reference=artifact(parent,folder/'reference.sv')
        first=initial['cases'][0];primitive_leaf=record(Path(first['historical_summary']),first['historical_sha256'])
        model=Path(primitive_leaf['dsp_model']);freeze(model,primitive_leaf['dsp_model_sha256'])
        require(model.resolve()==dsp_initial.physical.dsp_model().resolve(),'Current primitive model location differs')
        require(dsp_initial.functional_model(model.read_text())==artifact(parent,folder/'DSP48E1.sv').read_text(),
                'Current exact functional primitive differs from initialized parent')
        # This is a fresh independently checked exact reconstruction, not a claim
        # that current helper source was used by the historical invocation.
        recipes=[ROOT/'tools/prove_sparkle_mxu_dot.py',ROOT/'tools/prove_sparkle_mxu_physical_dot.py']
        for p in recipes:freeze(p)
        rtl=artifact(parent,ROOT/'rtl/mxu/otpu_mxu.sv');freeze(ROOT/'rtl/mxu/otpu_mxu.sv',maps[id(parent)][str(ROOT/'rtl/mxu/otpu_mxu.sv')])
        delay=ROOT/'rtl/vpu/otpu_fpipe.sv';freeze(delay)
        require(reference_recipe(recipes[0].read_text(),recipes[1].read_text(),rtl.read_text(),delay.read_text())==reference.read_text(),
                'Full original wrapper/current original RTL reconstruction differs')
        report['reference_bridge']='Full byte-identical independent recipe with exact128/4/2/16 original RTL and delay definition'
        leaf=record(LEAF,LEAF_SHA);require(leaf['status']=='production_dsp_leaf_initialized_refinements_bound' and leaf['initialized_leaf_theorem']['sha256']==INITIAL_SHA,'DSP production binding differs')
        current=record(CURRENT,CURRENT_SHA);tail=record(TAIL,TAIL_SHA)
        require(current['status']=='composite_diagnostic_current_assemblies_correspondence_validated' and current['after_tail_assemblies_sha256']==TAIL_SHA and maps[id(current)].get(str(TAIL))==TAIL_SHA,'Current assembly lineage differs')
        require(tail['status']=='se_tail_assertion_current_assemblies_correspondence_validated','Tail assembly bridge incomplete')
        for r in (leaf,current,tail):require([c['name'] for c in r['cases']]==['gen1','gen2','bundle'],'Exact three production cases required')
        module_names={DOT,*MODULE_BY_CASE.values()};proven={name:identity(native,name) for name in module_names}
        for old,middle,new in zip(leaf['cases'],tail['cases'],current['cases']):
            chain(old,middle,new);name=old['name'];binding=record(Path(old['specialization_receipt']),old['specialization_sha256'])
            require(binding['status']=='specialized_instances_bound_scope_incomplete' and binding['case']==name,'Specialization binding differs')
            original=artifact(leaf,old['assembly']);assembly=artifact(current,new['new_assembly']);freeze(assembly,new['new_assembly_sha256'])
            require(maps[id(leaf)][str(Path(old['assembly']).resolve())]==old['assembly_sha256'] and maps[id(binding)].get(str(Path(old['assembly']).resolve()))==old['assembly_sha256'],'Historical assembly direct join differs')
            hp=ROOT/'build/sparkle'/('specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first')/'summary.json'
            require(str(hp) in maps[id(binding)],'Missing exact hierarchy receipt')
            hierarchy=record(hp,maps[id(binding)][str(hp)],field='inputs')
            require(hierarchy['status']=='elaborated_hierarchy_inventory_complete','Hierarchy incomplete')
            actual={n:identity(assembly,n) for n in module_names}
            require(actual==proven,'Full production dot/helper definitions or directives differ from initialized parent source')
            mh={n:digest_tokens(actual[n][0]) for n in MODULE_BY_CASE.values()};projections={}
            for case in COUNTS:
                pp=ROOT/'build/sparkle/dsp-occurrence-projection-first'/case/'summary.json';projection=joined(binding,pp)
                require(projection['status']=='passed' and projection['case']==case and projection['module']==MODULE_BY_CASE[case],'Projection configuration differs')
                audit_projection_identity(projection['helper_identity'],mh[MODULE_BY_CASE[case]],actual[MODULE_BY_CASE[case]][1])
                projections[case]={'path':str(pp),'sha256':maps[id(binding)][str(pp)],'record':projection}
            coverage=production_occurrences(hierarchy,binding,mh,projections)
            require(coverage['helper_paths']==old['helper_paths'] and coverage['dsp_primitive_paths']==old['dsp_primitive_paths'],'Recomputed full DSP coverage differs from initialized binding')
            occurrence=reached_dot(hierarchy,binding,digest_tokens(actual[DOT][0]),proven[DOT][1],actual[DOT][1],coverage,parent['cuts'])
            paths={r['path']:r['specialization'] for r in hierarchy['paths']};dotpath=occurrence['path'];ancestors=[]
            for path,sid in paths.items():
                if dotpath==path or dotpath.startswith(path+'/'):
                    module=hierarchy['nodes'][sid]['module'];before=identity(original,module);after=identity(assembly,module)
                    require(before==after,'Containing current hierarchy module changed '+module)
                    require(binding['nodes'][sid]['module']==module and binding['nodes'][sid]['module_sha256']==digest_tokens(after[0]),'Containing reached specialization identity differs')
                    ancestors.append({'path':path,'specialization':sid,'module':module})
            require(len(ancestors)==len(dotpath.split('/')),'Incomplete containing path identity')
            edge=enclosing_dot_edge(identity(assembly,'otpu_mxu_sparkle')[0])
            report['cases'].append({'name':name,'assembly':new['new_assembly'],'assembly_sha256':new['new_assembly_sha256'],
              'occurrence':occurrence,'containing_path':ancestors,'parent_edge':edge});checkpoint()
        for p,h in current['runner']['source_sha256'].items():
            path=Path(p)
            if path.is_relative_to(ROOT/'OpenTPU') or path.is_relative_to(ROOT.parent/'sparkle'):freeze(path,h)
        report['current_generator_source_closure_verified']=True
        report['scope']='Initialized synchronous formal primitive-model physical dot only; one shared input trace and existential original initial witness. No whole-MXU, raw four-state simulation, device power-up, runtime or timing claim.'
        ev.finish();report.update(status='initialized_physical_dot_production_applicability_bound',production_parent_applicability=True);checkpoint()
    except BaseException as e:
        suppress();report.update(status='incomplete',production_parent_applicability=False,error=repr(e));checkpoint();raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--certificate',type=Path,required=True);p.add_argument('--certificate-sha',required=True)
    a=p.parse_args();main(a.output,a.certificate,a.certificate_sha)
