import OpenTPU.Circuit
import OpenTPU.Backend

namespace OpenTPU.BoardFifo
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

/-- Registered-ready skid buffer, including unreset data sampling during reset. -/
def skid (width : Nat) : Except String Module := do
  if width == 0 then throw "skid buffer width must be positive"
  return runModule "otpu_skid_sparkle" do
    clocks
    let _ ← input "s_valid" 1
    let _ ← input "s_data" width
    let _ ← input "m_ready" 1
    let adv ← wire "adv" 1 (bor (ref "m_ready") (bnot (ref "mv")))
    let take ← wire "take" 1 (band (ref "s_valid") (ref "sr"))
    reg "mv" 1 true [(adv,bor (ref "sk_v") take)]
    reg "sk_v" 1 true [(take,lit 1 1),(adv,lit 0 1)]
    reg "sr" 1 true [(lit 1 1,mux adv (lit 1 1) (mux take (lit 0 1) (bnot (ref "sk_v"))))]
    let _ ← clocked "md" width adv (mux (ref "sk_v") (ref "sk_d") (ref "s_data"))
    let _ ← clocked "sk_d" width (bnot (ref "sk_v")) (ref "s_data")
    output "s_ready" 1 (ref "sr")
    output "m_valid" 1 (ref "mv")
    output "m_data" width (ref "md")

structure Config where
  width : Nat := 8
  depth : Nat := 16
  registeredOutput : Bool := false
  deriving Repr

/-- Synchronous distributed-memory FIFO, with optional registered flags/head. -/
def fifo (c : Config) : Except String Module := do
  if c.width == 0 || c.depth < 2 || !powerOfTwo c.depth then
    throw "FIFO requires positive width and a power-of-two depth >= 2"
  return runModule "otpu_sfifo_sparkle" do
    clocks
    for (n,w) in [("wvalid",1),("wdata",c.width),("rready",1)] do
      let _ ← input n w
    let aw := clog2 c.depth
    let count := slice (sub (ref "wp") (ref "rp")) 0 (aw+1)
    let wr ← wire "write_ready" 1 (if c.registeredOutput then ref "wr" else bnot (eq count (lit c.depth (aw+1))))
    let rv ← wire "read_valid" 1 (if c.registeredOutput then ref "rv" else bnot (eq (ref "wp") (ref "rp")))
    let push ← wire "push" 1 (band (ref "wvalid") wr)
    let pop ← wire "pop" 1 (band rv (ref "rready"))
    let wpNext ← wire "wp_next" (aw+1) (add (ref "wp") (mux push (lit 1 (aw+1)) (lit 0 (aw+1))))
    let rpNext ← wire "rp_next" (aw+1) (add (ref "rp") (mux pop (lit 1 (aw+1)) (lit 0 (aw+1))))
    reg "wp" (aw+1) true [(push,wpNext)]
    reg "rp" (aw+1) true [(pop,rpNext)]
    let readAddress := if c.registeredOutput then slice (add (ref "rp") (lit 1 (aw+1))) 0 aw else slice (ref "rp") 0 aw
    let m ← getModule
    setModule <| (m.addWire {name := "read_data",ty := .bitVector c.width}).addStmt
      (.memory "mem" aw c.width "clk" (slice (ref "wp") 0 aw) (ref "wdata") push readAddress "read_data" true)
    if c.registeredOutput then
      let _ ← clocked "head" c.width (bor pop (bnot rv))
        (mux pop (mux (eq count (lit 1 (aw+1))) (ref "wdata") (ref "read_data")) (ref "wdata"))
      reg "rv" 1 true [(lit 1 1,bnot (eq wpNext rpNext))]
      reg "wr" 1 true [(lit 1 1,bnot (eq (slice (sub wpNext rpNext) 0 (aw+1)) (lit c.depth (aw+1))))] 1
    output "wready" 1 wr
    output "rvalid" 1 rv
    output "rdata" c.width (ref (if c.registeredOutput then "head" else "read_data"))

def fifoVerilog (c : Config) : Except String String := do
  Backend.withRegisterHints (← fifo c) [] false false [("mem",.distributed)]

end OpenTPU.BoardFifo
