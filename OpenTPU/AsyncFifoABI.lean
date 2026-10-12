import OpenTPU.AsyncFifo

namespace OpenTPU.AsyncFifoABI

private def sameConfig (a b : AsyncFifo.Config) : Bool :=
  a.width == b.width && a.depth == b.depth && a.outOfOrder == b.outOfOrder &&
    a.registeredReady == b.registeredReady

def coreName (c : AsyncFifo.Config) : String :=
  s!"otpu_afifo_sparkle_{c.width}_{c.depth}_{if c.outOfOrder then 1 else 0}_{if c.registeredReady then 1 else 0}"

/-- Parameter-dispatch ABI only. FIFO state, both clocks and RAM remain native AST.
    The added g_cfgN/u_native hierarchy requires CDC constraint endpoint updates
    before board implementation; the old scoped Tcl names are not preserved. -/
def toVerilog (configs : List AsyncFifo.Config) : Except String String := do
  if configs.isEmpty then throw "Asynchronous FIFO ABI needs at least one configuration"
  let configs := configs.foldl (fun seen c => if seen.any (sameConfig c) then seen else seen ++ [c]) []
  let mut cores := ""
  let mut branches := ""
  for (c,i) in configs.zipIdx do
    let name := coreName c
    let core ← AsyncFifo.toVerilog c
    -- Wide OOO flag updates can exceed a simulator's per-line token limit.
    -- Whitespace alone changes; the emitted native circuit tokens are identical.
    let formatted := core.replace " ? " " ?\n        "
    cores := cores ++ formatted.replace "module otpu_afifo_sparkle (" s!"module {name} ("
    branches := branches ++ s!"  {if i == 0 then "if" else "else if"} (W == {c.width} && DEPTH == {c.depth} && OOO == {if c.outOfOrder then 1 else 0} && RWR == {if c.registeredReady then 1 else 0}) begin : g_cfg{i}\n"
    branches := branches ++ s!"    {name} u_native (.wclk, .wrst, .wvalid, .wready, .wdata, .wslot, .wcommit, .wused, .rclk, .rrst, .rvalid, .rready, .rdata);\n"
    if c.outOfOrder then
      branches := branches ++ "`ifndef SYNTHESIS\n    always @(posedge wclk) if (!wrst && wvalid && u_native.wvld[wslot])\n      $error(\"otpu_afifo: slot %0d written twice\", wslot);\n`endif\n"
    branches := branches ++ "  end\n"
  return cores ++ "
module otpu_afifo #(
  parameter int W = 32,
  parameter int DEPTH = 16,
  parameter bit OOO = 1'b0,
  parameter bit RWR = 1'b0
) (
  input logic wclk, wrst, wvalid,
  output logic wready,
  input logic [W-1:0] wdata,
  input logic [$clog2(DEPTH)-1:0] wslot,
  output logic wcommit,
  output logic [$clog2(DEPTH):0] wused,
  input logic rclk, rrst,
  output logic rvalid,
  input logic rready,
  output logic [W-1:0] rdata
);
  localparam int AW = $clog2(DEPTH);
  initial if (DEPTH != (1 << AW) || DEPTH < 4)
    $fatal(1, \"otpu_afifo: DEPTH must be a power of two >= 4\");
" ++ branches ++ "  else begin : g_unsupported
    initial $fatal(1, \"otpu_afifo: configuration not emitted by native FIFO ABI\");
    assign wready = 1'b0;
    assign wcommit = 1'b0;
    assign wused = '0;
    assign rvalid = 1'b0;
    assign rdata = '0;
  end
endmodule
"

/-- The six asynchronous FIFO instances in the board memory channel. -/
def memChConfigs (ard : Nat := 64) (xrd : Nat := 16) : List AsyncFifo.Config :=
  [⟨26,32,false,false⟩, ⟨577,32,false,false⟩, ⟨512,ard,true,false⟩,
   ⟨26,16,false,true⟩, ⟨577,16,false,true⟩, ⟨512,xrd,true,false⟩]

def memChVerilog (ard : Nat := 64) (xrd : Nat := 16) : Except String String := do
  if xrd > ard || ard + xrd + 1 > 128 then
    throw "Memory channel FIFO configuration requires XRD <= ARD and ARD + XRD + 1 <= 128"
  toVerilog (memChConfigs ard xrd)

end OpenTPU.AsyncFifoABI
