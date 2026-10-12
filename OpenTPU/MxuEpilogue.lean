import OpenTPU.MxuConfig
import OpenTPU.MxuHelpers
import OpenTPU.FloatConvert
import OpenTPU.Float

/-! Native MXU floating-point epilogue, from the integer sums at S4 through
    registered rows. Four-way interleaved partial accumulation, optional PAIR
    addition and ordered (p0+p2)+(p1+p3) reduction preserve operation ordering. -/
namespace OpenTPU.MxuEpilogue
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit
open OpenTPU.Mxu OpenTPU.MxuHelpers

private def delay (name : String) (width count : Nat) (en value : Expr) : CircuitM Expr := do
  let mut x := value
  for k in [:count] do x ← clocked s!"{name}{k}" width en x
  return x

private def declared (name : String) (width : Nat) : CircuitM Expr := do
  let m ← getModule
  setModule <| m.addWire {name,ty := .bitVector width}
  return ref name

private def arithmetic (mul : Bool) (name : String) (en a b y : Expr) : CircuitM Unit :=
  emitInstance (if mul then "otpu_mxu_fmul" else "otpu_mxu_fadd") name
    [("clk", ref "clk"), ("en",en), ("a",a), ("b",b), ("y",y)]

/-- Integer conversion used by the common D<=512 fast path. Leading-zero count
    is retained at precisely the reference width, including the zero case. -/
def dotToFloat1 (stem : String) (sw : Nat) (x : Expr) : CircuitM Expr := do
  let mg := sw-1
  let lzw := clog2 mg
  let sign := bit x (sw-1)
  let mag ← wire (stem++"_mag") mg (slice (mux sign (sub (lit 0 sw) x) x) 0 mg)
  let lz ← FloatConvert.leadingZeros stem (pack [lit 0 (32-mg), mag])
  return pack [mag,slice lz 0 lzw,sign,eq x (lit 0 sw)]

def dotToFloat2 (stem : String) (sw : Nat) (m : Expr) : CircuitM Expr := do
  let mg := sw-1
  let lzw := clog2 mg
  let lz := slice m mg lzw
  let nrm ← wire (stem++"_normalized") mg (.op .shl [slice m 0 mg,lz])
  let exponent ← wire (stem++"_exponent") 8 (sub (lit (126+mg) 8) (pack [lz,lit 0 (8-lzw)]))
  let fraction := if mg == 24 then slice nrm 0 23 else pack [lit 0 (24-mg),slice nrm 0 (mg-1)]
  return mux (bit m (mg+lzw+1)) (lit 0) (pack [fraction,exponent,bit m (mg+lzw)])

