import OpenTPU.Circuit

/-! Native openTPU binary32 pipelines: round-to-nearest-even, signed zeros,
    canonical NaNs, and flush-to-zero. Multiply rounds after two enabled edges;
    add after four. Composites deliberately retain separate roundings. -/
namespace OpenTPU.Float
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

private def nz (x : Expr) (width : Nat) := bnot (eq x (lit 0 width))
private def ext (x : Expr) (extra : Nat) := Expr.concat [lit 0 extra, x]
private def sign (x : Expr) := bit x 31
private def exponent (x : Expr) := slice x 23 8
private def mantissa (x : Expr) := slice x 0 23
private def inf (s : Expr) := Expr.concat [s, lit 255 8, lit 0 23]
private def zero (s : Expr) := Expr.concat [s, lit 0 31]
private def nan (x : Expr) := band (eq (exponent x) (lit 255 8)) (nz (mantissa x) 23)
private def ftz (x : Expr) := mux (eq (exponent x) (lit 0 8)) (zero (sign x)) x
private def xor (a b : Expr) := Expr.xor a b
private def shl (x : Expr) (n : Nat) := Expr.op .shl [x, lit n]
private def shr (x : Expr) (n : Nat) := Expr.op .shr [x, lit n]

/-- Unreset pipeline registers with an explicit clock enable. -/
private def stage (name : String) (width : Nat) (value : Expr) : CircuitM Expr := do
  let m ← getModule
  setModule <| (m.addWire { name, ty := .bitVector width }).addStmt
    (.register name "clk" ("no_reset", .synchronous)
      (mux (ref "en") value (ref name)) 0)
  return ref name

private def ports : CircuitM (Expr × Expr) := do
  addInput "clk" .bit
  let _ ← input "en" 1
  let m ← getModule
  setModule <| (m.addWire { name := "no_reset", ty := .bit }).addStmt (.assign "no_reset" (lit 0 1))
  let a ← input "a" 32
  let b ← input "b" 32
  return (a, b)

private def pad (value : Expr) (n : Nat) : CircuitM Expr := do
  let mut v := value
  for i in [:n] do v ← stage s!"pad{i}" 32 v
  return v

/-- Two-stage 24×24 multiplier and its guard/sticky rounding stage. -/
def multiply (latency : Nat := 2) : Module := runModule s!"otpu_fmul_sparkle_{latency}" do
  let (ai, bi) ← ports
  let a ← wire "a_ftz" 32 (ftz ai)
  let b ← wire "b_ftz" 32 (ftz bi)
  let s := xor (sign a) (sign b)
  let special := bor (eq (exponent a) (lit 255 8)) (eq (exponent b) (lit 255 8))
  let zeros := bor (eq (exponent a) (lit 0 8)) (eq (exponent b) (lit 0 8))
  let invalid := bor (bor (nan a) (nan b))
    (bor (eq (slice a 0 31) (lit 0 31)) (eq (slice b 0 31) (lit 0 31)))
  let sp ← stage "m_sp" 1 (bor special zeros)
  let sv ← stage "m_sv" 32 (mux special (mux invalid (lit 0x7fc00000) (inf s)) (zero s))
  let s ← stage "m_s" 1 s
  let e ← stage "m_e" 11 (sub (add (ext (exponent a) 3) (ext (exponent b) 3)) (lit 127 11))
  let p ← stage "m_p" 48 (.mul (.concat [lit 1 1, mantissa ai]) (.concat [lit 1 1, mantissa bi]))
  let hi := bit p 47
  let mm ← wire "mm" 24 (mux hi (slice p 24 24) (slice p 23 24))
  let g := mux hi (bit p 23) (bit p 22)
  let sticky := mux hi (nz (slice p 0 23) 23) (nz (slice p 0 22) 22)
  let e0 ← wire "e0" 11 (add e (ext hi 10))
  let mr ← wire "mr" 25 (add (ext mm 1) (ext (band g (bor sticky (bit mm 0))) 24))
  let carry := bit mr 24
  let overflow := bor (.op .ge_s [e0, lit 255 11]) (band (eq e0 (lit 254 11)) carry)
  let underflow := bor (.op .lt_s [e0, lit 0 11]) (band (eq e0 (lit 0 11)) (bnot carry))
  let exp ← wire "rounded_exp" 8 (add (slice e0 0 8) (ext carry 7))
  let value := mux sp sv (mux overflow (inf s) (mux underflow (zero s)
    (.concat [s, exp, slice mr 0 23])))
  let result ← stage "result" 32 value
  output "y" 32 (← pad result (latency - 2))

