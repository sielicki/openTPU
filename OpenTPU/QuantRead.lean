import OpenTPU.Float
import OpenTPU.Backend

/-! Native quantizer prescale and two-stage absolute-maximum tree. Every lane
    uses two separately rounded binary32 multiplications. -/
namespace OpenTPU.QuantRead
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  lanes : Nat := 8
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  if c.lanes < 4 || !powerOfTwo c.lanes then
    throw "quantizer reader requires power-of-two LANES >= 4"

def Config.metadataWidth (c : Config) := 118+c.lanes

private def delay (name : String) (n width : Nat) (value : Expr) : CircuitM Expr := do
  let mut q := value
  for i in [:n] do q ← clocked s!"{name}_{i}" width (ref "en") q
  return q

private def multiply (name : String) (a b : Expr) : CircuitM Expr := do
  let m ← getModule
  setModule <| m.addWire {name := s!"{name}_out",ty := .bitVector 32}
  let result := ref s!"{name}_out"
  emitInstance "otpu_qread_mul" name
    [("clk",ref "clk"),("en",ref "en"),("a",a),("b",b),("y",result)]
  return result

private def larger (a b : Expr) : Expr := mux (lt (slice a 0 31) (slice b 0 31)) b a

def build (c : Config) : Module := runModule "otpu_qread_sparkle" do
  clockOnly
  let en ← input "en" 1
  let csf ← input "csf" 1
  let rsf ← input "rsf" 1
  let data ← input "t_rdata" (32*c.lanes)
  let columns ← input "t_rdata2" (32*c.lanes)
  let rows ← input "t_rdata3" 32
  let m0 ← input "m0" c.metadataWidth
  let badr ← input "badr" 32
  let r3 ← clocked "r3" 32 en (mux rsf rows (lit 0x3f800000))
  let mut values := []
  for l in [:c.lanes] do
    let x1 ← clocked s!"x1_{l}" 32 en (slice data (32*l) 32)
    let x2 ← clocked s!"x2_{l}" 32 en (mux csf (slice columns (32*l) 32) (lit 0x3f800000))
    let v1 ← multiply s!"row_mul{l}" x1 r3
    let cd ← delay s!"column{l}" 2 32 x2
    let xp ← multiply s!"column_mul{l}" v1 cd
    values := values ++ [xp]
  let mp ← delay "metadata" 5 c.metadataWidth m0
  let ba ← delay "address" 6 32 badr
  let mut absolute := []
  for l in [:c.lanes] do
    let v ← wire s!"absolute{l}" 32
      (mux (bit mp l) (.concat [lit 0 1,slice values[l]! 0 31]) (lit 0))
    absolute := absolute ++ [v]
  let half := c.lanes/2
  let mut level := []
  for l in [:half] do
    let ch ← clocked s!"ch{l}" 32 en (larger absolute[l]! absolute[l+half]!)
    level := level ++ [ch]
  for _ in [:clog2 half] do
    let width := level.length/2
    level ← (List.range width).mapM fun l =>
      wire s!"maximum_{width}_{l}" 32 (larger level[l]! level[l+width]!)
  let cmax ← clocked "chunk_max" 32 en level[0]!
  let mh ← clocked "mh" c.metadataWidth en mp
  let mc ← clocked "mc_r" c.metadataWidth en mh
  output "xp" (32*c.lanes) (pack values)
  output "mp" c.metadataWidth mp
  output "mp_baddr" 32 ba
  output "cmax" 32 cmax
  output "mc" c.metadataWidth mc

def registerHints (c : Config) : Backend.RegisterHints :=
  [("metadata_4",[.keep,.noShiftRegister]),("address_5",[.keep,.noShiftRegister])] ++
  (List.range c.lanes).map fun l => (s!"column{l}_1",[.keep,.noShiftRegister])

def toVerilog (c : Config) : Except String String := do
  c.validate
  let core ← Backend.withRegisterHints (build c) (registerHints c)
  let mul ← Backend.withRegisterHints {Float.multiply 2 with name := "otpu_qread_mul"} []
  return core ++ mul

def wrapper (c : Config) : String := s!"
module otpu_qread #(parameter int LANES={c.lanes})(
  input logic clk,en,csf,rsf,
  input logic [LANES-1:0][31:0] t_rdata,t_rdata2,
  input logic [31:0] t_rdata3,badr,
  input logic [117+LANES:0] m0,
  output logic [LANES-1:0][31:0] xp,
  output logic [117+LANES:0] mp,mc,
  output logic [31:0] mp_baddr,cmax
);
  initial if(LANES!={c.lanes}) $fatal(1, \"Sparkle quantizer reader configuration mismatch; regenerate\");
  otpu_qread_sparkle impl(.clk,.en,.csf,.rsf,.t_rdata,.t_rdata2,.t_rdata3,.badr,.m0,.xp,.mp,.mc,.mp_baddr,.cmax);
endmodule
"

end OpenTPU.QuantRead
