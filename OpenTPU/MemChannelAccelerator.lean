import OpenTPU.MemChannelSupport

namespace OpenTPU.MemChannelAccelerator
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.MemChannelSupport

def build : Module := runModule "otpu_mem_channel_accelerator_sparkle" do
  setup [("clk",1),("a_crst",1),("n_cvalid",1),("n_cwe",1),("n_caddr",25),
    ("n_wvalid",1),("n_wdata",512),("n_wmask",64),("aq_wr",1),("ad_wr",1),
    ("ar_rv",1),("ar_rd",512),("a_wacc_g",16),("c_err",1)]
  signal "n_cready" 1 (band (bnot (ref "a_crst")) (ref "aq_wr"))
  signal "aq_wv" 1 (band (ref "n_cvalid") (ref "n_cready"))
  signal "aq_wd" 26 (pack [ref "n_caddr",ref "n_cwe"])
  signal "n_wready" 1 (band (bnot (ref "a_crst")) (ref "ad_wr"))
  signal "ad_wv" 1 (band (ref "n_wvalid") (ref "n_wready"))
  signal "ad_wd" 577 (pack [ref "n_wdata",ref "n_wmask",bnot (eq (ref "n_wmask") (lit (2^64-1) 64))])
  signal "ar_rr" 1 (lit 1 1)
  sample "n_rvalid" 1 "clk" (band (ref "ar_rv") (bnot (ref "a_crst")))
  sample "n_rdata" 512 "clk" (ref "ar_rd")
  for (n,v) in [("a_wacc_s1",ref "a_wacc_g"),("a_wacc_s2",ref "a_wacc_s1"),("n_wdone",binary (ref "a_wacc_s2") 16)] do
    register n 16 "clk" "a_crst" [(lit 1 1,v)]
  sample "e_s1" 1 "clk" (ref "c_err")
  sample "e_s2" 1 "clk" (ref "e_s1")
  signal "n_err" 1 (ref "e_s2")
  outputs [("n_cready",1),("aq_wv",1),("aq_wd",26),("n_wready",1),("ad_wv",1),("ad_wd",577),
    ("ar_rr",1),("n_rvalid",1),("n_rdata",512),("n_wdone",16),("n_err",1)]

def hints : Backend.RegisterHints :=
  ["a_wacc_s1","a_wacc_s2","e_s1","e_s2"].map (fun n => (n,[.asyncRegister]))

end OpenTPU.MemChannelAccelerator