/-- Four-stage adder: unpack/order, align/add, normalize, round. -/
def addition (latency : Nat := 4) (duplicate : Bool := false) : Module :=
    runModule (if duplicate then "otpu_fadd2_sparkle" else s!"otpu_fadd_sparkle_{latency}") do
  let (ai, bi) ← ports
  let a ← wire "a_ftz" 32 (ftz ai)
  let b ← wire "b_ftz" 32 (ftz bi)
  let aInf := eq (exponent a) (lit 255 8)
  let bInf := eq (exponent b) (lit 255 8)
  let invalid := bor (bor (nan a) (nan b)) (band (band aInf bInf) (xor (sign a) (sign b)))
  let sp1 ← stage "p1_sp" 1 (bor aInf bInf)
  let sv1 ← stage "p1_sv" 3 (mux invalid (lit 3 3) (.concat [mux aInf (sign a) (sign b), lit 2 2]))
  let swap := lt (slice a 0 31) (slice b 0 31)
  let big ← wire "big" 32 (mux swap b a)
  let small ← wire "small" 32 (mux swap a b)
  let sa1 ← stage "p1_sa" 1 (sign big)
  let sub1 ← stage "p1_sub" 1 (xor (sign big) (sign small))
  let e1 ← stage "p1_e" 8 (exponent big)
  let d1 ← stage "p1_d" 8 (sub (exponent big) (exponent small))
  let ma1 ← stage "p1_ma" 27 (.concat [nz (exponent big) 8, mantissa big, lit 0 3])
  let mb1 ← stage "p1_mb" 27 (.concat [nz (exponent small) 8, mantissa small, lit 0 3])
  let mut aligned := mb1
  let mut sticky := lit 0 1
  for i in [4, 3, 2, 1, 0] do
    let amount := 2^i
    sticky ← wire s!"sticky{i}" 1 (bor sticky (band (bit d1 i) (nz (slice aligned 0 amount) amount)))
    aligned ← wire s!"align{i}" 27 (mux (bit d1 i) (shr aligned amount) aligned)
  let mb ← wire "aligned" 27 (mux (lt (lit 26 8) d1) (lit 1 27) (bor aligned (ext sticky 26)))
  let sp2 ← stage "p2_sp" 1 sp1
  let sv2 ← stage "p2_sv" 3 sv1
  let sa2 ← stage "p2_sa" 1 sa1
  let sub2 ← stage "p2_sub" 1 sub1
  let e2 ← stage "p2_e" 8 e1
  let sum ← stage "p2_sum" 28 (mux sub1 (sub (ext ma1 1) (ext mb 1)) (add (ext ma1 1) (ext mb 1)))
  let mut norm := sum
  let mut counts := []
  for amount in [16, 8, 4, 2, 1] do
    let empty ← wire s!"norm_empty{amount}" 1 (eq (slice norm (28 - amount) amount) (lit 0 amount))
    counts := counts ++ [empty]
    norm ← wire s!"norm{amount}" 28 (mux empty (shl norm amount) norm)
  let count ← wire "norm_count" 5 (.concat counts)
  let cancel := band sub2 (band (bnot (bit norm 27)) (bnot sp2))
  let sp3 ← stage "p3_sp" 1 (bor sp2 cancel)
  let sv3 ← stage "p3_sv" 3 (mux cancel (lit 0 3) sv2)
  let s3 ← stage "p3_s" 1 sa2
  let e3 ← stage "p3_e" 9 (sub (ext e2 1) (ext count 4))
  let mn ← stage "p3_mn" 27 (.concat [slice norm 2 26, bor (bit norm 1) (bit norm 0)])
  let mm := slice mn 3 24
  let g := bit mn 2
  let rs := bor (bit mn 1) (bit mn 0)
  let mr ← wire "mr" 25 (add (ext mm 1) (ext (band g (bor rs (bit mm 0))) 24))
  let carry := bit mr 24
  let overflow := bor (.op .ge_s [e3, lit 254 9]) (band (eq e3 (lit 253 9)) carry)
  let underflow := bor (.op .lt_s [e3, .const (-1) 9]) (band (eq e3 (.const (-1) 9)) (bnot carry))
  let exp ← wire "rounded_exp" 8 (add (slice e3 0 8) (.concat [lit 0 6, carry, bnot carry]))
  let specialValue := Expr.concat [bit sv3 2, mux (bit sv3 1) (lit 255 8) (lit 0 8), bit sv3 0, lit 0 22]
  let value := mux sp3 specialValue (mux overflow (inf s3)
    (mux underflow (zero s3) (.concat [s3, exp, slice mr 0 23])))
  let result ← stage "result" 32 value
  output "y" 32 (← pad result (latency - 4))
  if duplicate then output "yo" 32 (← stage "result_copy" 32 value)

end OpenTPU.Float
