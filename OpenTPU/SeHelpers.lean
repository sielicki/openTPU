import OpenTPU.FloatConvert

/-! Native composite-function seed preparation, range reduction, and result
    fixups. All helpers retain the reference bit behavior outside normal domains. -/
namespace OpenTPU.SeHelpers
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

private def nz (x : Expr) (width : Nat) := bnot (eq x (lit 0 width))
private def extend (x : Expr) (extra : Nat) : Expr := .concat [lit 0 extra,x]
private def shr (x amount : Expr) := Expr.op .shr [x,amount]

/-- Composite state, least significant first: flags3, integer9, k2, k1, v. -/
def setup (stem : String) (cls value : Expr) : CircuitM Expr := do
  let x ← wire s!"{stem}_x" 32 (FloatConvert.ftz value)
  let ax := .concat [lit 0 1,slice x 0 31]
  let ge := bnot (lt (slice x 0 23) (lit 0x3504f3 23))
  let zero := eq (slice x 0 31) (lit 0 31)
  let rcp := eq cls (lit 3 3)
  let seed ← wire s!"{stem}_seed" 32 (sub (mux rcp (lit 0x7ef311c3) (lit 0x5f3759df))
    (mux rcp ax (shr x (lit 1))))
  let k2 := mux rcp (FloatConvert.ftz seed) seed
  let k1 := mux (eq cls (lit 5 3))
    (.concat [lit 0 1,mux ge (lit 126 8) (lit 127 8),slice x 0 23])
    (.concat [lit 1 1,slice ax 0 31])
  let integer ← wire s!"{stem}_integer" 9 (add (sub (extend (slice x 23 8) 1) (lit 127 9)) (extend ge 8))
  let infinity := eq x (lit 0x7f800000)
  let rcpFlags := pack [eq ax (lit 0),bnot (lt ax (lit 0x7e800000)),bit x 31]
  let rsqFlags := pack [bor (bit x 31) (bor zero infinity),lit 0 2]
  let logFlags := pack [zero,infinity,band (bnot zero) (bor (bit x 31) (FloatConvert.isNan x))]
  let flags := mux rcp rcpFlags (mux (eq cls (lit 4 3)) rsqFlags
    (mux (eq cls (lit 5 3)) logFlags (lit 0 3)))
  return pack [flags,integer,k2,k1,lit 0]

def rangeFloor (stem : String) (value : Expr) : CircuitM Expr := do
  let exponent := slice value 23 8
  let k ← wire s!"{stem}_k" 3 (sub exponent (lit 127 8))
  let amount ← wire s!"{stem}_shift" 3 (sub (lit 6 3) k)
  let ip ← wire s!"{stem}_ip" 7 (shr (.concat [lit 1 1,slice value 17 6]) amount)
  let fraction := nz (band (slice value 0 23) (shr (lit 0x7fffff 23) k)) 23
  let magnitude := add (extend ip 2) (extend fraction 8)
  let integer := mux (bit value 31) (sub (lit 0 9) magnitude) (extend ip 2)
  return mux (lt exponent (lit 127 8))
    (mux (band (bit value 31) (nz exponent 8)) (lit 511 9) (lit 0 9)) integer

def integerToFloat (stem : String) (value : Expr) : CircuitM Expr := do
  let negative := bit value 8
  let magnitude ← wire s!"{stem}_magnitude" 8 (mux negative (sub (lit 0 9) value) (slice value 0 8))
  let mut top := lit 0 3
  for j in [1:8] do
    top := mux (bit magnitude j) (lit j 3) top
  let p ← wire s!"{stem}_top" 3 top
  let shifted ← wire s!"{stem}_shifted" 31 (shr (.concat [magnitude,lit 0 23]) p)
  let exponent ← wire s!"{stem}_exponent" 8 (add (lit 127 8) (extend p 5))
  return mux (eq magnitude (lit 0 8)) (lit 0)
    (.concat [negative,exponent,slice shifted 0 23])

def finish (cls state : Expr) : Expr := Id.run do
  let value := slice state 76 32
  let integer := slice state 3 9
  let f0 := bit state 0
  let f1 := bit state 1
  let f2 := bit state 2
  let exp := mux f0 (lit 0) (mux f1 (lit 0x7f800000) (add value (.concat [integer,lit 0 23])))
  let rcp := mux f0 (lit 0) (mux f1 (.concat [f2,lit 0 31]) (mux f2 (FloatConvert.neg value) value))
  let rsq := mux f0 (lit 0) value
  let log := mux f0 (lit 0xff800000) (mux f2 (lit 0x7fc00000) (mux f1 (lit 0x7f800000) value))
  return mux (bor (eq cls (lit 1 3)) (eq cls (lit 2 3))) exp
    (mux (eq cls (lit 3 3)) rcp (mux (eq cls (lit 4 3)) rsq (mux (eq cls (lit 5 3)) log (lit 0))))

def build : Module := runModule "otpu_se_helpers_sparkle" do
  let cls ← input "cls" 3
  let value ← input "value" 32
  let state ← input "state" 108
  let integer ← input "int9" 9
  output "prepared" 108 (← setup "setup" cls value)
  output "floored" 9 (← rangeFloor "rr" value)
  output "converted" 32 (← integerToFloat "i9" integer)
  output "finished" 32 (finish cls state)

end OpenTPU.SeHelpers
