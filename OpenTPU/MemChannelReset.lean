import OpenTPU.MemChannelSupport

namespace OpenTPU.MemChannelReset
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.MemChannelSupport

def build (c : Config) : Module := runModule "otpu_mem_channel_reset_sparkle" do
  setup ([("clk",1),("rst",1),("xclk",1),("xrst",1),("uclk",1),("urst",1),
    ("a_out",aow c),("x_out",xow c),("rm_busy",1),("rm_x",1),("a_oc",1),("x_oc",1)])
  sample "urq" 1 "uclk" (ref "urst") 1
  for (p,clock,reset,w) in [("a","clk","rst",aow c),("x","xclk","xrst",xow c)] do
    let q := fun suffix => ref s!"{p}_{suffix}"
    sample s!"{p}_rs1" 1 "uclk" (q "req")
    sample s!"{p}_rs2" 1 "uclk" (q "rs1")
    let resetting := bor (ref "urq") (q "rs2")
    sample s!"{p}_hcnt" 4 "uclk"
      (mux resetting (lit 15 4) (mux (nonzero (q "hcnt") 4) (sub (q "hcnt") (lit 1 4)) (q "hcnt")))
    let ownRmw := band (ref "rm_busy") (if p == "a" then bnot (ref "rm_x") else ref "rm_x")
    sample s!"{p}_hold" 1 "uclk" (bor resetting (band (q "hold")
      (any [nonzero (q "hcnt") 4,nonzero (q "out") w,ownRmw,q "oc"]))) 1
    sample s!"{p}_req" 1 clock (bor (ref reset) (band (q "req") (bnot (q "hs2"))))
    sample s!"{p}_hs1" 1 clock (q "hold") 1
    sample s!"{p}_hs2" 1 clock (q "hs1") 1
    sample s!"{p}_crst" 1 clock (any [ref reset,q "req",q "hs2"]) 1
  outputs [("urq",1),("a_hold",1),("x_hold",1),("a_hs2",1),("x_hs2",1),("a_crst",1),("x_crst",1)]

def hints : Backend.RegisterHints := [("urq",[.keep])] ++
  (["a_rs1","a_rs2","x_rs1","x_rs2","a_hs1","a_hs2","x_hs1","x_hs2"].map (fun n => (n,[.asyncRegister])))

end OpenTPU.MemChannelReset
