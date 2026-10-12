import OpenTPU.Mxu
import OpenTPU.MxuStoragePhysical
import OpenTPU.Backend

/-! Explicit DSP48E1 systolic hardware. The qualified behavioral builders remain
    independent. This pass replaces their PE and column-end statements in the
    native AST, preserving every operand skew and metadata pipeline. -/
namespace OpenTPU.MxuPhysical
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit
open OpenTPU.Mxu OpenTPU.MxuHelpers OpenTPU.Backend

private def declare (name : String) (width : Nat) : CircuitM Expr := do
  let m ← getModule
  setModule <| m.addWire {name,ty := .bitVector width}
  return ref name

private def n (b : Bool) : Nat := if b then 1 else 0

def peName (first last wreg : Bool) : String :=
  s!"otpu_mxu_pe_dsp_{n first}{n last}{n wreg}"

def colendName (width : Nat) : String := s!"otpu_mxu_colend_dsp_{width}"

private def parameters (areg dreg preg inmodereg : Nat) : List (String × ParamValue) :=
  [("A_INPUT",.string "DIRECT"),("B_INPUT",.string "DIRECT"),
   ("USE_DPORT",.string "TRUE"),("USE_MULT",.string "MULTIPLY"),
   ("USE_SIMD",.string "ONE48"),("AREG",.nat areg),("ACASCREG",.nat areg),
   ("BREG",.nat 1),("BCASCREG",.nat 1),("CREG",.nat 0),("DREG",.nat dreg),
   ("ADREG",.nat 0),("MREG",.nat 1),("PREG",.nat preg),
   ("INMODEREG",.nat inmodereg),("OPMODEREG",.nat 0),("ALUMODEREG",.nat 0),
   ("CARRYINREG",.nat 0),("CARRYINSELREG",.nat 0),
   ("USE_PATTERN_DETECT",.string "NO_PATDET"),("AUTORESET_PATDET",.string "NO_RESET"),
   ("MASK",.bits 48 0x3fffffffffff),("PATTERN",.bits 48 0),
   ("SEL_MASK",.string "MASK"),("SEL_PATTERN",.string "PATTERN")]

private def fixedPorts : List (String × Expr) :=
  [("CLK",ref "clk"),("C",lit 0 48),("ALUMODE",lit 0 4),
   ("CARRYIN",lit 0 1),("CARRYINSEL",lit 0 3),
   ("ACIN",lit 0 30),("BCIN",lit 0 18),("CARRYCASCIN",lit 0 1),
   ("MULTSIGNIN",lit 0 1)] ++
  (["CEC","CEAD","CEALUMODE","CECTRL","CECARRYIN",
    "RSTA","RSTB","RSTC","RSTD","RSTM","RSTP","RSTALLCARRYIN",
    "RSTALUMODE","RSTCTRL","RSTINMODE"].map fun name => (name,lit 0 1))

/-- Physical PCOUT retains the primitive's full-width cascade, including LAST.
    LAST's cascade has no consumer in the native dot hierarchy. -/
def pe (first last wreg : Bool) : Module := runModule (peName first last wreg) do
  addInput "clk" .bit
  let en ← input "en" 1
  let act ← input "act" 8
  let wlo ← input "wlo" 8
  let whi ← input "whi" 8
  let sel ← input "sel" 1
  let pcin ← input "pcin" 48
  let pf ← declare "pf" 48
  let pc ← declare "pc" 48
  emitInstance "DSP48E1" "u_dsp" <| fixedPorts ++
    [("A",sext wlo 8 30),("B",sext act 8 18),("D",sext whi 8 25),
     ("INMODE",pack [lit 0 1,sel,sel,lit 0 2]),
     ("OPMODE",lit (if first then 5 else 21) 7),
     ("CEA1",lit 0 1),("CEA2",if wreg then en else lit 0 1),
     ("CEB1",en),("CEB2",en),("CED",if wreg then en else lit 0 1),
     ("CEM",en),("CEP",if last then lit 0 1 else en),("CEINMODE",en),
     ("PCIN",pcin),("P",pf),("PCOUT",pc)]
  output "p" 24 (slice pf 0 24)
  output "pcout" 48 pc

def peParameters (_first last wreg : Bool) : InstanceParameters :=
  [("u_dsp",parameters (n wreg) (n wreg) (n (!last)) 1)]

def colend (sumWidth : Nat) : Module := runModule (colendName sumWidth) do
  addInput "clk" .bit
  let en ← input "en" 1
  let a ← input "a" 96
  let d ← input "d" 96
  let mb ← input "mb" 16
  let mut pcin := lit 0 48
  let mut result := lit 0 48
  for b in [:4] do
    let pf ← declare s!"pf{b}" 48
    let pc ← declare s!"pc{b}" 48
    emitInstance "DSP48E1" s!"u_dsp{b}" <| fixedPorts ++
      [("A",sext (slice a (b*24) 24) 24 30),
       ("B",pack [slice mb (b*4) 4,lit 0 14]),
       ("D",sext (slice d (b*24) 24) 24 25),
       ("INMODE",lit 4 5),("OPMODE",lit (if b == 0 then 5 else 21) 7),
       ("CEA1",en),("CEA2",en),("CEB1",en),("CEB2",en),("CED",en),
       ("CEM",en),("CEP",if b == 3 then en else lit 0 1),("CEINMODE",lit 0 1),
       ("PCIN",pcin),("P",pf),("PCOUT",pc)]
    pcin := pc
    result := pf
  output "s" sumWidth (slice result 0 sumWidth)

