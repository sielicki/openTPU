"""Validate native instance attributes and reject missing/duplicate targets."""
import json
import subprocess
from pathlib import Path
from check_sparkle_physical import functional_tokens

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/sparkle/instance_hints'


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    subprocess.run(['lake','build','OpenTPU.Backend'],cwd=ROOT,check=True)
    source=WORK/'Check.lean'
    source.write_text('''import OpenTPU.Backend
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.Backend
def child : Module := runModule "hint_child" do
  let a ← input "a" 8
  output "y" 8 a
def parent : Module := runModule "hint_parent" do
  let a ← input "a" 8
  let m ← getModule
  setModule (m.addWire {name := "result", ty := .bitVector 8})
  let y := ref "result"
  emitInstance "hint_child" "fifo_group0" [("a",a),("y",y)]
  output "y" 8 y
def requireError (h : InstanceHints) : IO Unit :=
  match withInstanceHints parent h with
  | .error _ => pure ()
  | .ok _ => throw (IO.userError "invalid instance hint accepted")
def requireParameterError (p : InstanceParameters) : IO Unit :=
  match withRegisterHints parent [] false false [] [] p with
  | .error _ => pure ()
  | .ok _ => throw (IO.userError "invalid instance parameter accepted")
def main : IO Unit := do
  requireError [("missing",[.keepHierarchy])]
  requireError [("fifo_group0",[])]
  requireError [("fifo_group0",[.keepHierarchy]),("fifo_group0",[.keepHierarchy])]
  requireParameterError [("missing",[("N",.nat 1)])]
  requireParameterError [("fifo_group0",[("bad-name",.nat 1)])]
  requireParameterError [("fifo_group0",[("N",.nat 1),("N",.nat 2)])]
  requireParameterError [("fifo_group0",[("N",.bits 0 0)])]
  requireParameterError [("fifo_group0",[("N",.bits 2 4)])]
  requireParameterError [("fifo_group0",[("N",.nat 1)]),("fifo_group0",[("N",.nat 2)])]
  let plain := Sparkle.Backend.Verilog.toVerilog parent
  let hinted ← match withInstanceHints parent [("fifo_group0",[.keepHierarchy])] with
    | .ok text => pure text
    | .error message => throw (IO.userError message)
  IO.FS.writeFile "PLAIN" plain
  IO.FS.writeFile "HINTED" (Sparkle.Backend.Verilog.toVerilog child ++ hinted)
  let params ← match withRegisterHints parent [] false false [] []
      [("fifo_group0",[("N",.nat 7),("MASK",.bits 48 (2^48-1)),("MODE",.string "ONE48"),
        ("ESC",.string (String.ofList ['a',Char.ofNat 34,'b',Char.ofNat 92,'c']))])] with
    | .ok text => pure text
    | .error message => throw (IO.userError message)
  IO.FS.writeFile "PARAMS" params
'''.replace('PLAIN',str(WORK/'plain.sv')).replace('HINTED',str(WORK/'hinted.sv')).replace('PARAMS',str(WORK/'params.sv')))
    subprocess.run(['lake','env','lean','--run',str(source)],cwd=ROOT,check=True)
    hinted=(WORK/'hinted.sv').read_text()
    parent=hinted[hinted.index('module hint_parent'):]
    assert functional_tokens(parent)==functional_tokens((WORK/'plain.sv').read_text())
    subprocess.run(['yosys','-Q','-T','-q','-p',
        f'read_verilog -sv {WORK}/hinted.sv; hierarchy -top hint_parent; write_json {WORK}/hinted.json'],cwd=ROOT,check=True)
    module=json.loads((WORK/'hinted.json').read_text())['modules']['hint_parent']
    assert module['cells']['fifo_group0']['attributes']['keep_hierarchy']=='yes'
    subprocess.run(['yosys','-Q','-T','-q','-p',
        f'read_verilog -sv {WORK}/params.sv; write_json {WORK}/params.json'],cwd=ROOT,check=True)
    params=json.loads((WORK/'params.json').read_text())['modules']['hint_parent']['cells']['fifo_group0']['parameters']
    assert int(params['N'],2)==7 and params['MASK']=='1'*48
    assert params['MODE']=='ONE48' and params['ESC']=='a"b\\c',params
    (WORK/'summary.json').write_text(json.dumps({'status':'passed','functional_tokens_unchanged':True,
        'yosys_keep_hierarchy':'yes','typed_parameters_parsed':True,
        'rejected':['missing instance','empty attributes','duplicate instance','unsafe parameter identifier',
                    'duplicate parameter','zero bit width','overflowing bit value','duplicate parameter instance']},indent=2)+'\n')
    print('PASS instance hints: unchanged functional tokens, Yosys hierarchy/typed parameters, invalid targets rejected')


if __name__=='__main__':main()
