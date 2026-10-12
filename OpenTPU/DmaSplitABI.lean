import OpenTPU.DmaSplit

namespace OpenTPU.DmaSplit

/-- Packed AXI fields preserve their bit ordering across the original board ABI. -/
def wrapper (c : Config) : Except String String := do
  let design ← build c
  let some top := design.modules.find? (·.name == design.topModule) | throw "DMA split top missing"
  let port := fun direction (p : Sparkle.IR.AST.Port) =>
    s!"  {direction} wire [{p.ty.bitWidth-1}:0] {p.name}"
  let ports := top.inputs.map (port "input") ++ top.outputs.map (port "output")
  let connections := (top.inputs ++ top.outputs).map fun p => s!".{p.name}({p.name})"
  return s!"
module otpu_dma_split #(
  parameter bit REG={if c.registered then 1 else 0},
  parameter int IDW={c.idWidth}, DW={c.dataWidth}
)(
{String.intercalate ",\n" ports}
);
  initial if(REG!={if c.registered then 1 else 0} || IDW!={c.idWidth} || DW!={c.dataWidth})
    $fatal(1, \"Sparkle DMA split configuration mismatch; regenerate\");
  otpu_dma_split_sparkle impl({String.intercalate "," connections});
endmodule
"

end OpenTPU.DmaSplit
