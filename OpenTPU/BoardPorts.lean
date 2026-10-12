import OpenTPU.BoardConfig

namespace OpenTPU.Board
open Sparkle.IR.AST

/-- External board ports, with packed channel zero in the least-significant bits. -/
def inputs : List (String × Nat) :=
  [("clk",1),("rst",1),("calib",2),("temp",12),("i2c_pin",5),
   ("s_ctl_awaddr",12),("s_ctl_awvalid",1),("s_ctl_wdata",32),("s_ctl_wstrb",4),
   ("s_ctl_wvalid",1),("s_ctl_bready",1),("s_ctl_araddr",12),("s_ctl_arvalid",1),
   ("s_ctl_rready",1),("n_cready",2),("n_wready",2),("n_rvalid",2),
   ("n_rdata",1024),("n_wdone",32),("n_err",2)]

def outputs : List (String × Nat) :=
  [("led",3),("i2c_lo",4),("s_ctl_awready",1),("s_ctl_wready",1),("s_ctl_bresp",2),
   ("s_ctl_bvalid",1),("s_ctl_arready",1),("s_ctl_rdata",32),("s_ctl_rresp",2),
   ("s_ctl_rvalid",1),("n_cvalid",2),("n_cwe",2),("n_caddr",50),
   ("n_wvalid",2),("n_wdata",1024),("n_wmask",128)]

/-- Pure pin contract of the retained original slice. Argument word zero is in
    bits 31:0; cmd_t and perf_t keep their original packed declaration order. -/
def sliceInputs (c : Config) : List (String × Nat) :=
  [("clk",1),("sys_rst",1),("rst",1),("rinit",256),
   ("ld_start",1),("ld_addr",32),("ld_n",32),("a_rdy",1),("b_rdy",1),
   ("sw_rdy",1),("wr_idle",1),("a_rvalid",1),("a_rdata",32),("a_rdata2",32),
   ("b_rvalid",1),("b_rtag",1),("b_rdata",c.d*8),("coll_ack",1),
   ("coll_ren",c.lanes),("coll_raddr",c.lanes*32),("coll_wen",c.lanes),
   ("coll_waddr",c.lanes*32),("coll_wdata",c.lanes*32),("coll_gnt",1),("dump",1)]

def sliceOutputs (c : Config) : List (String × Nat) :=
  [("ld_busy",1),("a_req",1),("a_we",1),("a_addr",32),("a_wdata",32),("a_be",4),
   ("sw_req",1),("sw_addr",32),("sw_wdata",32),("sw_be",4),
   ("b_req",1),("b_tag",1),("b_we",1),("b_wmask",c.d/4),("b_wdata",c.d*8),
   ("b_addr",32),("b_par",1),("coll_req",1),("coll_cmd",240),
   ("coll_rdata",c.lanes*32),("coll_gnt_local",1),
   ("halted",1),("error",1),("wait_to",1),("a_inval",1),("icount",32),
   ("pf",Trace.width Trace.perfFields)]

/-- Interface metadata only: no slice behavior is supplied or assumed here. -/
def sliceContract (c : Config) : Module :=
  {name:="otpu_board_slice_boundary",
   inputs:=(sliceInputs c).map fun (name,w) => {name,ty:=.bitVector w},
   outputs:=(sliceOutputs c).map fun (name,w) => {name,ty:=.bitVector w},
   wires:=[],body:=[],isPrimitive:=true}

end OpenTPU.Board
