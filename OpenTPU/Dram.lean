import OpenTPU.Circuit

/-! Behavioral DRAM's synthesizable state machine, expressed using native
multiport byte memories. Port order is poke, A, SW, then increasing B word.
Every read samples old memory on every edge, independently of request valid. -/
namespace OpenTPU.Dram
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit
structure Config where
  words : Nat := 262144
  depth : Nat := 32
  latency : Nat := 8
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  if !powerOfTwo c.words || c.words < 2 || clog2 c.words > 32 then
    throw "DRAM: WORDS must be a power of two in 2..2^32"
  if c.depth < 4 || c.depth % 4 != 0 then throw "DRAM: D must be a positive multiple of four"
  if c.latency == 0 then throw "DRAM: LAT must be positive"

def build (c : Config) : Module := runModule "otpu_dram_sparkle" do
  clockOnly
  for (n,w) in [("a_req",1),("a_we",1),("a_addr",32),("a_wdata",32),("a_be",4),
      ("sw_req",1),("sw_addr",32),("sw_wdata",32),("sw_be",4),
      ("b_req",1),("b_tag",1),("b_we",1),("b_wmask",c.depth/4),
      ("b_wdata",c.depth*8),("b_addr",32),
      ("poke_valid",1),("poke_addr",32),("poke_data",32)] do
    let _ ← input n w
  let aw := clog2 c.words
  let cw := c.depth/4
  let aa := slice (ref "a_addr") 0 aw
  let ba := fun w => slice (add (ref "b_addr") (lit w 32)) 0 aw
  for b in [:4] do
    let extra := [(aa, slice (ref "a_wdata") (8*b) 8,
        band (band (ref "a_req") (ref "a_we")) (bit (ref "a_be") b)),
      (slice (ref "sw_addr") 0 aw, slice (ref "sw_wdata") (8*b) 8,
        band (ref "sw_req") (bit (ref "sw_be") b))] ++
      (List.range cw).map (fun w => (ba w, slice (ref "b_wdata") (32*w+8*b) 8,
        band (band (ref "b_req") (ref "b_we")) (bit (ref "b_wmask") w)))
    let reads := [(Expr.op .xor [aa,lit 1 aw], s!"ar2_{b}")] ++
      (List.range cw).map (fun w => (ba w,s!"br{w}_{b}"))
    let mut m ← getModule
    for n in s!"ar_{b}" :: reads.map (·.2) do
      m := m.addWire {name := n, ty := .bitVector 8}
    setModule <| m.addStmt (.memory s!"mem{b}" aw 8 "clk"
      (slice (ref "poke_addr") 0 aw) (slice (ref "poke_data") (8*b) 8)
      (ref "poke_valid") aa s!"ar_{b}" true extra reads)
  let mut av := band (ref "a_req") (bnot (ref "a_we"))
  let mut bv := band (ref "b_req") (bnot (ref "b_we"))
  let mut bt := ref "b_tag"
  let mut ad := pack ((List.range 4).map fun b => ref s!"ar_{b}")
  let mut ad2 := pack ((List.range 4).map fun b => ref s!"ar2_{b}")
  let mut bd := pack ((List.range cw).flatMap fun w => (List.range 4).map fun b => ref s!"br{w}_{b}")
  for k in [:c.latency] do
    av ← clocked s!"av{k}" 1 (lit 1 1) av
    bv ← clocked s!"bv{k}" 1 (lit 1 1) bv
    bt ← clocked s!"bt{k}" 1 (lit 1 1) bt
    ad ← clocked s!"ad{k}" 32 (lit 1 1) ad
    ad2 ← clocked s!"ad2_{k}" 32 (lit 1 1) ad2
    bd ← clocked s!"bd{k}" (c.depth*8) (lit 1 1) bd
  for (n,w,e) in [("a_rvalid",1,av),("a_rdata",32,ad),("a_rdata2",32,ad2),
      ("b_rvalid",1,bv),("b_rtag",1,bt),("b_rdata",c.depth*8,bd)] do output n w e
end OpenTPU.Dram
