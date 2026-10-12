import OpenTPU.Circuit

/-! Native combinational binary32 ordering, integer conversion and signed-byte
    quantization. The conversion stage interfaces retain every original bit,
    allowing independent unrestricted proofs of both stages. -/
namespace OpenTPU.FloatConvert
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

private def nz (x : Expr) (w : Nat := 32) := bnot (eq x (lit 0 w))
private def zext (x : Expr) (extra : Nat) := Expr.concat [lit 0 extra, x]
private def exponent (x : Expr) := slice x 23 8
private def negative (x : Expr) := bit x 31
private def shl (x k : Expr) := Expr.op .shl [x,k]
private def shr (x k : Expr) := Expr.op .shr [x,k]

def ftz (x : Expr) : Expr :=
  mux (eq (exponent x) (lit 0 8)) (.concat [negative x, lit 0 31]) x

def neg (x : Expr) : Expr := .concat [bnot (negative x), slice x 0 31]
def abs (x : Expr) : Expr := .concat [lit 0 1, slice (ftz x) 0 31]
def isNan (x : Expr) : Expr := band (eq (exponent x) (lit 255 8)) (nz (slice x 0 23) 23)
private def rawKey (x : Expr) : Expr := mux (negative x) (bnot x) (.concat [lit 1 1, slice x 0 31])
def key (x : Expr) : Expr := rawKey (ftz x)

def greater (a b : Expr) : Expr :=
  let za := eq (exponent a) (lit 0 8)
  let zb := eq (exponent b) (lit 0 8)
  mux za (mux zb (band (bnot (negative a)) (negative b)) (negative b))
    (mux zb (bnot (negative a)) (lt (rawKey b) (rawKey a)))

def max (a b : Expr) : Expr := mux (greater a b) (ftz a) (ftz b)
def min (a b : Expr) : Expr := mux (greater b a) (ftz a) (ftz b)
def minMax (a b mn : Expr) : Expr := mux (.xor (greater a b) mn) (ftz a) (ftz b)

def leadingZeros (stem : String) (value : Expr) : CircuitM Expr := do
  let mut x := value
  let mut bits := []
  for k in [16,8,4,2,1] do
    let empty ← wire s!"{stem}_zero{k}" 1 (eq (slice x (32-k) k) (lit 0 k))
    bits := bits ++ [empty]
    x ← wire s!"{stem}_shift{k}" 32 (mux empty (shl x (lit k)) x)
  return mux (eq value (lit 0)) (lit 32 6) (.concat [lit 0 1, .concat bits])

def stickyBelow (x k : Expr) : Expr := nz (band x (bnot (shl (lit 0xffffffff) k)))

/-- Packed fields, least significant first: magnitude32, leadingZeros6, sign1, zero1. -/
def integerStage1 (stem : String) (x : Expr) : CircuitM Expr := do
  let mag ← wire s!"{stem}_mag" 32 (mux (negative x) (add (bnot x) (lit 1)) x)
  let lz ← leadingZeros stem mag
  return pack [mag, lz, negative x, eq x (lit 0)]

def integerStage2 (stem : String) (m : Expr) : CircuitM Expr := do
  let lz := slice m 32 6
  let nrm ← wire s!"{stem}_normal" 32 (shl (slice m 0 32) lz)
  let e ← wire s!"{stem}_exponent" 9 (sub (lit 158 9) (zext lz 3))
  let mm := slice nrm 8 24
  let round := band (bit nrm 7) (bor (nz (slice nrm 0 7) 7) (bit mm 0))
  let mr ← wire s!"{stem}_rounded" 25 (add (zext mm 1) (zext round 24))
  let carry := bit mr 24
  let exp ← wire s!"{stem}_exp_rounded" 9 (add e (zext carry 8))
  let fraction := mux carry (slice mr 1 23) (slice mr 0 23)
  return mux (bit m 39) (lit 0) (.concat [bit m 38, slice exp 0 8, fraction])

