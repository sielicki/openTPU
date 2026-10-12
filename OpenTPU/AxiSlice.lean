import OpenTPU.BoardFifo

namespace OpenTPU.AxiSlice
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  registered : Bool := true
  idWidth : Nat := 4
  dataWidth : Nat := 128
  deriving Repr

/-- Channel payloads in most-significant-field-first order. -/
def channels (c : Config) : List (String × Bool × List (String × Nat)) :=
  [("aw",false,[("id",c.idWidth),("addr",32),("len",8)]),
   ("w",false,[("data",c.dataWidth),("strb",c.dataWidth/8),("last",1)]),
   ("b",true,[("id",c.idWidth),("resp",2)]),
   ("ar",false,[("id",c.idWidth),("addr",32),("len",8)]),
   ("r",true,[("id",c.idWidth),("data",c.dataWidth),("resp",2),("last",1)])]

def build (c : Config) : Except String Design := do
  if c.idWidth == 0 || c.dataWidth == 0 || c.dataWidth % 8 != 0 then
    throw "AXI slice requires positive ID width and a positive byte-multiple data width"
  let widths := ((channels c).map fun (_,_,fs) => (fs.map Prod.snd).foldl (·+·) 0).eraseDups
  let modules ← if c.registered then widths.mapM (fun w => do
    return { (← BoardFifo.skid w) with name := s!"otpu_axi_skid_{w}" }) else pure []
  let top := runModule "otpu_axi_slice_sparkle" do
    let _ ← input "clk" 1
    let _ ← input "rst" 1
    for (channel,reverse,fields) in channels c do
      let origin :=  if reverse then "m" else "s"
      let dest := if reverse then "s" else "m"
      let valid ← input s!"{origin}_{channel}valid" 1
      let ready ← input s!"{dest}_{channel}ready" 1
      let mut values := []
      for (field,w) in fields do
        let v ← input s!"{origin}_{channel}{field}" w
        values := values ++ [v]
      let width := (fields.map Prod.snd).foldl (·+·) 0
      let mut result := Expr.concat values
      let mut outputValid := valid
      let mut outputReady := ready
      if c.registered then
        let m ← getModule
        setModule <| (m.addWire {name := s!"{channel}_data",ty := .bitVector width}).addWire
          {name := s!"{channel}_valid",ty := .bitVector 1} |>.addWire
          {name := s!"{channel}_ready",ty := .bitVector 1}
        result := ref s!"{channel}_data"
        outputValid := ref s!"{channel}_valid"
        outputReady := ref s!"{channel}_ready"
        emitInstance s!"otpu_axi_skid_{width}" s!"u_{channel}"
          [("clk",ref "clk"),("rst",ref "rst"),("s_valid",valid),("s_ready",outputReady),
           ("s_data",.concat values),("m_valid",outputValid),("m_ready",ready),("m_data",result)]
      output s!"{dest}_{channel}valid" 1 outputValid
      output s!"{origin}_{channel}ready" 1 outputReady
      let mut offset := width
      for (field,w) in fields do
        offset := offset-w
        output s!"{dest}_{channel}{field}" w (slice result offset w)
  return {topModule := top.name,modules := modules ++ [top]}

end OpenTPU.AxiSlice
