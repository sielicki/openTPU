import OpenTPU.BoardFifo
import OpenTPU.SeqWindow

namespace OpenTPU.AsyncFifo
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  width : Nat := 32
  depth : Nat := 16
  outOfOrder : Bool := false
  registeredReady : Bool := false
  deriving Repr

private def register (name : String) (width : Nat) (clock reset : String)
    (value : Expr) : CircuitM Unit := do
  let m ← getModule
  setModule <| (m.addWire {name,ty := .bitVector width}).addStmt
    (.register name clock (reset,.synchronous) value 0)

def build (c : Config) : Except String Module := do
  if c.width == 0 || c.depth < 4 || !powerOfTwo c.depth then
    throw "Asynchronous FIFO requires positive width and power-of-two depth >= 4"
  let aw := clog2 c.depth
  let pw := aw+1
  return runModule "otpu_afifo_sparkle" do
    for (n,w) in [("wclk",1),("wrst",1),("wvalid",1),("wdata",c.width),("wslot",aw),
      ("rclk",1),("rrst",1),("rready",1)] do let _ ← input n w
    -- This named constant is needed as a register reset connection.
    let m ← getModule
    setModule <| (m.addWire {name := "no_reset",ty := .bitVector 1}).addStmt (.assign "no_reset" (lit 0 1))
    let mut binary := []
    for i in [:pw] do
      let value := (List.range (pw-i)).foldl (fun q j => Expr.xor q (bit (ref "rgray_w2") (i+j))) (lit 0 1)
      binary := binary ++ [value]
    let used := slice (sub (ref "wbin") (pack binary)) 0 pw
    let ready := if c.registeredReady then ref "wrdy" else band (bnot (ref "wrst")) (bnot (eq used (lit c.depth pw)))
    let put := band (ref "wvalid") (if c.outOfOrder then bnot (ref "wrst") else ready)
    let advance := if c.outOfOrder then band (bnot (ref "wrst"))
      (SeqWindow.select ((List.range c.depth).map fun i => bit (ref "wvld") i) (slice (ref "wbin") 0 aw) aw 1)
      else put
    let wa := if c.outOfOrder then ref "wslot" else if c.registeredReady then ref "wa_q" else slice (ref "wbin") 0 aw
    let nextW := slice (add (ref "wbin") (lit 1 pw)) 0 pw
    let gray := fun value => Expr.xor value (.op .shr [value,lit 1 pw])
    if c.registeredReady then
      register "wrdy" 1 "wclk" "no_reset" (band (bnot (ref "wrst"))
        (bnot (eq (slice (add used (mux put (lit 1 pw) (lit 0 pw))) 0 pw) (lit c.depth pw))))
      register "wa_q" aw "wclk" "wrst" (mux advance (slice nextW 0 aw) (ref "wa_q"))
    register "wbin" pw "wclk" "wrst" (mux advance nextW (ref "wbin"))
    register "wgray" pw "wclk" "wrst" (mux advance (gray nextW) (ref "wgray"))
    register "rgray_w1" pw "wclk" "wrst" (ref "rgray")
    register "rgray_w2" pw "wclk" "wrst" (ref "rgray_w1")
    if c.outOfOrder then
      let flags := (List.range c.depth).map fun i =>
        mux (band advance (eq (slice (ref "wbin") 0 aw) (lit i aw))) (lit 0 1)
          (mux (band put (eq (ref "wslot") (lit i aw))) (lit 1 1) (bit (ref "wvld") i))
      register "wvld" c.depth "wclk" "wrst" (pack flags)
    let valid := band (bnot (ref "rrst")) (bnot (eq (ref "rgray") (ref "wgray_r2")))
    let pop := band valid (ref "rready")
    let nextR := slice (add (ref "rbin") (lit 1 pw)) 0 pw
    register "rbin" pw "rclk" "rrst" (mux pop nextR (ref "rbin"))
    register "rgray" pw "rclk" "rrst" (mux pop (gray nextR) (ref "rgray"))
    register "wgray_r1" pw "rclk" "rrst" (ref "wgray")
    register "wgray_r2" pw "rclk" "rrst" (ref "wgray_r1")
    let m ← getModule
    setModule <| (m.addWire {name := "read_data",ty := .bitVector c.width}).addStmt
      (.memory "mem" aw c.width "wclk" wa (ref "wdata") put (slice (ref "rbin") 0 aw) "read_data" true)
    output "wready" 1 ready
    output "wcommit" 1 (if c.outOfOrder then advance else lit 0 1)
    output "wused" pw used
    output "rvalid" 1 valid
    output "rdata" c.width (ref "read_data")

/-- Preserve the reference's synchronizer chains, RAM style and write-address fanout. -/
def toVerilog (c : Config) : Except String String := do
  let hints : Backend.RegisterHints :=
    (["rgray_w1","rgray_w2","wgray_r1","wgray_r2"].map (fun n => (n,[.asyncRegister]))) ++
    (if c.registeredReady then [("wa_q",[.maxFanout 32])] else [])
  Backend.withRegisterHints (← build c) hints false false [("mem",.distributed)]

end OpenTPU.AsyncFifo
