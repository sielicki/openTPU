import OpenTPU.SeqWindow
import OpenTPU.SeqLogic

/-! Native VPU function decoder and wrapped TMEM addressing. All 256 function
    encodings retain the reference defaults, including undefined ISA opcodes. -/
namespace OpenTPU.VpuDecode
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

def slots (f : Nat) : Nat :=
  if [0,1,2,3,6].contains f then 1 else if f == 9 || f == 14 then 9
  else if f == 10 then 6 else if f == 11 || f == 15 then 10 else 0

def reduction (f : Nat) : Bool := [16,17,18,19,20].contains f

def classOf (f : Nat) : Nat :=
  if [0,1,2,3,6].contains f then 1 else if f == 9 || f == 14 then 2
  else if f == 10 then 3 else if f == 11 then 4 else if f == 15 then 5 else 0

def compositeClass (f : Nat) : Nat :=
  if f == 9 then 1 else if f == 14 then 2 else if f == 10 then 3
  else if f == 11 then 4 else if f == 15 then 5 else 0

def classFunction (c : Nat) : Nat := (#[8,0,9,10,11,15,8,8] : Array Nat)[c%8]!

def decodeValue (f : Nat) : Nat :=
  classOf f ||| (compositeClass f <<< 3) ||| ((if slots f > 1 then 1 else 0) <<< 6) |||
  ((if !reduction f && slots f == 0 then 1 else 0) <<< 7) |||
  ((if f < 20 then 1 <<< f else 0) <<< 8)

private def table (width : Nat) (values : Nat → Nat) (f : Expr) : Expr :=
  SeqWindow.select ((List.range 256).map fun i => lit (values i) width) f 8 width

def decode (f : Expr) : Expr := table 28 decodeValue f
def slotCount (f : Expr) : Expr := table 4 slots f
def isReduction (f : Expr) : Expr := table 1 (fun f => if reduction f then 1 else 0) f

def address (base column lane : Expr) : Expr :=
  zext (slice (add (add (zext base 20 32) (zext column 16 32)) lane) 0 20) 20 32

def build : Module := runModule "otpu_vpu_decode_sparkle" do
  let f ← input "func" 8
  let cls ← input "cls" 3
  let base ← input "base" 20
  let column ← input "column" 16
  let lane ← input "lane" 32
  output "decoded" 28 (decode f)
  output "slots" 4 (slotCount f)
  output "reduction" 1 (isReduction f)
  output "class_function" 8 (SeqWindow.select ((List.range 8).map fun c => lit (classFunction c) 8) cls 3 8)
  output "address" 32 (address base column lane)

end OpenTPU.VpuDecode
