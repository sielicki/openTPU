"""Unexecuted staged-driver guards; test under bounded gate only."""
import json
from pathlib import Path
import tempfile
import unittest
from check_streamlane_stage import generator,reference_anchors,stream_inventory,resume,PENDING,workspace_root,archived_reference,ROOT,yosys_path

class StageTests(unittest.TestCase):
    def test_frontend_paths_are_bare_and_reject_script_metacharacters(self):
        self.assertEqual(yosys_path(Path('/work/source-1.sv')),'/work/source-1.sv')
        for path in ['relative.sv','/work/a b.sv','/work/a;quit','/work/a\nquit','/work/"a"','/work/a\\b']:
            with self.assertRaises(RuntimeError):yosys_path(path)
    def test_loader_does_not_execute_module(self):
        source="raise RuntimeError('top-level must not run')\ndef reference(lanes,cl,se=False):\n    return str(lanes)+str(cl)+str(int(se))\n"
        self.assertEqual(archived_reference(source)(8,2,True),'821')
    def test_loader_rejects_contract_and_dependencies(self):
        good='def reference(lanes,cl,se=False):\n    return str(lanes)\n'
        for source in [good+good,good.replace('se=False','se=True'),good.replace('return str(lanes)','return modern_helper(lanes)'),
                       '@decorator\n'+good,good.replace('def reference','async def reference'),
                       good.replace('return str(lanes)','import os\n    return str(lanes)')]:
            with self.assertRaises(RuntimeError):archived_reference(source)
    def test_real_archived_reference_reconstructs_old_wrapper(self):
        recipe=ROOT/'build/sparkle/proof_inputs/0882622f30287ef52a88486020fc22604bd7acc33c925d9478690a4fc7713f6a'
        fn=archived_reference(recipe.read_text(),str(recipe))
        wrapper=ROOT/'build/sparkle/formal_vpu_datapath_lanes/8_8_1/proof/reference.sv'
        self.assertEqual(fn(8,8,True),wrapper.read_text())
        current=fn(8,2,True)
        self.assertEqual(current.replace('LANES=8,CL=2,','LANES=8,CL=8,',1),wrapper.read_text())
    def test_workspace_discovery_draft_and_installed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'tools').mkdir();(root/'OpenTPU').mkdir()
            (root/'tools/sparkle_bounded.py').touch();(root/'OpenTPU/VpuLanes.lean').touch()
            self.assertEqual(workspace_root(root/'tools/checker.py'),root)
            self.assertEqual(workspace_root(root/'build/sparkle/draft/checker.py'),root)
            (root/'OpenTPU/VpuLanes.lean').unlink()
            with self.assertRaises(RuntimeError):workspace_root(root/'tools/checker.py')
    def test_no_argument_generator(self):
        text=generator('/tmp/native.sv','/tmp/datapath.sv')
        self.assertIn('def main : IO Unit := do',text)
        self.assertNotIn('args :',text)
        self.assertIn('⟨8,2,true⟩',text)
        self.assertIn('⟨8,21,3,2,true⟩',text)
        self.assertIn('IO.FS.writeFile "/tmp/native.sv" native',text)
    def test_unsafe_generator_path_rejected(self):
        for p in ['bad"name','bad\nname','bad\\name']:
            with self.assertRaises(RuntimeError):generator(p,'good')
    def test_actual_reference_shapes(self):
        rtl=Path('rtl/vpu/otpu_vpu.sv').read_text()
        self.assertEqual(len(reference_anchors(rtl)),2)
        for original,replacement in [('begin : g_slane','begin : changed_slane'),
            ('m0d.fh[V_COPY]:','m0d.fh[V_FILL]:'),('unique case (1\'b1)','case (1\'b1)')]:
            # Remove all matching qualifiers to ensure both active cases change.
            with self.assertRaises(RuntimeError):reference_anchors(rtl.replace(original,replacement))
    def test_streamed_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'graph.json'
            path.write_text(json.dumps({'creator':'fixture','modules':{'gold':{'ports':{},'cells':{},'netnames':{}},'gate':{'ports':{},'cells':{},'netnames':{}}}}))
            self.assertEqual(set(stream_inventory(path)),{'gold','gate'})
            path.write_text('{"creator":"fixture","modules":{"gold":{},"gold":{},"gate":{}}}')
            with self.assertRaises(RuntimeError):stream_inventory(path)
    def test_missing_parent_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'graph.json';path.write_text('{"creator":"fixture","modules":{"gold":{}}}')
            with self.assertRaises(RuntimeError):stream_inventory(path)
    def test_false_proof_status_not_resumable(self):
        from sparkle_provenance import sha256
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'summary.json'
            path.write_text(json.dumps({'status':'passed','product_proven':True,'pending':PENDING,'input_sha256':{}}))
            with self.assertRaises(RuntimeError):resume(path,sha256(path))
    def test_changed_resume_artifact_rejected(self):
        from sparkle_provenance import sha256
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'summary.json';artifact=Path(td)/'raw.json';artifact.write_text('{}')
            record={'status':'extraction_complete_product_unproved','product_proven':False,
                    'pending':PENDING,'input_sha256':{str(artifact):sha256(artifact)}}
            path.write_text(json.dumps(record));digest=sha256(path)
            artifact.write_text('{"changed":1}')
            with self.assertRaises(RuntimeError):resume(path,digest)

if __name__=='__main__':unittest.main()
