import OpenTPU.TopConfig

/-! Native simulation-top wiring. Boundary modules are structural ABI bridges;
AXI memory models remain explicit external simulation dependencies. -/
namespace OpenTPU.Top
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

def inputs : List (String × Nat) :=
  [("clk",1),("sys_rst",1),("rst",1),("rinit",256),("ld_start",1),("ld_addr",32),("ld_n",32),("dump",1)]
def outputs (c : Config) : List (String × Nat) :=
  [("ld_busy",1),("all_halted",1),("any_error",1),("icount",32*c.slice.slices)]
def contract (name : String) (ins outs : List (String × Nat)) : Module :=
  {name,inputs:=ins.map fun (name,w) => {name,ty:=.bitVector w},
   outputs:=outs.map fun (name,w) => {name,ty:=.bitVector w},wires:=[],body:=[],isPrimitive:=true}
def sliceContract (c : Config) (sid : Nat) : Module :=
  contract s!"otpu_top_slice_{sid}" ((Slice.inputPorts (c.at sid)).filter (fun p => p.1 != "slice_perf_win"))
    (Slice.outputPorts (c.at sid))
def dramContract (c : Config) (sid : Nat) : Module :=
  let m := Dram.build c.dram
  {m with
    name := s!"otpu_top_dram_{sid}"
    inputs:=(m.inputs.filter fun p => !(p.name.startsWith "poke_")) ++ [{name:="dump",ty:=.bitVector 1}],
    wires:=[],body:=[],isPrimitive:=true}
def memoryContract (c : Config) : Module :=
  let m := NativeDram.build c.memory
  {m with name:="otpu_native_dram",wires:=[],body:=[],isPrimitive:=true}
def modelContract (c : Config) (sid : Nat) : Module :=
  contract s!"otpu_top_model_{sid}"
    ([("clk",1),("rst",1),("dump",1)] ++ (if c.axi == 1 then [("run_rst",1)] else []) ++
    [("n_cvalid",2),("n_cwe",2),("n_caddr",50),("n_wvalid",2),("n_wdata",1024),("n_wmask",128)])
    [("n_cready",2),("n_wready",2),("n_rvalid",2),("n_rdata",1024),("n_wdone",32)]

private def declared (name : String) (w : Nat) : CircuitM Unit := do
  let m ← getModule
  if let some p := (m.inputs ++ m.outputs ++ m.wires).find? (·.name == name) then
    if p.ty.bitWidth != w then panic! s!"top conflicting width {name}"
  else setModule (m.addWire {name,ty:=.bitVector w})
private def named (m : Module) (instanceName : String) (name : String → String) : CircuitM Unit := do
  for p in m.inputs ++ m.outputs do declared (name p.name) p.ty.bitWidth
  emitInstance m.name instanceName ((m.inputs ++ m.outputs).map fun p => (p.name,ref (name p.name)))
private def global (n : String) : Bool :=
  ["clk","sys_rst","rst","rinit","ld_start","ld_addr","ld_n","dump", "coll_ack","coll_wen","coll_waddr","coll_wdata","coll_gnt"].contains n

def build (c : Config) : Except String Module := do
  c.validate
  return runModule "otpu_top_sparkle" do
    for (n,w) in inputs do let _ ← input n w
    let localName := fun s n => if global n then n else s!"s{s}_{n}"
    for s in [:c.slice.slices] do
      named (sliceContract c s) s!"u_slice_{s}" (localName s)
      if c.axi == 0 then
        for n in ["a_rdy","b_rdy","sw_rdy","wr_idle"] do emitAssign (localName s n) (lit 1 1)
        named (dramContract c s) s!"u_dram_{s}" (localName s)
      else
        let flush := s!"s{s}_a_flush"
        declared flush 1
        emitAssign flush (bor (ref "rst") (bor (ref "ld_start") (ref (localName s "a_inval"))))
        named (memoryContract c) s!"u_adapt_{s}" fun n =>
          if n == "rst" then "sys_rst"
          else if n == "clk" then n
          else s!"s{s}_{if n.endsWith "_x" then (n.dropEnd 2).toString else n}"
        named (modelContract c s) s!"u_model_{s}" fun n =>
          if n == "rst" then "sys_rst" else if n == "run_rst" then "rst"
          else if n == "clk" || n == "dump" then n else s!"s{s}_{n}"
    let all := fun n => (List.range c.slice.slices).foldl (fun a s => band a (ref (localName s n))) (lit 1 1)
    let any := fun n => (List.range c.slice.slices).foldl (fun a s => bor a (ref (localName s n))) (lit 0 1)
    emitAssign "coll_gnt" (all "coll_gnt_local")
    let coll := Collective.build c.collective
    for p in coll.inputs ++ coll.outputs do
      if !["clk","rst"].contains p.name then declared s!"collective_{p.name}" p.ty.bitWidth
    for (p,n) in [("req","coll_req"),("cmds","coll_cmd"),("r_data","coll_rdata")] do
      emitAssign s!"collective_{p}" (pack ((List.range c.slice.slices).map fun s => ref (localName s n)))
    emitAssign "collective_gnt" (ref "coll_gnt")
    for (p,n) in [("ack","coll_ack"),("w_en","coll_wen"),("w_addr","coll_waddr"),("w_data","coll_wdata")] do
      emitAssign n (ref s!"collective_{p}")
    for s in [:c.slice.slices] do
      emitAssign (localName s "coll_ren") (slice (ref "collective_r_en") (s*c.slice.lanes) c.slice.lanes)
      emitAssign (localName s "coll_raddr") (slice (ref "collective_r_addr") (s*c.slice.lanes*32) (c.slice.lanes*32))
    named coll "u_coll" fun n => if ["clk","rst"].contains n then n else s!"collective_{n}"
    output "ld_busy" 1 (any "ld_busy")
    output "all_halted" 1 (all "halted")
    output "any_error" 1 (any "error")
    output "icount" (32*c.slice.slices) (pack ((List.range c.slice.slices).map fun s => ref (localName s "icount")))
end OpenTPU.Top
