import OpenTPU.Float
import OpenTPU.FloatConvert
import OpenTPU.Backend

/-! Native quantizer scale pipeline: three separately rounded Newton steps,
    scale/inverse products, flags, tags, and grant-stalled delay lines. -/
namespace OpenTPU.QuantScale
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  multiplyLatency : Nat := 2
  addLatency : Nat := 4
  tagWidth : Nat := 2
  deriving Repr

def Config.step (c : Config) := c.multiplyLatency + c.addLatency + c.multiplyLatency
def Config.latency (c : Config) := 3*c.step + c.multiplyLatency

def Config.validate (c : Config) : Except String Unit := do
  if c.multiplyLatency < 2 || c.addLatency < 4 || c.tagWidth == 0 then
    throw "quantizer scale requires LM >= 2, LA >= 4, TW > 0"

private def declared (name : String) (width : Nat) : CircuitM Expr := do
  let m ← getModule
  setModule <| m.addWire { name, ty := .bitVector width }
  return ref name

private def delay (name : String) (n width : Nat) (value : Expr)
    (resetLast : Bool := false) (initial : Int := 0) : CircuitM Expr := do
  let mut q := value
  for i in [:n] do
    if resetLast && i+1 == n then
      reg s!"{name}_{i}" width true [(ref "en", q)]
      q := ref s!"{name}_{i}"
    else
      let register := s!"{name}_{i}"
      let m ← getModule
      setModule <| (m.addWire {name := register,ty := .bitVector width}).addStmt
        (.register register "clk" ("no_reset", .synchronous)
          (mux (ref "en") q (ref register)) initial)
      q := ref register
  return q

private def arithmetic (c : Config) (name : String) (a b : Expr) (multiply : Bool) : CircuitM Expr := do
  let result ← declared s!"{name}_result" 32
  emitInstance (if multiply then s!"otpu_qscale_mul_{c.multiplyLatency}" else s!"otpu_qscale_add_{c.addLatency}")
    name [("clk", ref "clk"), ("en", ref "en"), ("a", a), ("b", b), ("y", result)]
  return result

def build (c : Config) : Module := runModule "otpu_qscale_sparkle" do
  clocks
  let en ← input "en" 1
  let iv ← input "iv" 1
  let itag ← input "itag" c.tagWidth
  let amax ← input "amax" 32
  let amax ← clocked "amax_q" 32 en amax
  let iv ← clocked "iv_q" 1 en iv
  let itag ← clocked "itag_q" c.tagWidth en itag
  let a ← wire "absolute" 32 (.concat [lit 0 1, slice amax 0 31])
  let ax ← clocked "ax" 32 en a
  let zero ← clocked "zero" 1 en (eq a (lit 0))
  let big ← clocked "big" 1 en (bnot (lt a (lit 0x7e800000)))
  let seed ← wire "seed" 32 (sub (lit 0x7ef311c3) a)
  let mut y ← clocked "y0" 32 en (FloatConvert.ftz seed)
  let mut k := Expr.concat [lit 1 1, slice ax 0 31]
  for i in [:3] do
    let product ← arithmetic c s!"t_mul{i}" k y true
    let two ← delay s!"two{i}" c.multiplyLatency 32 (lit 0x40000000)
    let t ← arithmetic c s!"t_add{i}" product two false
    let yd ← delay s!"yd{i}" (c.multiplyLatency+c.addLatency) 32 y true
    -- k0 has a constant sign bit of one. Give its unreset stages that
    -- legal initial value so synthesis can fold the constant; its resettable
    -- endpoint still initializes/resets to zero. Other delay state stays zero.
    k ← delay s!"k{i}" c.step 32 k true (if i == 0 then 0x80000000 else 0)
    y ← arithmetic c s!"y_mul{i}" yd t true
  let flags ← delay "flags" (3*c.step) 2 (pack [big,zero]) true
  let inv ← arithmetic c "inv_mul" (lit 0x42fe0000) y true
  let sc ← arithmetic c "scale_mul" ax (lit 0x3c010204) true
  let sc ← delay "scale" (3*c.step) 32 sc
  let flags ← delay "final_flags" c.multiplyLatency 2 flags
  let tag ← delay "tag" (c.latency+1) (1+c.tagWidth) (pack [itag,iv])
  output "ov" 1 (bit tag c.tagWidth)
  output "otag" c.tagWidth (slice tag 0 c.tagWidth)
  output "inv" 32 (mux (bnot (eq flags (lit 0 2))) (lit 0) inv)
  output "sc" 32 (mux (bit flags 1) (lit 0) sc)

def registerHints (c : Config) : Backend.RegisterHints :=
  let endpoint := fun (name : String) (n : Nat) => (s!"{name}_{n-1}", [.keep, .noShiftRegister])
  ((List.range 3).flatMap fun i =>
    [endpoint s!"two{i}" c.multiplyLatency,
     endpoint s!"yd{i}" (c.multiplyLatency+c.addLatency), endpoint s!"k{i}" c.step]) ++
  [endpoint "flags" (3*c.step), endpoint "scale" (3*c.step),
   endpoint "final_flags" c.multiplyLatency, endpoint "tag" (c.latency+1)]

def toVerilog (c : Config) : Except String String := do
  c.validate
  let core ← Backend.withRegisterHints (build c) (registerHints c)
  let padding := fun (n : Nat) => if n == 0 then [] else [(s!"pad{n-1}", [.keep, .noShiftRegister])]
  let mul ← Backend.withRegisterHints
    { Float.multiply c.multiplyLatency with name := s!"otpu_qscale_mul_{c.multiplyLatency}" }
    (padding (c.multiplyLatency-2))
  let add ← Backend.withRegisterHints
    { Float.addition c.addLatency with name := s!"otpu_qscale_add_{c.addLatency}" }
    (padding (c.addLatency-4))
  return core ++ mul ++ add

def wrapper (c : Config) : String := s!"
module otpu_qscale #(parameter int LM={c.multiplyLatency}, LA={c.addLatency}, TW={c.tagWidth})(
  input logic clk,rst,en,iv,
  input logic [TW-1:0] itag,
  input logic [31:0] amax,
  output logic ov,
  output logic [TW-1:0] otag,
  output logic [31:0] sc,inv
);
  initial if(LM!={c.multiplyLatency} || LA!={c.addLatency} || TW!={c.tagWidth})
    $fatal(1, \"Sparkle quantizer scale configuration mismatch; regenerate\");
  otpu_qscale_sparkle impl(.clk,.rst,.en,.iv,.itag,.amax,.ov,.otag,.sc,.inv);
endmodule
"

end OpenTPU.QuantScale
