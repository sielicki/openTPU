import OpenTPU.TraceABI
import OpenTPU.MemChannelABI
import OpenTPU.BoardABI
import OpenTPU.BoardNativeABI
import OpenTPU.FpgaTopCompleteABI
import OpenTPU.TopABI
import OpenTPU.AsyncFifoABI
import OpenTPU.ControlABI
import OpenTPU.MxuABI
import OpenTPU.MxuPhysical
import OpenTPU.MxuStoragePhysical
import OpenTPU.BoardFifo
import OpenTPU.AsyncFifo
import OpenTPU.AxiSlice
import OpenTPU.DmaSplitABI
import OpenTPU.VpuControl
import OpenTPU.VpuABI
import OpenTPU.DramABI
import OpenTPU.NativeDramABI
import OpenTPU.Collective
import OpenTPU.Float
import OpenTPU.FloatConvert
import OpenTPU.Quant
import OpenTPU.DmaABI
import OpenTPU.SeMicrocode
import OpenTPU.SeHelpers
import OpenTPU.SeCompositeABI
import OpenTPU.SeTailABI
import OpenTPU.QuantRead
import OpenTPU.QuantWrite
import OpenTPU.QuantScale
import OpenTPU.ActRam
import OpenTPU.Backend
import OpenTPU.TMemABI
import OpenTPU.VTree
import OpenTPU.Physical
import OpenTPU.SeqLogic
import OpenTPU.SeqSchedule
import OpenTPU.SeqDispatch
import OpenTPU.SeqWindow
import OpenTPU.Seq

open OpenTPU Sparkle.Backend.Verilog