def colendParameters : InstanceParameters :=
  (List.range 4).map fun b => (s!"u_dsp{b}",parameters 1 1 (n (b == 3)) 0)

private def replacedNames (c : Config) : List String := Id.run do
  let mut names := []
  for j in [:c.columns] do
    for i in [:c.d] do
      let suffixes := ["br","selr","m"] ++ (if j == 0 then [] else ["wlr","whr"])
      names := names ++ (suffixes.map fun suffix => s!"pe{j}_{i}_{suffix}") ++ [s!"preg{j}_{i}"]
    names := names ++ [s!"ce{j}_mr",s!"ce{j}_s"] ++
      ((List.range 4).flatMap fun b => [s!"ce{j}_ar{b}",s!"ce{j}_dr{b}",s!"ce{j}_v{b}"])
  return names

private def target? : Stmt → Option String
  | .register name .. => some name
  | .assign name _ => some name
  | _ => none

private def replacement (c : Config) : Module := runModule "physical_replacement" do
  let cls := min (c.d/4) c.chainLength
  let cps := c.d/4/cls
  let cpa := (cps+1)/2
  let en := ref "en_c"
  for j in [:c.columns] do
    for i in [:c.d] do
      let first := i%cls == 0
      let last := i%cls == cls-1
      let askCount := i%cls+j
      let ask := if askCount == 0 then slice (ref "a0") ((j*c.d+i)*8) 8
        else ref s!"ask{j}_{i}_{askCount-1}"
      let wc := ref s!"wc{if j == 0 then 0 else j-1}_{i}"
      let pc ← declare s!"physical_pc{j}_{i}" 48
      emitInstance (peName first last (j > 0)) s!"physical_pe{j}_{i}"
        [("clk",ref "clk"),("en",en),("act",ask),
         ("wlo",slice wc 0 8),("whi",slice wc 8 8),("sel",bit (ref "c_hi") j),
         ("pcin",if first then lit 0 48 else ref s!"physical_pc{j}_{i-1}"),
         ("p",ref s!"preg{j}_{i}"),("pcout",pc)]
    let ends := fun b lo hi => ((List.range cps).filter fun k => lo ≤ k && k < hi).map fun k =>
      ref s!"preg{j}_{(b*cps+k)*cls+cls-1}"
    let total := fun xs => xs.foldl add (lit 0 24)
    emitInstance (colendName c.sumWidth) s!"physical_ce{j}"
      [("clk",ref "clk"),("en",en),
       ("a",pack ((List.range 4).map fun b => total (ends b 0 cpa))),
       ("d",pack ((List.range 4).map fun b => total (ends b cpa cps))),
       ("mb",ref s!"mbd{j}_{cls+j}"),("s",ref s!"ce{j}_s")]

/-- Reject stale rewrite assumptions instead of silently leaving a behavioral
    register next to a primitive driver. No emitted HDL is parsed or patched. -/
def dot (c : Config) : Except String Module := do
  c.validate
  let base := MxuDot.build c
  if c.implementation != 2 then return base
  let names := replacedNames c
  for name in names do
    if (base.body.filter fun stmt => target? stmt == some name).length != 1 then
      throw s!"mxu physical: expected exactly one driver for {name}"
  let extra := replacement c
  for w in extra.wires do
    if (base.inputs ++ base.outputs ++ base.wires).any (·.name == w.name) then
      throw s!"mxu physical: generated declaration collision {w.name}"
  let retained := (List.range c.columns).flatMap fun j =>
    s!"ce{j}_s" :: (List.range c.d).map (fun i => s!"preg{j}_{i}")
  return {base with
    wires := base.wires.filter (fun w => !names.contains w.name || retained.contains w.name) ++ extra.wires
    body := base.body.filter (fun stmt => !(target? stmt).any names.contains) ++ extra.body}

def primitiveModules (c : Config) : List (Module × InstanceParameters) :=
  if c.implementation != 2 then [] else
    ([false,true].flatMap fun first => [false,true].flatMap fun last =>
      [false,true].map fun wreg => (pe first last wreg,peParameters first last wreg)) ++
    [(colend c.sumWidth,colendParameters)]

def emitDot (c : Config) : Except String String := do
  let m ← dot c
  let mut result := Sparkle.Backend.Verilog.toVerilog m
  for (primitive,params) in primitiveModules c do
    result := result ++ "\n" ++ (← withRegisterHints primitive [] false false [] [] params)
  return result

def emit (c : Config) : Except String String := do
  c.validateWhole
  let storage ← MxuStoragePhysical.emit c
  let datapath ← emitDot c
  return storage ++ "\n" ++ datapath ++ "\n" ++ String.intercalate "\n"
    ([MxuEpilogue.multiply,MxuEpilogue.addition,MxuEpilogue.build c,Mxu.build c].map
      Sparkle.Backend.Verilog.toVerilog)

end OpenTPU.MxuPhysical
