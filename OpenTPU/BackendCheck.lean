import OpenTPU.ActRam
import OpenTPU.Backend

/-! Formal fixtures for the actual byte-bank Verilog lowering. The miter relates
    every storage cell and register, starts with equal but arbitrary RAM contents,
    and asserts that state correspondence and outputs remain equal. -/
open OpenTPU Sparkle.IR.AST Sparkle.IR.Builder Sparkle.Backend.Verilog
open CircuitM OpenTPU.Circuit

private def bankFixture : Module := runModule "banks" do
  clockOnly
  let wa ← input "wa" 2
  let ra ← input "ra" 2
  let wa2 ← input "wa2" 2
  let ra2 ← input "ra2" 2
  let en ← input "en" 40
  let data ← input "data" 320
  let mut reads := []
  for lane in [:40] do
    -- Exercise the 32-byte group limit, different addresses and a singleton.
    let w := if lane < 35 then wa else wa2
    let r := if lane < 39 then ra else ra2
    let q ← emitMemoryComboRead s!"bank{lane}" 2 8 "clk" w
      (slice data (lane * 8) 8) (bit en lane) r
    reads := reads ++ [ref q]
  output "q" 320 (pack reads)

private def miter (m : Module) : String := Id.run do
  let groups := Backend.groups m
  let mut storage := []
  let mut registers := []
  for stmt in m.body do
    match stmt with
    | .memory name aw _ _ _ _ _ _ _ _ _ _ =>
      for addr in [:2^aw] do
        let raw := s!"raw.{Sparkle.Backend.Verilog.sanitizeName name}[{addr}]"
        let mut packed := s!"lowered.{Sparkle.Backend.Verilog.sanitizeName name}[{addr}]"
        for group in groups do
          for lane in [:group.size] do
            if group[lane]!.name == name then
              packed := s!"lowered.{Sparkle.Backend.Verilog.sanitizeName group[0]!.name}_packed0[{addr}][{lane*8} +: 8]"
        storage := storage ++ [s!"({raw} == {packed})"]
    | .register name .. =>
      registers := registers ++ [s!"(raw.{Sparkle.Backend.Verilog.sanitizeName name} == lowered.{Sparkle.Backend.Verilog.sanitizeName name})"]
    | _ => pure ()
  let join := String.intercalate " &&\n    "
  let ports := String.intercalate ",\n  " <| m.inputs.map fun p =>
    s!"input wire [{p.ty.bitWidth-1}:0] {Sparkle.Backend.Verilog.sanitizeName p.name}"
  let connections := String.intercalate "," <| m.inputs.map fun p =>
    s!".{Sparkle.Backend.Verilog.sanitizeName p.name}({Sparkle.Backend.Verilog.sanitizeName p.name})"
  let outs := m.outputs.map fun p =>
    s!"(raw.{Sparkle.Backend.Verilog.sanitizeName p.name} == lowered.{Sparkle.Backend.Verilog.sanitizeName p.name})"
  return s!"module backend_miter({ports}, output wire ok);
  raw_circuit raw({connections});
  packed_circuit lowered({connections});
  wire memory_equal = {join storage};
  logic first = 1'b1;
  always @(posedge clk) first <= 1'b0;
  always_comb if (first) assume(memory_equal);
  assign ok = memory_equal && {join (registers ++ outs)};
endmodule
"

def main (args : List String) : IO UInt32 := do
  let [kind, directory] := args | throw <| IO.userError "usage: backend-check banks|actram DIRECTORY"
  let m ← if kind == "banks" then pure bankFixture
    else if kind == "actram" then pure (ActRam.build ⟨8, 2, 4, 4, 1⟩)
    else throw <| IO.userError "expected banks or actram"
  let dir : System.FilePath := directory
  IO.FS.createDirAll dir
  IO.FS.writeFile (dir / "raw.sv") (toVerilog { m with name := "raw_circuit" })
  IO.FS.writeFile (dir / "packed.sv") (Backend.toPackedVerilog { m with name := "packed_circuit" })
  IO.FS.writeFile (dir / "miter.sv") (miter m)
  return 0