/-- ABI adapter only: all control and datapath logic comes from the Lean circuit. -/
def collectiveWrapper (cfg : Collective.Config) : String :=
  s!"\nmodule otpu_coll import otpu_pkg::*; #(parameter int S = {cfg.slices}, LANES = {cfg.lanes})(
  input logic clk, rst,
  input logic [S-1:0] req,
  input cmd_t cmds [S],
  input logic gnt,
  output logic ack,
  output logic [S-1:0][LANES-1:0] r_en,
  output logic [S-1:0][LANES-1:0][31:0] r_addr,
  input logic [S-1:0][LANES-1:0][31:0] r_data,
  output logic [LANES-1:0] w_en,
  output logic [LANES-1:0][31:0] w_addr, w_data
);
  initial if (S != {cfg.slices} || LANES != {cfg.lanes})
    $fatal(1, \"Sparkle collective configuration mismatch; regenerate for S/LANES\");
  wire [S*240-1:0] packed_cmds;
  for (genvar s = 0; s < S; s++) assign packed_cmds[s*240 +: 240] = cmds[s];
  otpu_coll_sparkle impl(.clk, .rst, .req, .cmds(packed_cmds), .gnt, .ack,
    .r_en, .r_addr, .r_data, .w_en, .w_addr, .w_data);
endmodule
"

/-- The generic delay and composite wiring remain shared with the reference RTL. -/
def floatWrappers : String := "
module otpu_fmul #(parameter int LAT=2)(input logic clk,en,
  input logic [31:0] a,b, output logic [31:0] y);
  initial if(LAT<2) $fatal(1, \"fmul LAT must be >= 2\");
  wire [31:0] v;
  otpu_fmul_sparkle_2 impl(.clk,.en,.a,.b,.y(v));
  otpu_delay #(.W(32),.N(LAT-2)) pad(.clk,.en,.d(v),.q(y));
endmodule
module otpu_fadd #(parameter int LAT=4)(input logic clk,en,
  input logic [31:0] a,b, output logic [31:0] y);
  initial if(LAT<4) $fatal(1, \"fadd LAT must be >= 4\");
  wire [31:0] v;
  otpu_fadd_sparkle_4 impl(.clk,.en,.a,.b,.y(v));
  otpu_delay #(.W(32),.N(LAT-4)) pad(.clk,.en,.d(v),.q(y));
endmodule
module otpu_fadd2(input logic clk,en, input logic [31:0] a,b,
  output logic [31:0] y,yo);
  otpu_fadd2_sparkle impl(.clk,.en,.a,.b,.y,.yo);
endmodule
"

/-- Parameter guard and unchanged ACT RAM port ABI. -/
def actramWrapper (c : ActRam.Config) : String :=
  s!"
module otpu_actram #(parameter int D={c.depth}, MCOLS={c.columns}, ROWS={c.rows},
  BLOCKS={c.blocks}, LANES={c.lanes})(
  input logic clk,
  input logic [LANES-1:0] we,
  input logic [7:0] w_row,
  input logic [31:0] w_idx,
  input logic [LANES-1:0][7:0] w_data,
  input logic w_dup,
  input logic [7:0] w_off,
  input logic swe,
  input logic [7:0] s_row,
  input logic [15:0] s_blk,
  input logic [31:0] s_data,
  input logic ren,r_use,
  input logic [15:0] r_blk,r_blk2,
  input logic [MCOLS-1:0] r_hi,
  input logic [7:0] r_grp,
  output wire [MCOLS*D*8-1:0] r_data,
  output wire [MCOLS*32-1:0] r_scale
);
  initial if(D!={c.depth} || MCOLS!={c.columns} || ROWS!={c.rows} ||
             BLOCKS!={c.blocks} || LANES!={c.lanes})
    $fatal(1, \"Sparkle ACT RAM configuration mismatch; regenerate\");
  wire hazard;
  otpu_actram_sparkle impl(.hazard,.clk,.we,.w_row,.w_idx,.w_data,.w_dup,.w_off,.swe,
    .s_row,.s_blk,.s_data,.ren,.r_use,.r_blk,.r_blk2,.r_hi,.r_grp,.r_data,.r_scale);
`ifndef SYNTHESIS
  always @(posedge clk) if(ren && r_use && hazard)
    $fatal(1, \"Sparkle ACT RAM: consumed read while its write is in flight\");
`endif
endmodule
"

def main (args : List String) : IO UInt32 := do
  match args with
  | "fpga-top" :: values | "fpga-top-physical" :: values =>
    if values.length != 12 then
      throw <| IO.userError "fpga-top/fpga-top-physical expects 11 configuration values and an output path"
    let ns ← (values.take 11).mapM fun s =>
      match s.toNat? with
      | some n => pure n
      | none => throw <| IO.userError "FPGA parameters must be natural numbers"
    if ns[9]! > 1 then throw <| IO.userError "FPGA DSTEP must be 0 or 1"
    let c : FpgaTop.Config := {
      columns := ns[0]!, actRows := ns[1]!, vpuCompositeLanes := ns[2]!
      mxuImplementation := ns[3]!, lanes := ns[4]!, unitLanes := ns[5]!
      coreKhz := ns[6]!, buildId := ns[7]!, ddrMts := ns[8]!
      dstep := ns[9]! == 1, pcieGen := ns[10]! }
    let rtl ← IO.ofExcept (if args.head! == "fpga-top-physical" then
      FpgaTop.physicalAbiVerilog c else FpgaTop.abiVerilog c)
    IO.FS.writeFile values[11]! rtl
    return 0
  | "top" :: values =>
    if values.length != 20 then
      throw <| IO.userError "top expects 19 configuration values and an output path"
    let ns ← (values.take 19).mapM fun s =>
      match s.toNat? with
      | some n => pure n
      | none => throw <| IO.userError "top parameters must be natural numbers"
    let c : Top.Config := {
      slice := {
        sliceId := 0
        slices := ns[0]!
        depth := ns[1]!
        columns := ns[2]!
        actBlocks := ns[3]!
        actRows := ns[4]!
        tmemWords := ns[5]!
        imemWords := ns[6]!
        fifoDepth := ns[9]!
        lanes := ns[10]!
        slots := ns[11]!
        readsPerBank := ns[12]!
        writesPerBank := ns[13]!
        mxuImpl := ns[14]!
        mxuChain := ns[15]!
        compositeLanes := ns[16]!
        unitLanes := ns[17]!
        pqWindow := 64
        streams := true }
      dramWords := ns[7]!
      dramLatency := ns[8]!
      axi := ns[18]! }
    IO.FS.writeFile values[19]! (← IO.ofExcept (Top.abiVerilog c))
    return 0
  | ["mxu-physical", d, cols, rows, depth, lanes, impl, chain, path] =>
    let ns ← [d,cols,rows,depth,lanes,impl,chain].mapM fun s =>
      match s.toNat? with
      | some n => pure n
      | none => throw <| IO.userError "MXU parameters must be natural numbers"
    let c : Mxu.Config := ⟨ns[0]!,ns[1]!,ns[2]!,ns[3]!,ns[4]!,ns[5]!,ns[6]!,0⟩
    let core ← IO.ofExcept (MxuPhysical.emit c)
    IO.FS.writeFile path (core.replace " ? " " ?\n        " ++ Mxu.wrapperDSPModel c)
    return 0
  | "board-assembly" :: values | "board-native" :: values | "board-physical" :: values =>
    if values.length != 26 then
      throw <| IO.userError "board-assembly/board-native/board-physical expects 25 configuration values and an output path"
    let ns ← (values.take 25).mapM fun s =>
      match s.toNat? with
      | some n => pure n
      | none => throw <| IO.userError "board parameters must be natural numbers"
    if (ns.drop 21).any (· > 1) then throw <| IO.userError "board feature flags must be 0 or 1"
    let c : Board.Config := ⟨ns[0]!,ns[1]!,ns[2]!,ns[3]!,ns[4]!,ns[5]!,ns[6]!,ns[7]!,
      ns[8]!,ns[9]!,ns[10]!,ns[11]!,ns[12]!,ns[13]!,ns[14]!,ns[15]!,ns[16]!,ns[17]!,
      ns[18]!,ns[19]!,ns[20]!,ns[21]! == 1,ns[22]! == 1,ns[23]! == 1,ns[24]! == 1⟩
    let rtl ← IO.ofExcept (if args.head! == "board-physical" then Board.physicalNativeAbiVerilog c
      else if args.head! == "board-native" then Board.nativeAbiVerilog c else Board.abiVerilog c)
    IO.FS.writeFile values[25]! rtl
    return 0
  | ["mem-channel", idw, ard, xrd, run, oq, od, path] =>
    let ns ← [idw,ard,xrd,run,oq,od].mapM fun s =>
      match s.toNat? with
      | some n => pure n
      | none => throw <| IO.userError "memory-channel parameters must be natural numbers"
    let c : MemChannel.Config := ⟨ns[0]!,ns[1]!,ns[2]!,ns[3]!,ns[4]!,ns[5]!⟩
    IO.FS.writeFile path (← IO.ofExcept (MemChannel.abiVerilog c))
    return 0
  | ["trace", depth, queue, window, path] =>
    let some d := depth.toNat? | throw <| IO.userError "invalid trace depth"
    let some q := queue.toNat? | throw <| IO.userError "invalid trace queue depth"
    let some w := window.toNat? | throw <| IO.userError "invalid trace window"
    IO.FS.writeFile path (← IO.ofExcept (Trace.abiVerilog ⟨d,q,w⟩))
    return 0
  | ["async-fifo-family", ard, xrd, path] =>
    let some a := ard.toNat? | throw <| IO.userError "invalid memory-channel ARD"
    let some x := xrd.toNat? | throw <| IO.userError "invalid memory-channel XRD"
    IO.FS.writeFile path (← IO.ofExcept (AsyncFifoABI.memChVerilog a x))
    return 0
  | ["mxu-test", d, cols, rows, depth, lanes, impl, chain, path] =>
    let ns ← [d,cols,rows,depth,lanes,impl,chain].mapM fun s =>
      match s.toNat? with
      | some n => pure n
      | none => throw <| IO.userError "MXU parameters must be natural numbers"
    let c : Mxu.Config := ⟨ns[0]!,ns[1]!,ns[2]!,ns[3]!,ns[4]!,ns[5]!,ns[6]!,0⟩
    IO.ofExcept c.validateWhole
    let datapath := String.join ([MxuEpilogue.multiply,MxuEpilogue.addition,
      MxuDot.build c,MxuEpilogue.build c,Mxu.build c].map toVerilog)
    let core := datapath ++ (← IO.ofExcept (MxuStoragePhysical.emit c))
    -- Preserve tokens while avoiding simulator limits on very wide mux lines.
    IO.FS.writeFile path (core.replace " ? " " ?\n        " ++ Mxu.wrapper c)
    return 0
  | ["control", d, cols, lanes, rows, khz, bid, mts, trace, pq, temp, i2c, chash, dstep, hostcal, path] =>
    let ns ← [d,cols,lanes,rows,khz,bid,mts,trace,pq,temp,i2c,chash,dstep,hostcal].mapM fun s =>
      match s.toNat? with
      | some n => pure n
      | none => throw <| IO.userError "control parameters must be natural numbers"
    if (ns.drop 9).any (· > 1) then throw <| IO.userError "control feature flags must be 0 or 1"
    let c : Control.Config := ⟨ns[0]!,ns[1]!,ns[2]!,ns[3]!,ns[4]!,ns[5]!,ns[6]!,ns[7]!,ns[8]!,
      ns[9]! == 1,ns[10]! == 1,ns[11]! == 1,ns[12]! == 1,ns[13]! == 1⟩
    IO.FS.writeFile path (Control.abiVerilog c)
    return 0
  | [kind, depth, qd, wqd, chash, gather, rd, ad, apf, path] =>
    if kind != "native-dram" && kind != "native-dram-core" then
      throw <| IO.userError "expected native-dram or native-dram-core"
    let some d := depth.toNat? | throw <| IO.userError "invalid D"
    let some q := qd.toNat? | throw <| IO.userError "invalid QD"
    let some w := wqd.toNat? | throw <| IO.userError "invalid WQD"
    if chash != "0" && chash != "1" then throw <| IO.userError "CHASH must be 0 or 1"
    let some g := gather.toNat? | throw <| IO.userError "invalid GATHER"
    let some r := rd.toNat? | throw <| IO.userError "invalid RD"
    let some a := ad.toNat? | throw <| IO.userError "invalid AD"
    let some p := apf.toNat? | throw <| IO.userError "invalid APF"
    let cfg : NativeDram.Config := ⟨d,q,w,chash == "1",g,r,a,p⟩
    IO.ofExcept cfg.validate
    IO.FS.writeFile path (toVerilog (NativeDram.build cfg) ++ if kind == "native-dram" then NativeDram.wrapper cfg else "")
    return 0
  | ["se-helpers", path] =>
    IO.FS.writeFile path (toVerilog SeHelpers.build)
    return 0
  | ["float-convert", path] =>
    IO.FS.writeFile path (toVerilog FloatConvert.build)
    return 0
  | [kind, words, depth, slices, slots, path] =>
    if kind == "async-fifo-core" then
      let some w := words.toNat? | throw <| IO.userError "invalid asynchronous FIFO width"
      let some d := depth.toNat? | throw <| IO.userError "invalid asynchronous FIFO depth"
      if (slices != "0" && slices != "1") || (slots != "0" && slots != "1") then
        throw <| IO.userError "asynchronous FIFO OOO and RWR must be 0 or 1"
      IO.FS.writeFile path (← IO.ofExcept (AsyncFifo.toVerilog ⟨w,d,slices == "1",slots == "1"⟩))
      return 0
    if kind == "vpu-control" || kind == "vpu-core" || kind == "vpu-test" then
      let some l := words.toNat? | throw <| IO.userError "invalid VPU LANES"
      let some cl := depth.toNat? | throw <| IO.userError "invalid VPU CL"
      if (slices != "0" && slices != "1") || (slots != "0" && slots != "1") then
        throw <| IO.userError "VPU HAS_SE and WBUF must be 0 or 1"
      let cfg : VpuControl.Config := {lanes := l,compositeLanes := cl,streams := slices == "1",buffered := slots == "1"}
      let rtl ← IO.ofExcept (if kind == "vpu-control" then VpuControl.toVerilog cfg else Vpu.toVerilog cfg)
      IO.FS.writeFile path (rtl ++ if kind == "vpu-test" then Vpu.wrapper cfg else "")
      return 0
    if kind == "dma" || kind == "dma-core" then
      let some d := words.toNat? | throw <| IO.userError "invalid DMA D"
      let some l := depth.toNat? | throw <| IO.userError "invalid DMA LANES"
      let some b := slices.toNat? | throw <| IO.userError "invalid DMA DEPTH"
      if slots != "0" && slots != "1" then throw <| IO.userError "DMA HAS_DSTEP must be 0 or 1"
      let cfg : Dma.Config := ⟨d,l,b,slots == "1"⟩
      IO.FS.writeFile path ((← IO.ofExcept (Dma.toVerilog cfg)) ++ if kind == "dma" then Dma.wrapper cfg else "")
      return 0
    if kind != "seq" && kind != "seq-core" then throw <| IO.userError "expected seq or seq-core"
    let some w := words.toNat? | throw <| IO.userError "invalid IMEM_WORDS"
    let some d := depth.toNat? | throw <| IO.userError "invalid sequencer D"
    let some s := slices.toNat? | throw <| IO.userError "invalid sequencer S"
    let some n := slots.toNat? | throw <| IO.userError "invalid sequencer WIN"
    let cfg : Seq.Config := { words := w, depth := d, slices := s, slots := n }
    IO.ofExcept cfg.validate
    IO.FS.writeFile path ((← IO.ofExcept (Physical.seq cfg)) ++ if kind == "seq" then Seq.wrapper cfg else "")
    return 0
  | ["seq-fetch", words, depth, slices, path] =>
    let some w := words.toNat? | throw <| IO.userError "invalid IMEM_WORDS"
    let some d := depth.toNat? | throw <| IO.userError "invalid sequencer D"
    let some s := slices.toNat? | throw <| IO.userError "invalid sequencer S"
    let cfg : SeqFetch.Config := ⟨w,d,s⟩
    IO.ofExcept cfg.validate
    IO.FS.writeFile path (toVerilog (SeqFetch.build cfg))
    return 0
  | [kind, lm, la, tw, path] =>
    if kind == "sfifo-core" then
      let some w := lm.toNat? | throw <| IO.userError "invalid FIFO W"
      let some d := la.toNat? | throw <| IO.userError "invalid FIFO DEPTH"
      if tw != "0" && tw != "1" then throw <| IO.userError "FIFO RO must be 0 or 1"
      IO.FS.writeFile path (← IO.ofExcept (BoardFifo.fifoVerilog ⟨w,d,tw == "1"⟩))
      return 0
    if kind == "axi-split-core" then
      let some i := lm.toNat? | throw <| IO.userError "invalid AXI IDW"
      let some d := la.toNat? | throw <| IO.userError "invalid AXI DW"
      let some n := tw.toNat? | throw <| IO.userError "invalid AXI OD"
      IO.FS.writeFile path (← IO.ofExcept (AxiSplit.toVerilog ⟨i,d,n⟩))
      return 0
    if kind == "axi-slice-core" || kind == "dma-split-core" || kind == "dma-split" then
      if lm != "0" && lm != "1" then throw <| IO.userError "AXI slice REG must be 0 or 1"
      let some i := la.toNat? | throw <| IO.userError "invalid AXI IDW"
      let some d := tw.toNat? | throw <| IO.userError "invalid AXI DW"
      let design ← IO.ofExcept (if kind == "axi-slice-core" then AxiSlice.build ⟨lm == "1",i,d⟩
        else DmaSplit.build ⟨lm == "1",i,d⟩)
      let abi ← if kind == "dma-split" then IO.ofExcept (DmaSplit.wrapper ⟨lm == "1",i,d⟩) else pure ""
      let rtl ← if kind == "axi-slice-core" then pure (String.join (design.modules.map toVerilog))
        else IO.ofExcept (DmaSplit.toVerilog ⟨lm == "1",i,d⟩)
      IO.FS.writeFile path (rtl ++ abi)
      return 0
    if kind == "dram" || kind == "dram-core" then
      let some w := lm.toNat? | throw <| IO.userError "invalid DRAM WORDS"
      let some d := la.toNat? | throw <| IO.userError "invalid DRAM D"
      let some l := tw.toNat? | throw <| IO.userError "invalid DRAM LAT"
      let cfg : Dram.Config := ⟨w,d,l⟩
      IO.ofExcept cfg.validate
      IO.FS.writeFile path (toVerilog (Dram.build cfg) ++ if kind == "dram" then Dram.wrapper cfg else "")
      return 0
    if kind == "se-tail" || kind == "se-tail-core" then
      let some l := lm.toNat? | throw <| IO.userError "invalid LANES"
      let some a := la.toNat? | throw <| IO.userError "invalid TA"
      let some d := tw.toNat? | throw <| IO.userError "invalid QD"
      let cfg : SeTail.Config := ⟨l,a,d⟩
      let rtl ← IO.ofExcept (SeTail.toVerilog cfg)
      IO.FS.writeFile path (rtl ++ if kind == "se-tail" then SeTail.wrapper cfg else "")
      return 0
    if kind != "qscale" && kind != "qscale-core" then throw <| IO.userError "expected qscale or qscale-core"
    let some m := lm.toNat? | throw <| IO.userError "invalid LM"
    let some a := la.toNat? | throw <| IO.userError "invalid LA"
    let some t := tw.toNat? | throw <| IO.userError "invalid TW"
    let cfg : QuantScale.Config := ⟨m,a,t⟩
    let rtl ← IO.ofExcept (QuantScale.toVerilog cfg)
    IO.FS.writeFile path ((if kind == "qscale" then "`define OTPU_SPARKLE_QSCALE\n" else "") ++ rtl ++
      if kind == "qscale" then QuantScale.wrapper cfg else "")
    return 0
  | [kind, count, path] =>
    if kind == "skid-core" then
      let some w := count.toNat? | throw <| IO.userError "invalid skid W"
      IO.FS.writeFile path (toVerilog (← IO.ofExcept (BoardFifo.skid w)))
      return 0
    let some n := count.toNat? | throw <| IO.userError "invalid LANES, WIN, or stage count"
    if kind == "se-microcode" then
      IO.FS.writeFile path (toVerilog (← IO.ofExcept (SeMicrocode.build n)))
    else if kind == "qread" || kind == "qread-core" then
      let cfg : QuantRead.Config := ⟨n⟩
      let rtl ← IO.ofExcept (QuantRead.toVerilog cfg)
      IO.FS.writeFile path ((if kind == "qread" then "`define OTPU_SPARKLE_QREAD\n" else "") ++ rtl ++
        if kind == "qread" then QuantRead.wrapper cfg else "")
    else if kind == "qwrite" || kind == "qwrite-core" then
      let cfg : QuantWrite.Config := ⟨n⟩
      let rtl ← IO.ofExcept (QuantWrite.toVerilog cfg)
      IO.FS.writeFile path ((if kind == "qwrite" then "`define OTPU_SPARKLE_QWRITE\n" else "") ++ rtl ++
        if kind == "qwrite" then QuantWrite.wrapper cfg else "")
    else if kind == "seq-schedule" || kind == "seq-window" then
      IO.ofExcept (SeqSchedule.validate n)
      IO.FS.writeFile path (toVerilog (if kind == "seq-window" then SeqWindow.build n else SeqSchedule.build n))
    else throw <| IO.userError "expected qread, qwrite, seq-schedule, seq-window, or se-microcode"
    return 0
  | [kind, words, lanes, nrp, nwp, wpb, gr, gw, host, guests, path] =>
    if kind != "tmem" && kind != "tmem-core" then throw <| IO.userError "expected tmem or tmem-core"
    let nums ← [words, lanes, nrp, nwp, wpb, gr, gw, host, guests].mapM fun s =>
      match s.toNat? with
      | some n => pure n
      | none => throw <| IO.userError s!"invalid TMEM parameter: {s}"
    let [w, l, r, n, b, gr, gw, h, g] := nums | throw <| IO.userError "invalid TMEM configuration"
    let c : TMem.Config := ⟨w, l, r, n, b, gr, gw, h, g⟩
    IO.ofExcept c.validate
    IO.FS.writeFile path ((← IO.ofExcept (Physical.tmem c)) ++ (if kind == "tmem" then TMem.wrapper c else ""))
    return 0
  | [kind, depth, columns, rows, blocks, lanes, path] =>
    if kind == "se-comp" || kind == "se-comp-core" then
      let some l := depth.toNat? | throw <| IO.userError "invalid SE LANES"
      let some m := columns.toNat? | throw <| IO.userError "invalid SE MW"
      let some n := rows.toNat? | throw <| IO.userError "invalid SE NS"
      let some h := blocks.toNat? | throw <| IO.userError "invalid SE HA"
      if lanes != "0" && lanes != "1" then throw <| IO.userError "SE EXT must be 0 or 1"
      let cfg : SeComposite.Config := ⟨l,m,n,h,lanes == "1"⟩
      IO.FS.writeFile path ((← IO.ofExcept (SeComposite.toVerilog cfg)) ++
        if kind == "se-comp" then SeComposite.wrapper cfg else "")
      return 0
    if kind != "actram" && kind != "actram-core" then
      throw <| IO.userError "expected actram or actram-core"
    let some d := depth.toNat? | throw <| IO.userError "invalid D"
    let some m := columns.toNat? | throw <| IO.userError "invalid MCOLS"
    let some r := rows.toNat? | throw <| IO.userError "invalid ROWS"
    let some b := blocks.toNat? | throw <| IO.userError "invalid BLOCKS"
    let some l := lanes.toNat? | throw <| IO.userError "invalid LANES"
    let cfg : ActRam.Config := ⟨d, m, r, b, l⟩
    IO.ofExcept cfg.validate
    IO.FS.writeFile path ((← IO.ofExcept (Physical.actram cfg)) ++
      (if kind == "actram" then actramWrapper cfg else ""))
    return 0
  | ["float", mulLatency, addLatency, path] =>
    let some lm := mulLatency.toNat? | throw <| IO.userError "LM must be a natural number"
    let some la := addLatency.toNat? | throw <| IO.userError "LA must be a natural number"
    if lm < 2 || la < 4 then throw <| IO.userError "float pipelines require LM >= 2 and LA >= 4"
    IO.FS.writeFile path ((← IO.ofExcept (Physical.floatMultiply lm)) ++ (← IO.ofExcept (Physical.floatAdd la)))
    return 0
  | [kind, slices, lanes, path] =>
    if kind == "quant" || kind == "quant-core" then
      let some d := slices.toNat? | throw <| IO.userError "invalid quantizer D"
      let some l := lanes.toNat? | throw <| IO.userError "invalid quantizer LANES"
      let cfg : Quant.Config := ⟨d,l⟩
      IO.FS.writeFile path ((← IO.ofExcept (Quant.toVerilog cfg)) ++
        if kind == "quant" then Quant.wrapper cfg else "")
      return 0
    if kind == "seq-logic" || kind == "seq-dispatch" then
      let some d := slices.toNat? | throw <| IO.userError "invalid sequencer D"
      let some s := lanes.toNat? | throw <| IO.userError "invalid sequencer S"
      if d == 0 || d % 32 != 0 || s == 0 then
        throw <| IO.userError "sequencer requires D a positive multiple of 32 and S > 0"
      IO.FS.writeFile path (toVerilog (if kind == "seq-dispatch" then SeqDispatch.build d s else SeqLogic.build d s))
      return 0
    if kind == "vtree" || kind == "vtree-core" then
      let some l := slices.toNat? | throw <| IO.userError "invalid VTREE LANES"
      let some a := lanes.toNat? | throw <| IO.userError "invalid VTREE LA"
      let c : VTree.Config := ⟨l, a⟩
      IO.ofExcept c.validate
      IO.FS.writeFile path ((← IO.ofExcept (Physical.vtree c)) ++ if kind == "vtree" then VTree.wrapper c else "")
      return 0
    if kind != "collective" && kind != "collective-core" then
      throw <| IO.userError "expected collective or collective-core"
    let some s := slices.toNat? | throw <| IO.userError "S must be a natural number"
    let some l := lanes.toNat? | throw <| IO.userError "LANES must be a natural number"
    let cfg : Collective.Config := ⟨s, l⟩
    IO.ofExcept cfg.validate
    IO.FS.writeFile path (toVerilog (Collective.build cfg) ++
      (if kind == "collective" then collectiveWrapper cfg else ""))
    return 0
  | ["fpipe", path] =>
    IO.FS.writeFile path ("`define OTPU_SPARKLE_FLOAT\n" ++
      (← IO.ofExcept (Physical.floatMultiply 2)) ++ (← IO.ofExcept (Physical.floatAdd 4)) ++
      (← IO.ofExcept (Physical.floatAdd 4 true)) ++ floatWrappers)
    return 0
  | _ =>
    IO.eprintln "board commands: mem-channel XIDW ARD XRD RUN OQ OD OUTPUT.sv | trace DEPTH QD WIN OUTPUT.sv | async-fifo-family ARD XRD OUTPUT.sv | control D MCOLS LANES ACT_ROWS CORE_KHZ BUILD_ID DDR_MTS TRACE_DEPTH PQ_WIN HAS_TEMP HAS_I2C CHASH DSTEP HOSTCAL OUTPUT.sv"
    IO.eprintln "matrix commands: mxu-test or mxu-physical D MCOLS ROWS FIFO_DEPTH LANES IMPL CL OUTPUT.sv"
    IO.eprintln "fpga-top|fpga-top-physical MCOLS ACT_ROWS VPU_CL MXU_IMPL LANES ULANES CORE_KHZ BUILD_ID DDR_MTS DSTEP PCIE_GEN OUTPUT.sv"
    IO.eprintln "board-assembly|board-native|board-physical D MCOLS ACT_BLOCKS ACT_ROWS TMEM_WORDS IMEM_WORDS FIFO_DEPTH LANES WIN RPB WPB MXU_IMPL MXU_CL VPU_CL ULANES CORE_KHZ BUILD_ID DDR_MTS TRACE_DEPTH TRACE_QD PQ_WIN HAS_I2C CHASH DSTEP HOSTCAL OUTPUT.sv"
    IO.eprintln "usage: opentpu-gen vpu-control LANES CL HAS_SE WBUF OUTPUT.sv | dma D LANES DEPTH HAS_DSTEP OUTPUT.sv | collective S LANES OUTPUT.sv | float LM LA OUTPUT.sv | fpipe OUTPUT.sv | float-convert OUTPUT.sv | qscale LM LA TW OUTPUT.sv | quant D LANES OUTPUT.sv | qread LANES OUTPUT.sv | qwrite LANES OUTPUT.sv | actram D MCOLS ROWS BLOCKS LANES OUTPUT.sv | tmem WORDS LANES NRP NWP WPB GEN_R GEN_W SH_HOST SH_MASK OUTPUT.sv | vtree LANES LA OUTPUT.sv | seq-logic D S OUTPUT.sv | seq-schedule WIN OUTPUT.sv | seq-dispatch D S OUTPUT.sv | seq-window WIN OUTPUT.sv | seq-fetch IMEM_WORDS D S OUTPUT.sv | seq IMEM_WORDS D S WIN OUTPUT.sv"
    return 2
