import OpenTPU.VpuDecode

namespace OpenTPU.VpuIssue
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

structure Config where
  lanes : Nat := 8
  compositeLanes : Nat := 8
  streams : Bool := true
  deriving Repr

def Config.comp8 (c : Config) := c.streams && c.lanes == 8
def Config.issueLanes (c : Config) := if c.comp8 then c.lanes else min c.compositeLanes c.lanes

def build (c : Config) : Except String Module := do
  if c.lanes == 0 || c.lanes > 256 || c.compositeLanes == 0 then
    throw "VPU issue requires 1..256 lanes and a positive composite lane count"
  return runModule "otpu_vpu_issue_sparkle" do
    for (name,width) in [("issuing",1),("filling",1),("od_sc",1),("od_one",1),("c_hold",1),
      ("func",8),("bmode",2),("ic",16),("ir",16),("ch",16),("nch",16),("rows",16),("cols",16),
      ("od_a",20),("oc_a",20),("a_row",20),("b_row",20),("b",20)] do
      let _ ← input name width
    let f := ref "func"
    let comp := lt (lit 1 4) (VpuDecode.slotCount f)
    let iwid ← wire "iwid" 16 (mux comp (lit c.issueLanes 16) (lit c.lanes 16))
    let ok := if c.comp8 then bnot (band comp (ref "c_hold")) else lit 1 1
    let last ← wire "last" 1 (eq (add (zext (ref "ch") 16 32) (lit 1)) (zext (ref "nch") 16 32))
    let rb := ([0,1,2,3,4,5,6,13,14,19] : List Nat).foldl
      (fun p code => bor p (eq f (lit code 8))) (lit 0 1)
    let rowMode := eq (ref "bmode") (lit 1 2)
    let colMode := eq (ref "bmode") (lit 2 2)
    let address := fun base l => VpuDecode.address (ref base) (ref "ic") (lit l)
    let mut ta := []
    let mut tb := []
    let mut ae := []
    let mut be := []
    let mut masks := []
    for l in [:c.lanes] do
      ta := ta ++ [mux (ref "filling")
        (mux (ref "od_sc") (zext (ref "od_a") 20 32) (address "od_a" l)) (address "a_row" l)]
      tb := tb ++ [mux (ref "filling") (address "oc_a" l)
        (mux colMode (address "b" l) (if l == 0 then mux rowMode (zext (ref "b_row") 20 32) (address "b_row" l) else address "b_row" l))]
      let inside := lt (add (zext (ref "ic") 16 32) (lit l)) (zext (ref "cols") 16 32)
      let mask ← wire s!"mask{l}" 1 (every [ref "issuing",bnot (ref "filling"),ok,inside,lt (lit l 16) iwid])
      masks := masks ++ [mask]
      let fill := every [ref "issuing",ref "filling",inside]
      ae := ae ++ [bor (every [fill,bnot (ref "od_one"),if l == 0 then lit 1 1 else bnot (ref "od_sc")])
        (band mask (bnot (eq f (lit 13 8))))]
      be := be ++ [bor fill (every [mask,rb,
        bor (bor (eq (ref "bmode") (lit 0 2)) colMode) (if l == 0 then rowMode else lit 0 1)])]
    output "ta_addr" (32*c.lanes) (pack ta)
    output "tb_addr" (32*c.lanes) (pack tb)
    output "ta_en" c.lanes (pack ae)
    output "tb_en" c.lanes (pack be)
    output "imask" c.lanes (pack masks)
    output "irow_last" 1 last
    output "iall_last" 1 (band last (eq (add (zext (ref "ir") 16 32) (lit 1)) (zext (ref "rows") 16 32)))
    output "iwid" 16 iwid
    output "iss_ok" 1 ok

end OpenTPU.VpuIssue
