import OpenTPU.Float
import OpenTPU.FloatConvert
import OpenTPU.Backend

/-! Native quantizer write pipeline. Metadata and scales track the enabled
    arithmetic edges; only the final metadata register resets. -/
namespace OpenTPU.QuantWrite
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  lanes : Nat := 8
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  if c.lanes < 4 || !powerOfTwo c.lanes then
    throw "quantizer writer requires power-of-two LANES >= 4"

def Config.metadataWidth (c : Config) := 92+c.lanes

/-- Exact private qq8_s1 behavior, including otherwise unused subnormal fields.
    Decode shifts directly to preserve the reference's short exponent path. -/
def stage1 (stem : String) (x : Expr) : CircuitM Expr := do
  let e := slice x 23 8
  let m ← wire s!"{stem}_mantissa" 32 (.concat [lit 0 8,lit 1 1,slice x 0 23])
  let mut sh := lit 17 5
  let mut k := lit 16 5
  for c in [126:134] do
    sh := mux (eq e (lit c 8)) (lit (150-c) 5) sh
    k := mux (eq e (lit c 8)) (lit (149-c) 5) k
  let shift ← wire s!"{stem}_shift" 5 sh
  let guardIndex ← wire s!"{stem}_guard_index" 5 k
  let ip ← wire s!"{stem}_integer" 32 (.op .shr [m,shift])
  let guard ← wire s!"{stem}_guard" 32 (.op .shr [m,guardIndex])
  return pack [FloatConvert.stickyBelow m guardIndex,bit guard 0,ip,bit x 31,
    bnot (lt e (lit 134 8)),lt e (lit 126 8)]

def build (c : Config) : Module := runModule "otpu_qwrite_sparkle" do
  clocks
  let en ← input "en" 1
  let wq ← input "wq" c.metadataWidth
  let wx ← input "wx" (32*c.lanes)
  let winv ← input "winv" 32
  let wsc ← input "wsc_in" 32
  let wq ← clocked "wq_r" c.metadataWidth en wq
  let winv ← clocked "winv_r" 32 en winv
  let wsc ← clocked "wsc_r" 32 en wsc
  let mut bytes := []
  for l in [:c.lanes] do
    let x ← clocked s!"wx_r{l}" 32 en (slice wx (32*l) 32)
    let m ← getModule
    setModule <| m.addWire {name := s!"product{l}",ty := .bitVector 32}
    let p := ref s!"product{l}"
    emitInstance "otpu_qwrite_mul" s!"multiply{l}"
      [("clk",ref "clk"),("en",en),("a",x),("b",winv),("y",p)]
    let qm ← clocked s!"qm{l}" 37 en (← stage1 s!"q1_{l}" p)
    let qb ← clocked s!"qb{l}" 8 en (← FloatConvert.quantizeStage2 s!"q2_{l}" qm)
    bytes := bytes ++ [qb]
  let mut metadata := wq
  let mut scale := wsc
  for i in [:4] do
    if i == 3 then
      reg s!"metadata{i}" c.metadataWidth true [(en,metadata)]
      metadata := ref s!"metadata{i}"
    else metadata ← clocked s!"metadata{i}" c.metadataWidth en metadata
    scale ← clocked s!"scale{i}" 32 en scale
  output "wqd" c.metadataWidth metadata
  output "qb" (8*c.lanes) (pack bytes)
  output "wsc_d" 32 scale

def registerHints : Backend.RegisterHints :=
  [("metadata3",[.keep,.noShiftRegister]),("scale3",[.keep,.noShiftRegister])]

def toVerilog (c : Config) : Except String String := do
  c.validate
  let core ← Backend.withRegisterHints (build c) registerHints
  let mul ← Backend.withRegisterHints {Float.multiply 2 with name := "otpu_qwrite_mul"} []
  return core ++ mul

def wrapper (c : Config) : String := s!"
module otpu_qwrite #(parameter int LANES={c.lanes})(
  input logic clk,rst,en,
  input logic [91+LANES:0] wq,
  input logic [LANES-1:0][31:0] wx,
  input logic [31:0] winv,wsc_in,
  output logic [91+LANES:0] wqd,
  output logic [LANES-1:0][7:0] qb,
  output logic [31:0] wsc_d
);
  initial if(LANES!={c.lanes}) $fatal(1, \"Sparkle quantizer writer configuration mismatch; regenerate\");
  otpu_qwrite_sparkle impl(.clk,.rst,.en,.wq,.wx,.winv,.wsc_in,.wqd,.qb,.wsc_d);
endmodule
"

end OpenTPU.QuantWrite
