import OpenTPU.Circuit

namespace OpenTPU.SliceArbiter
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  lanes : Nat := 8
  readsPerBank : Nat := 4
  writesPerBank : Nat := 2
  deriving Repr

private def reads : List (List Nat) := [[1],[7],[3,4],[0],[2,6,5]]
private def writes : List (List Nat) := [[0],[2],[3],[1],[]]
private def any (xs : List Expr) := xs.foldl bor (lit 0 1)
private def all (xs : List Expr) := xs.foldl band (lit 1 1)

def build (c : Config) : Except String Module := do
  if c.lanes < 2 || !powerOfTwo c.lanes || c.lanes > 128 then
    throw "slice arbiter requires power-of-two LANES in 2..128"
  if c.readsPerBank == 0 || c.writesPerBank == 0 ||
      c.readsPerBank >= 2^31 || c.writesPerBank >= 2^31 then
    throw "slice arbiter requires positive signed-int bank capacities"
  return runModule "otpu_slice_arbiter_sparkle" do
    let l := c.lanes
    let rq ← input "rq_en" (8*l)
    let ra ← input "r_addr" (8*l*32)
    let wq ← input "wq_en" (4*l)
    let wa ← input "w_addr" (4*l*32)
    let want ← input "q_awant" 1
    let ready ← input "sw_rdy" 1
    let global ← input "coll_gnt" 1
    let vren ← input "v_ren" 1
    let req := fun p => bnot (eq (slice rq (p*l) l) (lit 0 l))
    let qblock := band (req 5) (req 1)
    let cblock := band (req 7) (bor (req 1) (req 5))
    let allowed := fun g => if g == 4 then bnot (bor qblock (band want (bnot ready)))
      else if g == 1 then bnot cblock else lit 1 1
    let hits := fun (en addr : Expr) (ports : List Nat) (bank : Nat) =>
      ports.flatMap fun p => (List.range l).map fun lane =>
        band (bit en (p*l+lane)) (eq (slice addr ((p*l+lane)*32) (clog2 l)) (lit bank (clog2 l)))
    let mut grants : List Expr := []
    let mut localGrant := lit 1 1
    if c.readsPerBank >= 8*l && c.writesPerBank == 1 then
      let mut masks : List Expr := []
      for g in List.range 5 do
        let m ← wire s!"mask{g}" l (pack ((List.range l).map fun b => any (hits wq wa writes[g]! b)))
        masks := masks ++ [m]
      let mut admitted : List Expr := []
      for g in List.range 5 do
        let conflicts := (List.range g).map fun h =>
          band admitted[h]! (bnot (eq (band masks[g]! masks[h]!) (lit 0 l)))
        let ok ← wire s!"ok{g}" 1 (band (allowed g) (bnot (any conflicts)))
        admitted := admitted ++ [ok]
        if g == 1 then localGrant := ok
        grants := grants ++ [if g == 1 then global else ok]
    else
      let mut rc := List.replicate l (lit 0 32)
      let mut wc := List.replicate l (lit 0 32)
      for g in List.range 5 do
        let mut nextR : List Expr := []
        let mut nextW : List Expr := []
        for b in List.range l do
          let count := fun xs => xs.foldl (fun a e => add a (pack [e,lit 0 31])) (lit 0 32)
          let r ← wire s!"readCount{g}_{b}" 32 (add rc[b]! (count (hits rq ra reads[g]! b)))
          let w ← wire s!"writeCount{g}_{b}" 32 (add wc[b]! (count (hits wq wa writes[g]! b)))
          nextR := nextR ++ [r]
          nextW := nextW ++ [w]
        let fits := (List.range l).map fun b => band
          (bnot (lt (lit c.readsPerBank) nextR[b]!)) (bnot (lt (lit c.writesPerBank) nextW[b]!))
        let ok ← wire s!"ok{g}" 1 (band (allowed g) (all fits))
        if g == 1 then localGrant := ok
        grants := grants ++ [if g == 1 then global else ok]
        for b in List.range l do
          rc := rc.set b (← wire s!"usedR{g}_{b}" 32 (mux ok nextR[b]! rc[b]!))
          wc := wc.set b (← wire s!"usedW{g}_{b}" 32 (mux ok nextW[b]! wc[b]!))
    output "gnt" 5 (pack grants)
    output "coll_gnt_local" 1 localGrant
    let rg := [grants[3]!,lit 1 1,grants[4]!,vren,vren,grants[4]!,grants[4]!,grants[1]!]
    let wg := [lit 1 1,grants[3]!,grants[1]!,grants[2]!]
    output "r_en" (8*l) (pack ((List.range 8).map fun p => mux rg[p]! (slice rq (p*l) l) (lit 0 l)))
    output "w_en" (4*l) (pack ((List.range 4).map fun p => mux wg[p]! (slice wq (p*l) l) (lit 0 l)))
    output "w_gnt" 4 (pack wg)

def toVerilog (c : Config) : Except String String := do
  return Sparkle.Backend.Verilog.toVerilog (← build c)

end OpenTPU.SliceArbiter
