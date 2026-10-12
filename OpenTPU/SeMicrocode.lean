import OpenTPU.SeqWindow

/-! Native composite-stage microcode. The operation table is evaluated in Lean
    at elaboration time; hardware contains only constant ROM muxes. -/
namespace OpenTPU.SeMicrocode
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Op where
  a : Nat := 0
  b : Nat := 2
  c : Nat := 0
  dst : Nat := 1
  neg : Bool := false
  kb : Nat := 0x3f800000
  kc : Nat := 0x80000000
  kv : Nat := 0
  deriving Repr

def Op.encode (u : Op) : Nat :=
  u.kv ||| (u.kc <<< 32) ||| (u.kb <<< 64) |||
  ((if u.neg then 1 else 0) <<< 96) ||| (u.dst <<< 97) |||
  (u.c <<< 99) ||| (u.b <<< 101) ||| (u.a <<< 103)

private def expCoefficient (i : Nat) : Nat :=
  #[0x3f800000,0x3f317218,0x3e75fdf0,0x3d635847,
    0x3c1d955b,0x3aaec3ff,0x39218489,0x377fe5fe][i]?.getD 0x377fe5fe

private def logCoefficient (i : Nat) : Nat :=
  #[0x3e00db73,0x3fb8aa3b,0xbf38aa38,0x3ef639eb,0xbeb8ae27,
    0x3e9369c2,0xbe74adf2,0x3e5ce48e,0xbe543e8e][i]?.getD 0x3e00db73

def operationCount (cls : Nat) : Nat :=
  if cls == 1 || cls == 2 then 9 else if cls == 3 then 6
  else if cls == 4 || cls == 5 then 10 else 1

def passCount (stages cls : Nat) : Nat :=
  if cls >= 1 && cls <= 5 then ((operationCount cls + stages - 1) / stages) % 16 else 1

/-- Nonnegative operation indices, including the identity padding after the last
    operation. Runtime ROM indices cover all sixteen passes, including unused ones. -/
def operation (cls k : Nat) : Op := Id.run do
  let u : Op := {}
  if cls == 1 || cls == 2 then
    if k == 0 then return {u with a := 3, c := if cls == 2 then 2 else 0}
    else if k == 1 then return {u with c := 1, dst := 2, kv := expCoefficient 7}
    else if k <= 8 then return {u with b := 0, kc := expCoefficient (8-k)}
  else if cls == 3 && k < 6 then
    if k % 2 == 0 then return {u with a := 1, b := 1, kc := 0x40000000}
    else return {u with b := 1, dst := if k == 5 then 1 else 3}
  else if cls == 4 then
    if k == 0 then return {u with a := 3, kb := 0x3f000000, dst := 2, neg := true}
    else if k < 10 then
      if (k-1) % 3 == 0 then return {u with a := 2, b := 1}
      else if (k-1) % 3 == 1 then return {u with b := 0, kc := 0x3fc00000}
      else return {u with b := 1, dst := if k == 9 then 1 else 3}
  else if cls == 5 then
    if k == 0 then return {u with a := 1, kc := 0xbf800000, dst := 2, kv := logCoefficient 9}
    else if k <= 8 then return {u with b := 0, kc := logCoefficient (9-k)}
    else if k == 9 then return {u with b := 0, c := 1}
  return u

def stageUse (stages stage field : Nat) : Nat := Id.run do
  let mut mask := 0
  for cls in [1:6] do
    for p in [:passCount stages cls] do
      let u := operation cls (p*stages+stage)
      let index := if field == 0 then u.a else if field == 1 then u.b
        else if field == 2 then u.c else u.dst
      mask := mask ||| (1 <<< index)
  return mask

def usesConstant (stages stage : Nat) : Bool := Id.run do
  for cls in [1:6] do
    for p in [:passCount stages cls] do
      let u := operation cls (p*stages+stage)
      if u.dst != 1 && u.kv != 0 then return true
  return false

def rom (stages stage : Nat) (cls pass : Expr) : Expr :=
  SeqWindow.select ((List.range 128).map fun index =>
    lit (operation (index%8) ((index/8)*stages+stage)).encode 105)
    (pack [cls,pass]) 7 105

def build (stages : Nat) : Except String Module := do
  -- Keep every elaborated k inside the reference's nonnegative signed int range.
  if stages == 0 || stages > 2^27 then throw "SE stages must be in 1..2^27"
  return runModule "otpu_se_microcode_sparkle" do
    let cls ← input "cls" 3
    let pass ← input "pass" 4
    output "n_ops" 32 (SeqWindow.select ((List.range 8).map fun c => lit (operationCount c)) cls 3 32)
    output "n_pass" 4 (SeqWindow.select ((List.range 8).map fun c => lit (passCount stages c) 4) cls 3 4)
    for s in [:stages] do
      output s!"uc{s}" 105 (rom stages s cls pass)
      output s!"use{s}" 16 (pack ((List.range 4).map fun f => lit (stageUse stages s f) 4))
      output s!"kv{s}" 1 (lit (if usesConstant stages s then 1 else 0) 1)

end OpenTPU.SeMicrocode
