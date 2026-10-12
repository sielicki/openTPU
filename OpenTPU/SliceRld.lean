import OpenTPU.Circuit

namespace OpenTPU.SliceRld
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

/-- ISA RLD conversion: truncate toward zero, with the original overflow sentinel. -/
def convert (x : Expr) : CircuitM Expr := do
  let e := slice x 23 8
  let m := pack [slice x 0 23,lit 1 9]
  let value ← wire "rld_magnitude" 32 (mux (bnot (lt e (lit 150 8)))
    (.op .shl [m,sub e (lit 150 8)]) (.op .shr [m,sub (lit 150 8) e]))
  return mux (lt e (lit 127 8)) (lit 0)
    (mux (bnot (lt e (lit 158 8))) (lit 0x80000000)
      (mux (bit x 31) (sub (lit 0) value) value))

/-- Collective request retention and the slice's local register-load pipeline. -/
def build : Module := runModule "otpu_slice_rld_sparkle" do
  clocks
  let start ← input "start" 1
  let cmd ← input "cmd" 240
  let ack ← input "coll_ack" 1
  let ren ← input "read_enable" 1
  let data ← input "read_data" 32
  let launch ← wire "rl_start" 1 (band start (eq (slice cmd 232 8) (lit 6 8)))
  reg "coll_req" 1 true [(ack,lit 0 1),(band start (bnot launch),lit 1 1)]
  let take ← wire "rl_take" 1 (band (ref "rl_pend") ren)
  reg "rl_pend" 1 true [(take,lit 0 1),(launch,lit 1 1)]
  for (n,value) in [("rl_got",take),("rl_cv",ref "rl_got"),
      ("rl_c1",ref "rl_cv"),("rl_c2",ref "rl_c1"),("rl_v",ref "rl_c2")] do
    reg n 1 true [(lit 1 1,value)]
  reg "rl_a" 32 false [(launch,slice cmd 192 32)]
  reg "rl_raw" 1 false [(launch,bit cmd 224)]
  reg "rl_m" 32 false [(launch,mux (bit cmd 225) (slice cmd 160 32) (lit 1))]
  reg "rl_w" 32 false [(ref "rl_got",data)]
  let converted ← convert (ref "rl_w")
  reg "rl_x" 32 false [(ref "rl_cv",mux (ref "rl_raw") (ref "rl_w") converted)]
  reg "rl_pl" 32 false [(ref "rl_c1",.mul (ref "rl_x") (pack [slice (ref "rl_m") 0 16,lit 0 16]))]
  reg "rl_ph" 16 false [(ref "rl_c1",.mul (slice (ref "rl_x") 0 16) (slice (ref "rl_m") 16 16))]
  reg "rl_val" 32 false [(ref "rl_c2",add (ref "rl_pl") (pack [lit 0 16,ref "rl_ph"]))]
  let busy := ["rl_pend","rl_got","rl_cv","rl_c1","rl_c2","rl_v"].foldl
    (fun a n => bor a (ref n)) (lit 0 1)
  for (n,w) in [("coll_req",1),("rl_pend",1),("rl_a",32),("rl_v",1),("rl_val",32)] do
    output s!"o_{n}" w (ref n)
  output "o_rl_busy" 1 busy
  output "o_coll_cmd" 240 cmd

def toVerilog : String := Sparkle.Backend.Verilog.toVerilog build

end OpenTPU.SliceRld
