import OpenTPU.MemChannelSupport

namespace OpenTPU.MemChannelController
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.MemChannelSupport

/-- Arbitration, credits, RMW and port registers. Every FIFO boundary is explicit. -/
def build (c : Config) : Module := runModule "otpu_mem_channel_controller_sparkle" do
  setup [("uclk",1),("urq",1),("a_hold",1),("x_hold",1),
    ("aq_rv",1),("aq_rd",26),("ad_rv",1),("ad_rd",577),
    ("xq_rv",1),("xq_rd",26),("xd_rv",1),("xd_rd",577),
    ("ar_used",aow c),("xr_used",xow c),("ar_cmt",1),("xr_cmt",1),
    ("oq_wr",2),("oq_rv",2),("oq_rd",54),("of_wr",2),("tg_wr",2),("tg_rv",2),("tg_rd",2*tw c),
    ("c_cmd_ready",2),("c_rdata_valid",2),("c_rdata_data",1024)]
  for (p,width,depth,used) in [("a",aow c,c.acceleratorDepth,"ar_used"),("x",xow c,c.xdmaDepth,"xr_used")] do
    sample s!"{p}_rok" 1 "uclk" (bnot (lt (lit (depth-2) width)
      (truncAdd (ref s!"{p}_pend") (ref used) width)))
  for (p,head,dat) in [("a","aq","ad"),("x","xq","xd")] do
    signal s!"{p}_ok" 1 (band (ref s!"{head}_rv")
      (mux (bit (ref s!"{head}_rd") 25) (ref s!"{dat}_rv") (ref s!"{p}_rok")))
    let port := bit (ref s!"{head}_rd") 7
    signal s!"{p}_room" 1 (band (choose2 (ref "oq_wr") 1 port)
      (bor (bnot (bit (ref s!"{head}_rd") 25)) (choose2 (ref "of_wr") 1 port)))
  signal "pick_x" 1 (mux (ref "cur_x")
    (bor (bnot (ref "a_ok")) (band (ref "x_ok") (lt (ref "run") (lit c.runLength 6))))
    (band (ref "x_ok") (bor (bnot (ref "a_ok")) (bnot (lt (ref "run") (lit c.runLength 6))))))
  signal "sel_x" 1 (mux (ref "rm_busy") (ref "rm_x") (ref "pick_x"))
  signal "we" 1 (mux (ref "sel_x") (bit (ref "xq_rd") 25) (bit (ref "aq_rd") 25))
  signal "addr" 25 (mux (ref "sel_x") (slice (ref "xq_rd") 0 25) (slice (ref "aq_rd") 0 25))
  signal "wd" 577 (mux (ref "sel_x") (ref "xd_rd") (ref "ad_rd"))
  signal "tp" 1 (bit (ref "addr") 7)
  signal "part" 1 (band (ref "we") (bit (ref "wd") 576))
  signal "rmw" 1 (ref "part")
  signal "go" 1 (band (bnot (ref "rm_busy")) (mux (ref "pick_x")
    (band (ref "x_ok") (ref "x_room")) (band (ref "a_ok") (ref "a_room"))))
  signal "a_rgo" 1 (all [bnot (ref "rm_busy"),bnot (ref "pick_x"),ref "a_ok",ref "a_room",bnot (bit (ref "aq_rd") 25)])
  signal "x_rgo" 1 (all [bnot (ref "rm_busy"),ref "pick_x",ref "x_ok",ref "x_room",bnot (bit (ref "xq_rd") 25)])
  signal "rv" 1 (nonzero (ref "c_rdata_valid") 2)
  signal "rp" 1 (bit (ref "c_rdata_valid") 1)
  signal "rdat" 512 (slice (ref "c_rdata_data") 0 512)
  signal "rtag" (tw c) (choose2 (ref "tg_rd") (tw c) (ref "rp"))
  signal "rm_ret" 1 (band (ref "rv") (bit (ref "rtag") (tw c-1)))
  signal "rm_ok" 1 (band (ref "rm_ret") (bnot (mux (ref "rm_x") (ref "x_hold") (ref "a_hold"))))
  register "rm_busy" 1 "uclk" "urq" [(ref "rm_ret",lit 0 1),(band (ref "go") (ref "rmw"),lit 1 1)]
  register "rm_x" 1 "uclk" "no_reset" [(band (ref "go") (ref "rmw"),ref "pick_x")]
  for (p,isX) in [("a",false),("x",true)] do
    let chosen := if isX then ref "pick_x" else bnot (ref "pick_x")
    let returning := band (ref "rm_ret") (if isX then ref "rm_x" else bnot (ref "rm_x"))
    signal s!"{p}q_rr" 1 (bor (all [ref "go",chosen,bnot (ref "rmw")]) returning)
    signal s!"{p}d_rr" 1 (bor (all [ref "go",chosen,ref "we",bnot (ref "rmw")]) returning)
  signal "of_wd" 512 (pack ((List.range 64).map fun k =>
    mux (band (ref "rm_busy") (bnot (bit (ref "wd") (512+k))))
      (slice (ref "rdat") (8*k) 8) (slice (ref "wd") (8*k) 8)))
  signal "ocn" 27 (pack [ref "addr",ref "sel_x",bor (ref "rm_busy") (band (ref "we") (bnot (ref "rmw")))])
  for p in List.range 2 do
    let v := ref s!"oc_v{p}"
    let oc := ref s!"oc{p}"
    let ready := bit (ref "c_cmd_ready") p
    let rv := bit (ref "oq_rv") p
    let writable := bor (bnot v) ready
    signal s!"oq_wv{p}" 1 (band (bor (ref "go") (ref "rm_ok")) (eq (ref "tp") (lit p 1)))
    signal s!"byp{p}" 1 (all [ref s!"oq_wv{p}",bnot rv,writable])
    signal s!"oq_rr{p}" 1 (band rv writable)
    signal s!"oq_push{p}" 1 (band (ref s!"oq_wv{p}") (bnot (ref s!"byp{p}")))
    register s!"oc_v{p}" 1 "uclk" "urq" [(writable,bor rv (ref s!"byp{p}"))]
    register s!"oc{p}" 27 "uclk" "no_reset" [(writable,mux rv (slice (ref "oq_rd") (27*p) 27) (ref "ocn"))]
    signal s!"opop{p}" 1 (band v ready)
    for (owner,isX) in [("a",false),("x",true)] do
      let chosen := if isX then bit oc 25 else bnot (bit oc 25)
      signal s!"opw_{owner}{p}" 1 (all [ref s!"opop{p}",bit oc 26,chosen])
      signal s!"opc_{owner}{p}" 1 (band (ref s!"opop{p}") chosen)
    signal s!"of_wv{p}" 1 (band (bor (all [ref "go",ref "we",bnot (ref "rmw")]) (ref "rm_ok")) (eq (ref "tp") (lit p 1)))
    signal s!"tg_wv{p}" 1 (all [ref "go",bor (bnot (ref "we")) (ref "rmw"),eq (ref "tp") (lit p 1)])
  for name in ["oq_wv","oq_rr","oq_push","of_wv","tg_wv","opop","opw_a","opw_x","opc_a","opc_x"] do
    signal name 2 (pack [ref s!"{name}0",ref s!"{name}1"])
  signal "c_cmd_valid" 2 (pack [ref "oc_v0",ref "oc_v1"])
  signal "c_cmd_we" 2 (pack [bit (ref "oc0") 26,bit (ref "oc1") 26])
  signal "c_cmd_addr" 50 (pack [slice (ref "oc0") 0 25,slice (ref "oc1") 0 25])
  signal "oq_wd" 27 (ref "ocn")
  signal "tg_wd" (tw c) (pack [mux (ref "pick_x") (extend (ref "x_seq") (xsw c) (asw c)) (ref "a_seq"),ref "pick_x",ref "rmw"])
  signal "tg_rr" 2 (ref "c_rdata_valid")
  for (p,isX,slotWidth,width) in [("a",false,asw c,aow c),("x",true,xsw c,xow c)] do
    let q := fun name => ref s!"{p}_{name}"
    let owner := eq (slice (ref "rtag") (asw c) 2) (lit (if isX then 1 else 0) 2)
    let returned := band (ref "rv") owner
    signal s!"{p}_oc" 1 (nonzero (q "nq") 6)
    signal s!"{p}r_wv" 1 (band returned (bnot (q "hold")))
    signal s!"{p}r_slot" slotWidth (slice (ref "rtag") 0 slotWidth)
    signal s!"{p}r_wd" 512 (ref "rdat")
    register s!"{p}_out" width "uclk" "urq" [(lit 1 1,
      sub (add (q "out") (extend (q "rgo") 1 width)) (extend returned 1 width))]
    let queued := band (bor (ref "go") (ref "rm_ok")) (if isX then ref "sel_x" else bnot (ref "sel_x"))
    register s!"{p}_nq" 6 "uclk" "urq" [(lit 1 1,
      sub (sub (add (q "nq") (extend queued 1 6)) (extend (ref s!"opc_{p}0") 1 6)) (extend (ref s!"opc_{p}1") 1 6))]
    register s!"{p}_pend" width "uclk" s!"{p}_hold" [(lit 1 1,
      sub (add (q "pend") (extend (q "rgo") 1 width)) (extend (ref s!"{p}r_cmt") 1 width))]
    register s!"{p}_seq" slotWidth "uclk" s!"{p}_hold" [(q "rgo",add (q "seq") (lit 1 slotWidth))]
    register s!"{p}_wacc" 16 "uclk" s!"{p}_hold" [(lit 1 1,
      add (add (q "wacc") (extend (ref s!"opw_{p}0") 1 16)) (extend (ref s!"opw_{p}1") 1 16))]
    sample s!"{p}_wacc_g" 16 "uclk" (gray (q "wacc") 16)
  register "cur_x" 1 "uclk" "urq" [(ref "go",ref "pick_x")]
  register "run" 6 "uclk" "urq" [(ref "go",mux (bnot (eq (ref "pick_x") (ref "cur_x"))) (lit 1 6)
    (mux (eq (ref "run") (lit 63 6)) (ref "run") (add (ref "run") (lit 1 6))))]
  register "c_err" 1 "uclk" "urq" [(bor (eq (ref "c_rdata_valid") (lit 3 2))
    (nonzero (band (ref "c_rdata_valid") (bnot (ref "tg_rv"))) 2),lit 1 1)]
  outputs [("c_cmd_valid",2),("c_cmd_we",2),("c_cmd_addr",50),
    ("aq_rr",1),("ad_rr",1),("xq_rr",1),("xd_rr",1),
    ("oq_push",2),("oq_wd",27),("oq_rr",2),("of_wv",2),("of_wd",512),
    ("tg_wv",2),("tg_wd",tw c),("tg_rr",2),
    ("ar_wv",1),("ar_wd",512),("ar_slot",asw c),("xr_wv",1),("xr_wd",512),("xr_slot",xsw c),
    ("a_wacc_g",16),("x_wacc_g",16),("a_out",aow c),("x_out",xow c),
    ("a_oc",1),("x_oc",1),("rm_busy",1),("rm_x",1),("c_err",1)]

end OpenTPU.MemChannelController