/-- Packed fields, least significant first: sticky1, guard1, integer32, sign1,
    saturated1, zero1. -/
def quantizeStage1 (stem : String) (value : Expr) : CircuitM Expr := do
  let x ← wire s!"{stem}_flushed" 32 (ftz value)
  let e := exponent x
  let zero := lt e (lit 126 8)
  let sat := bnot (lt e (lit 134 8))
  let m ← wire s!"{stem}_mantissa" 32 (.concat [lit 0 8, lit 1 1, slice x 0 23])
  let sh ← wire s!"{stem}_amount" 6 (mux (bor zero sat) (lit 17 6) (sub (lit 150 8) e))
  let ip ← wire s!"{stem}_integer" 32 (shr m sh)
  let below ← wire s!"{stem}_below" 6 (sub sh (lit 1 6))
  let guard ← wire s!"{stem}_guard" 32 (shr m below)
  return pack [stickyBelow m below, bit guard 0, ip, negative x, sat, zero]

def quantizeStage2 (stem : String) (q : Expr) : CircuitM Expr := do
  let ip := slice q 2 32
  let round := band (bit q 1) (bor (bit q 0) (bit ip 0))
  let rounded ← wire s!"{stem}_rounded" 32 (add ip (zext round 31))
  let bounded ← wire s!"{stem}_bounded" 32 (mux (lt (lit 127) rounded) (lit 127) rounded)
  let signed ← wire s!"{stem}_signed" 32 (mux (bit q 34) (sub (lit 0) bounded) bounded)
  return mux (bit q 36) (lit 0 8)
    (mux (bit q 35) (mux (bit q 34) (lit 0x81 8) (lit 0x7f 8)) (slice signed 0 8))

/-- The hardware's floor helper. Its intended arithmetic domain is [-126,128),
    but the implementation also preserves the original bit behavior outside it. -/
def floor (stem : String) (value : Expr) : CircuitM Expr := do
  let x ← wire s!"{stem}_flushed" 32 (ftz value)
  let e := exponent x
  let m := .concat [lit 0 8, lit 1 1, slice x 0 23]
  let sh ← wire s!"{stem}_amount" 32 (sub (lit 150) (zext e 24))
  let ip ← wire s!"{stem}_integer" 32 (shr m sh)
  let frac := stickyBelow m (slice sh 0 6)
  let signed := mux (negative x) (sub (lit 0) (add ip (zext frac 31))) ip
  return mux (eq (slice x 0 31) (lit 0 31)) (lit 0)
    (mux (lt e (lit 127 8)) (mux (negative x) (lit 0xffffffff) (lit 0)) signed)

/-- Standalone unrestricted stage interfaces for the differential/formal harness. -/
def build : Module := runModule "otpu_float_convert_sparkle" do
  let a ← input "a" 32
  let b ← input "b" 32
  let mn ← input "mn" 1
  let im ← input "im" 40
  let qm ← input "qm" 37
  let k ← input "k" 6
  output "flushed" 32 (ftz a)
  output "negated" 32 (neg a)
  output "absolute" 32 (abs a)
  output "nan" 1 (isNan a)
  output "ordered_key" 32 (key a)
  output "gt" 1 (greater a b)
  output "maximum" 32 (max a b)
  output "minimum" 32 (min a b)
  output "mm" 32 (minMax a b mn)
  output "lz" 6 (← leadingZeros "lzc" a)
  output "sticky" 1 (stickyBelow a k)
  output "i_s1" 40 (← integerStage1 "i1" a)
  output "i_s2" 32 (← integerStage2 "i2" im)
  output "q_s1" 37 (← quantizeStage1 "q1" a)
  output "q_s2" 8 (← quantizeStage2 "q2" qm)
  output "floored" 32 (← floor "floor" a)

end OpenTPU.FloatConvert
