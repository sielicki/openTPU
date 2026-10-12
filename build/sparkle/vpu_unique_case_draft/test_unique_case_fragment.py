"""Unexecuted conditional compiler-lemma guards."""
import copy,json,tempfile,unittest
from pathlib import Path
from unique_case_fragment import ROOT,emit,source_fragments,harness
from check_unique_case_fragment import INPUTS,audit,buffer,mutation,query,counterexample
class Tests(unittest.TestCase):
    def sources(self):return (ROOT/'rtl/vpu/otpu_vpu.sv').read_text(),(ROOT/'rtl/top/otpu_pkg.sv').read_text()
    def test_only_unique_keywords_differ(self):
        rtl,pkg=self.sources();a=emit(rtl,pkg,False);b=emit(rtl,pkg,True)
        self.assertEqual(a.replace('module original ','module normalized ',1).replace('unique case','case'),b)
        self.assertEqual(a.count('unique case'),2);self.assertIn('output [159:0] observed',a)
    def test_original_negative_zero_dependency_is_preserved(self):
        rtl,pkg=self.sources();decl="  localparam f32_t F_NZ = 32'h8000_0000;"
        self.assertIn(decl,emit(rtl,pkg,False))
        for changed in (rtl.replace(decl,''),rtl+'\n'+decl+'\n'):
            with self.assertRaises(RuntimeError):source_fragments(changed,pkg)
    def test_source_anchors_labels_defaults_and_package_indices(self):
        rtl,pkg=self.sources();source_fragments(rtl,pkg)
        for old,new in [('V_COPY]:  st[0]','V_ADD]:  st[0]'),('localparam int NLL = C8 ? 0 : NCL;','localparam int NLL = NCL;'),
                        ('default: ;                                 // MAX',';                                 // MAX')]:
            with self.subTest(old=old),self.assertRaises(RuntimeError):source_fragments(rtl.replace(old,new),pkg)
        with self.assertRaises(RuntimeError):source_fragments(rtl,pkg.replace('V_COPY = 8','V_COPY = 7'))
    def test_actual_source_mutations_and_exact_premise(self):
        rtl,pkg=self.sources();source=emit(rtl,pkg,False)
        for fault in ('label','operand'):
            changed=mutation(source,fault);self.assertNotEqual(changed,source)
            self.assertEqual(changed.count('unique case'),2)
        self.assertIn('decoded[27:8]',harness())
        for kind in ('definedness','equality'):
            text=query(Path('/tmp/g.json'),kind,Path('/tmp/c.json'))
            self.assertIn('-enable_undef -set-def-inputs -set onehot0 1',text)
            self.assertNotIn('prove-x',text);self.assertNotIn('opt',text)
    def raw(self):
        ports={};cursor=2
        for n,w in INPUTS.items():ports[n]={'direction':'input','bits':list(range(cursor,cursor+w))};cursor+=w
        for n,bits in [('onehot0',['1']),('equal_ok',['1']),('impossible',['0']),('observed',[2]*320)]:ports[n]={'direction':'output','bits':bits}
        return {'modules':{'check':{'attributes':{},'ports':ports,'netnames':{},'cells':{}}}}
    def test_complete_combinational_audit_and_rejections(self):
        _,report=audit(self.raw());self.assertEqual(report['output_bits'],320)
        for fault in ('port','init','alias','driver','cycle','state'):
            with self.subTest(fault=fault):
                raw=self.raw();m=raw['modules']['check']
                if fault=='port':m['ports']['observed']['bits'].pop()
                if fault=='init':m['netnames']['bad']={'bits':[2],'attributes':{'init':'0'}}
                if fault=='alias':m['ports']['RMA']['bits']=[2]
                if fault in ('driver','cycle','state'):
                    m['cells']['bad']={'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'attributes':{},
                        'port_directions':{'A':'input','Y':'output'},'connections':{'A':[1000],'Y':[1000]}}
                    if fault=='driver':m['cells']['bad']['connections']['Y']=[2]
                    if fault=='state':m['cells']['bad']['type']='$dff'
                with self.assertRaises((RuntimeError,ValueError)):audit(raw)
    def test_buffer_identity_exact(self):
        c={'type':'$buf','parameters':{'WIDTH':'10'},'attributes':{},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[2,'x'],'Y':[3,4]}}
        out=buffer(c);self.assertEqual(out['connections'],{'A':[2,'x'],'B':['0','0'],'Y':[3,4]})
        c['parameters']['WIDTH']='1'
        with self.assertRaises(RuntimeError):buffer(c)
    def test_counterexample_requires_premise_and_real_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.json';data={'signal':[{'name':'onehot0','wave':'1'},{'name':'equal_ok','wave':'0'}]};p.write_text(json.dumps(data));counterexample(p)
            for index in (0,1):
                changed=copy.deepcopy(data);changed['signal'][index]['wave']='0' if index==0 else '1';p.write_text(json.dumps(changed))
                with self.assertRaises(RuntimeError):counterexample(p)
if __name__=='__main__':unittest.main()
