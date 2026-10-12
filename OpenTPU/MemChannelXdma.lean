import OpenTPU.MemChannelSupport

namespace OpenTPU.MemChannelXdma
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.MemChannelSupport

/-- XDMA burst packing and response sequencing, with explicit synchronous FIFO pins. -/
def build (c : Config) : Module := runModule "otpu_mem_channel_xdma_sparkle" do
  setup ([("xclk",1),("x_crst",1),("x_awvalid",1),("x_awid",c.idWidth),("x_awaddr",32),("x_awlen",8),
    ("x_wvalid",1),("x_wdata",128),("x_wstrb",16),("x_wlast",1),("x_bready",1),
    ("x_arvalid",1),("x_arid",c.idWidth),("x_araddr",32),("x_arlen",8),("x_rready",1),
    ("xq_wr",1),("xd_wr",1),("xr_rv",1),("xr_rd",512),("x_wacc_g",16)] ++
    ([("xai",32),("xwi",27),("xrq",c.idWidth+10),("xbq",c.idWidth+7)].flatMap fun (p,w) =>
      [(s!"{p}_wr",1),(s!"{p}_rv",1),(s!"{p}_rd",w)]))
  for p in ["ar","aw"] do
    signal s!"x_{p}n" 7 (slice (add (extend (ref s!"x_{p}len") 8 9)
      (extend (slice (ref s!"x_{p}addr") 4 2) 2 9)) 2 7)
  signal "x_arready" 1 (all [bnot (ref "x_crst"),ref "xai_wr",ref "xrq_wr"])
  signal "x_awready" 1 (all [bnot (ref "x_crst"),ref "xwi_wr",ref "xbq_wr"])
  signal "xai_wv" 1 (band (ref "x_arvalid") (ref "x_arready"))
  signal "xrq_wv" 1 (ref "xai_wv")
  signal "xwi_wv" 1 (band (ref "x_awvalid") (ref "x_awready"))
  signal "xbq_wv" 1 (ref "xwi_wv")
  signal "xai_wd" 32 (pack [slice (ref "x_araddr") 6 25,ref "x_arn"])
  signal "xwi_wd" 27 (pack [slice (ref "x_awaddr") 6 25,slice (ref "x_awaddr") 4 2])
  signal "xrq_wd" (c.idWidth+10) (pack [slice (ref "x_araddr") 4 2,ref "x_arlen",ref "x_arid"])
  signal "xbq_wd" (c.idWidth+7) (pack [ref "x_awn",ref "x_awid"])
  signal "x_wlane" 2 (mux (ref "x_wfirst") (slice (ref "xwi_rd") 25 2) (ref "x_wlane_r"))
  signal "x_wpush" 1 (bor (eq (ref "x_wlane") (lit 3 2)) (ref "x_wlast"))
  signal "x_selw" 1 (all [ref "xwi_rv",ref "x_wvalid",ref "x_wpush"])
  signal "x_rlastb" 1 (eq (ref "x_roff") (slice (ref "xai_rd") 25 7))
  for (name,width,old,current) in [("x_wdata_full",128,"x_wbuf","x_wdata"),("x_wstb_full",16,"x_wstb","x_wstrb")] do
    signal name (4*width) (pack ((List.range 4).map fun lane =>
      mux (eq (ref "x_wlane") (lit lane 2)) (ref current) (slice (ref old) (lane*width) width)))
  signal "xq_wv" 1 (all [bnot (ref "x_crst"),ref "xq_wr",mux (ref "x_selw") (ref "xd_wr") (ref "xai_rv")])
  signal "xq_wd" 26 (mux (ref "x_selw")
    (pack [truncAdd (slice (ref "xwi_rd") 0 25) (extend (ref "x_woff") 7 25) 25,lit 1 1])
    (pack [truncAdd (slice (ref "xai_rd") 0 25) (extend (ref "x_roff") 7 25) 25,lit 0 1]))
  signal "x_wready" 1 (all [bnot (ref "x_crst"),ref "xwi_rv",
    bor (bnot (ref "x_wpush")) (band (ref "xq_wr") (ref "xd_wr"))])
  signal "xd_wv" 1 (all [ref "x_wvalid",ref "x_wready",ref "x_wpush"])
  let strobesFull := eq (ref "x_wstrb") (lit 65535 16)
  signal "x_wfull" 1 (band strobesFull (all ((List.range 4).map fun lane =>
    bor (eq (ref "x_wlane") (lit lane 2)) (bit (ref "x_wsfull") lane))))
  signal "xd_wd" 577 (pack [ref "x_wdata_full",ref "x_wstb_full",bnot (ref "x_wfull")])
  signal "xai_rr" 1 (all [ref "xq_wv",bnot (ref "x_selw"),ref "x_rlastb"])
  signal "xwi_rr" 1 (all [ref "x_wvalid",ref "x_wready",ref "x_wlast"])
  let takeW := band (ref "x_wvalid") (ref "x_wready")
  register "x_roff" 7 "xclk" "x_crst" [(band (ref "xq_wv") (bnot (ref "x_selw")),
    mux (ref "x_rlastb") (lit 0 7) (add (ref "x_roff") (lit 1 7)))]
  register "x_woff" 7 "xclk" "x_crst" [(band takeW (ref "x_wpush"),
    mux (ref "x_wlast") (lit 0 7) (add (ref "x_woff") (lit 1 7)))]
  register "x_wfirst" 1 "xclk" "x_crst" [(takeW,ref "x_wlast")] 1
  register "x_wlane_r" 2 "xclk" "x_crst" [(takeW,add (ref "x_wlane") (lit 1 2))]
  for (name,width,value) in [("x_wbuf",512,ref "x_wdata_full"),("x_wstb",64,ref "x_wstb_full"),
      ("x_wsfull",4,pack ((List.range 4).map fun lane => mux (eq (ref "x_wlane") (lit lane 2))
        strobesFull (bit (ref "x_wsfull") lane)))] do
    register name width "xclk" "x_crst" [(takeW,mux (ref "x_wpush") (lit 0 width) value)]
  signal "x_rlane" 2 (mux (ref "x_rfirst") (slice (ref "xrq_rd") 0 2) (ref "x_rlane_r"))
  signal "x_rvalid" 1 (band (ref "xr_rv") (ref "xrq_rv"))
  signal "x_rdata" 128 (SeqWindow.select ((List.range 4).map fun lane => slice (ref "xr_rd") (128*lane) 128) (ref "x_rlane") 2 128)
  signal "x_rid" c.idWidth (slice (ref "xrq_rd") 10 c.idWidth)
  signal "x_rlast" 1 (eq (ref "x_rcnt") (slice (ref "xrq_rd") 2 8))
  signal "x_rresp" 2 (lit 0 2)
  let takeR := band (ref "x_rvalid") (ref "x_rready")
  signal "xr_rr" 1 (band takeR (bor (eq (ref "x_rlane") (lit 3 2)) (ref "x_rlast")))
  signal "xrq_rr" 1 (band takeR (ref "x_rlast"))
  register "x_rcnt" 8 "xclk" "x_crst" [(takeR,mux (ref "x_rlast") (lit 0 8) (add (ref "x_rcnt") (lit 1 8)))]
  register "x_rlane_r" 2 "xclk" "x_crst" [(takeR,add (ref "x_rlane") (lit 1 2))]
  register "x_rfirst" 1 "xclk" "x_crst" [(takeR,ref "x_rlast")] 1
  for (n,v) in [("x_wacc_s1",ref "x_wacc_g"),("x_wacc_s2",ref "x_wacc_s1"),("x_wacc_c",binary (ref "x_wacc_s2") 16)] do
    register n 16 "xclk" "x_crst" [(lit 1 1,v)]
  let completed := extend (slice (ref "xbq_rd") 0 7) 7 16
  signal "x_bvalid" 1 (band (ref "xbq_rv") (lt completed (truncSub (ref "x_wacc_c") (ref "x_wdone") 16)))
  signal "x_bid" c.idWidth (slice (ref "xbq_rd") 7 c.idWidth)
  signal "x_bresp" 2 (lit 0 2)
  signal "xbq_rr" 1 (band (ref "x_bvalid") (ref "x_bready"))
  register "x_wdone" 16 "xclk" "x_crst" [(ref "xbq_rr",add (add (ref "x_wdone") completed) (lit 1 16))]
  outputs ([("x_arready",1),("x_awready",1),("x_wready",1),("x_rvalid",1),("x_rdata",128),("x_rid",c.idWidth),
    ("x_rlast",1),("x_rresp",2),("x_bvalid",1),("x_bid",c.idWidth),("x_bresp",2),
    ("xq_wv",1),("xq_wd",26),("xd_wv",1),("xd_wd",577),("xr_rr",1)] ++
    ([("xai",32),("xwi",27),("xrq",c.idWidth+10),("xbq",c.idWidth+7)].flatMap fun (p,w) =>
      [(s!"{p}_wv",1),(s!"{p}_wd",w),(s!"{p}_rr",1)]))

def hints : Backend.RegisterHints := ["x_wacc_s1","x_wacc_s2"].map (fun n => (n,[.asyncRegister]))

end OpenTPU.MemChannelXdma