def build (c : Config) : Module := runModule "otpu_mxu_epilogue_sparkle" do
  clocks
  let en ← input "en_c" 1
  let s4 ← input "s4" (c.columns*c.sumWidth)
  let m4 ← input "m4" 7
  let ws4 ← input "ws4" 32
  let ws4h ← input "ws4h" 32
  let hi0 ← input "hi0" c.columns
  let pr0 ← input "pr0" 1
  let actScale ← input "act_scale" (c.columns*32)
  let pM ← input "p_M" 8
  let m5 ← clocked "m5" 7 en m4
  let m6 ← clocked "m6" 7 en m5
  let ws5 ← clocked "ws5" 32 en ws4
  let ws5h ← clocked "ws5h" 32 en ws4h
  let m0 ← clocked "M0" 8 en pM
  let mtp ← delay "mtp" 7 3 en m6
  reg "mt" 7 true [(en,mtp)]
  let mt := ref "mt"
  let mqp ← delay "mqp" 7 3 en mt
  reg "mq" 7 true [(en,mqp)]
  let mx ← wire "mx" 7 (mux pr0 (ref "mq") mt)
  let ma ← delay "ma" 7 4 en mx
  let zb ← wire "zb" 1 (bor (bnot (bit ma 6))
    (bor (bit ma 5) (band (bit ma 4) (eq (slice ma 2 2) (lit 0 2)))))
  let midY ← delay "my" 1 4 en (band (bit ma 6) (bnot (bit ma 5)))
  let launch ← wire "launch" 1 (band (bit ma 6) (bit ma 5))
  let lv2 ← delay "lv_" 1 9 en launch
  let mut row : List Expr := []
  for j in [:c.columns] do
    let _ ← declared s!"t1_{j}" 32
    let _ ← declared s!"t2_{j}" 32
    let _ ← declared s!"tq_{j}" 32
    let _ ← declared s!"pacc{j}" 32
    let _ ← declared s!"cy{j}" 32
    let _ ← declared s!"rowv{j}" 32
  for j in [:c.columns] do
    let sw := c.sumWidth
    let x := slice s4 (j*sw) sw
    let fi ← if sw-1 ≤ 24 then do
      let imd ← dotToFloat1 s!"i2f1_{j}" sw x
      let im ← clocked s!"im{j}" (sw+1+clog2 (sw-1)) en imd
      let fid ← dotToFloat2 s!"i2f2_{j}" sw im
      clocked s!"fi{j}" 32 en fid
    else do
      let imd ← FloatConvert.integerStage1 s!"i2f1_{j}" (sext x sw 32)
      let im ← clocked s!"im{j}" 40 en imd
      let fid ← FloatConvert.integerStage2 s!"i2f2_{j}" im
      clocked s!"fi{j}" 32 en fid
    reg s!"ws6_{j}" 32 true [(en,mux (bit hi0 j) ws5h ws5)]
    let asp ← delay s!"asp{j}_" 32 (c.dotLatency+3) en (slice actScale (j*32) 32)
    reg s!"asq{j}" 32 true [(en,asp)]
    arithmetic true s!"m1_{j}" en fi (ref s!"ws6_{j}") (ref s!"t1_{j}")
    arithmetic true s!"m2_{j}" en (ref s!"t1_{j}") (ref s!"asq{j}") (ref s!"t2_{j}")
    let tx ← if j < c.columns/2 then do
      let mut pb := lit 0
      for m in [1:c.columns/2+1] do
        if j+m < c.columns then
          pb := mux (band (bit mt 0) (eq m0 (lit m 8))) (ref s!"t2_{j+m}") pb
      let partner ← wire s!"partner{j}" 32 pb
      arithmetic false s!"pair{j}" en (ref s!"t2_{j}") partner (ref s!"tq_{j}")
      pure (mux pr0 (ref s!"tq_{j}") (ref s!"t2_{j}"))
    else do
      emitAssign s!"tq_{j}" (lit 0)
      pure (ref s!"t2_{j}")
    let prev := mux (bit mx 4) (lit 0) (ref s!"pacc{j}")
    arithmetic false s!"acc{j}" en prev tx (ref s!"pacc{j}")
    let pp1 ← clocked s!"pp1_{j}" 32 en (ref s!"pacc{j}")
    let pb ← clocked s!"pb{j}" 32 en (mux zb (lit 0) pp1)
    let cy1 ← clocked s!"cy1_{j}" 32 en (mux midY (ref s!"cy{j}") (lit 0))
    arithmetic false s!"combine_p{j}" en (ref s!"pacc{j}") pb (ref s!"cy{j}")
    arithmetic false s!"combine_c{j}" en cy1 (ref s!"cy{j}") (ref s!"rowv{j}")
    let rr ← clocked s!"rowr{j}" 32 en (ref s!"rowv{j}")
    row := row ++ [rr]
  output "rowr" (c.columns*32) (pack row)
  output "lv2" 1 lv2

def multiply : Module := {Float.multiply 2 with name := "otpu_mxu_fmul"}
def addition : Module := {Float.addition 4 with name := "otpu_mxu_fadd"}

end OpenTPU.MxuEpilogue
