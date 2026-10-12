import OpenTPU.Circuit

/-! Banked tensor scratchpad. Requests route to RAM before grants; pending writes
    bypass the RAM read, and each granted lane keeps its last returned word.
    Shared copies prioritize the host, then guests in increasing port order. -/
namespace OpenTPU.TMem
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  words : Nat := 65536
  lanes : Nat := 8
  readPorts : Nat := 8
  writePorts : Nat := 4
  writesPerBank : Nat := 1
  generalRead : Nat := 1
  generalWrite : Nat := 2
  shareHost : Nat := 1
  shareMask : Nat := 160
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  if c.lanes < 2 || !powerOfTwo c.lanes then
    throw "TMEM: LANES must be a power of two >= 2"
  if !powerOfTwo c.words || c.words <= c.lanes || clog2 c.words > 32 then
    throw "TMEM: WORDS must be a power of two > LANES, with at most 32 address bits"
  if c.readPorts == 0 || c.writePorts == 0 || c.readPorts > 32 || c.writePorts > 32 then
    throw "TMEM: read/write port counts must be in 1..32"
  if c.writesPerBank == 0 || c.writesPerBank > c.writePorts * c.lanes then
    throw "TMEM: WPB must be in 1..NWP*LANES"
  if c.shareHost >= c.readPorts || c.shareMask.testBit c.shareHost || c.shareMask >= 2^c.readPorts then
    throw "TMEM: shared guests must be valid ports and cannot include the host"
  if c.generalRead >= 2^c.readPorts || c.generalWrite >= 2^c.writePorts then
    throw "TMEM: GEN_R/GEN_W masks exceed their port counts"

private def field (name : String) (width index : Nat) : Expr :=
  slice (ref name) (width * index) width

private def any (value : Expr) (width : Nat) : Expr := bnot (eq value (lit 0 width))

/-- One shared barrel network puts contiguous lanes into bank order. -/
private def rotate (name : String) (lanes width : Nat) (value rotation : Expr) : CircuitM Expr := do
  let mut v := value
  -- Cyclic stages commute. Group the wide write-data muxes high-bit first;
  -- retain low-bit-first request routing. This preserves each pipeline bit
  -- while improving the default xc7 LUT mapping without changing RAM or hints.
  let stages := List.range (clog2 lanes)
  for k in (if width == 32 then stages.reverse else stages) do
    let chunks := (List.range lanes).map fun b =>
      slice v (((b + lanes - 2^k) % lanes) * width) width
    v ← wire s!"{name}_{k}" (lanes * width) (mux (bit rotation k) (pack chunks) v)
  return v

def build (c : Config) : Module := runModule "otpu_tmem_sparkle" do
  clockOnly
  for (name, width) in [("r_en", c.readPorts*c.lanes), ("r_req", c.readPorts*c.lanes),
      ("r_addr", c.readPorts*c.lanes*32), ("w_en", c.writePorts*c.lanes),
      ("w_req", c.writePorts*c.lanes), ("w_gnt", c.writePorts),
      ("w_addr", c.writePorts*c.lanes*32), ("w_data", c.writePorts*c.lanes*32)] do
    let _ ← input name width
  let bw := clog2 c.lanes
  let iw := clog2 (c.words / c.lanes)
  let one := lit 1 1
  let mut selectedV := #[]
  let mut selectedA := #[]
  let mut selectedD := #[]
  if c.writesPerBank == 1 then
    let mut portV := #[]
    let mut portA := #[]
    let mut portD := #[]
    for p in [:c.writePorts] do
      let a0 := field "w_addr" 32 (p*c.lanes)
      let rot := slice a0 0 bw
      let rv ← rotate s!"wv{p}" c.lanes 1 (field "w_req" c.lanes p) rot
      let rd ← rotate s!"wd{p}" c.lanes 32 (field "w_data" (c.lanes*32) p) rot
      for b in [:c.lanes] do
        let mut v := bit rv b
        let mut a := add (slice a0 bw iw) (mux (lt (lit b bw) rot) (lit 1 iw) (lit 0 iw))
        let mut d := slice rd (b*32) 32
        if c.generalWrite.testBit p then
          v := lit 0 1; a := lit 0 iw; d := lit 0 32
          for l in [:c.lanes] do
            let addr := field "w_addr" 32 (p*c.lanes+l)
            let hit := band (field "w_req" 1 (p*c.lanes+l)) (eq (slice addr 0 bw) (lit b bw))
            v := bor v hit
            a := bor a (mux hit (slice addr bw iw) (lit 0 iw))
            d := bor d (mux hit (field "w_data" 32 (p*c.lanes+l)) (lit 0 32))
        portV := portV.push (← wire s!"wpv{p}_{b}" 1 v)
        portA := portA.push (← wire s!"wpa{p}_{b}" iw a)
        portD := portD.push (← wire s!"wpd{p}_{b}" 32 d)
    for b in [:c.lanes] do
      let mut v := lit 0 1
      let mut a := lit 0 iw
      let mut d := lit 0 32
      for p in [:c.writePorts] do
        let hit := band (field "w_gnt" 1 p) portV[p*c.lanes+b]!
        v := bor v hit
        a := bor a (mux hit portA[p*c.lanes+b]! (lit 0 iw))
        d := bor d (mux hit portD[p*c.lanes+b]! (lit 0 32))
      selectedV := selectedV.push v
      selectedA := selectedA.push a
      selectedD := selectedD.push d
  else
    -- Select the first WPB writes in port/lane order; RAM and bypass use
    -- increasing slot order, so the last selected write to an address wins.
    let cw := clog2 (c.writesPerBank+1)
    for b in [:c.lanes] do
      let mut count := lit 0 cw
      let mut vs := Array.replicate c.writesPerBank (lit 0 1)
      let mut addresses := Array.replicate c.writesPerBank (lit 0 iw)
      let mut data := Array.replicate c.writesPerBank (lit 0 32)
      for i in [:c.writePorts*c.lanes] do
        let addr := field "w_addr" 32 i
        let hit ← wire s!"wh{b}_{i}" 1 (band (field "w_en" 1 i)
          (band (eq (slice addr 0 bw) (lit b bw)) (lt count (lit c.writesPerBank cw))))
        for w in [:c.writesPerBank] do
          let take := band hit (eq count (lit w cw))
          vs := vs.modify w (bor · take)
          -- count advances once per selected lane, so each slot's takes are
          -- mutually exclusive. Masked ORs avoid long priority mux chains.
          addresses := addresses.modify w (fun old => bor old (mux take (slice addr bw iw) (lit 0 iw)))
          data := data.modify w (fun old => bor old (mux take (field "w_data" 32 i) (lit 0 32)))
        count ← wire s!"wc{b}_{i}" cw (mux hit (add count (lit 1 cw)) count)
      selectedV := selectedV ++ vs
      selectedA := selectedA ++ addresses
      selectedD := selectedD ++ data
  let mut pv := #[]
  let mut pa := #[]
  let mut pd := #[]
  let mut delayed := #[]
  for i in [:c.lanes*c.writesPerBank] do
    -- Share each selected slot between the pipeline and the dump interface.
    -- Inlining all multiwrite muxes into one packed output can exceed the
    -- Verilog preprocessor's per-line token limit at sixteen lanes.
    selectedV := selectedV.set! i (← wire s!"selected_v{i}" 1 selectedV[i]!)
    selectedA := selectedA.set! i (← wire s!"selected_a{i}" iw selectedA[i]!)
    selectedD := selectedD.set! i (← wire s!"selected_d{i}" 32 selectedD[i]!)
    pv := pv.push (← clocked s!"pwv{i}" 1 one selectedV[i]!)
    pa := pa.push (← clocked s!"pwa{i}" iw one selectedA[i]!)
    pd := pd.push (← clocked s!"pwd{i}" 32 one selectedD[i]!)
    delayed := delayed.push (← clocked s!"pd{i}" 32 one pd[i]!)
  -- Expose the logical writes for simulation dumps, without duplicating routing.
  output "selected_valid" (c.lanes*c.writesPerBank) (pack selectedV.toList)
  output "selected_address" (c.lanes*c.writesPerBank*iw) (pack selectedA.toList)
  output "selected_data" (c.lanes*c.writesPerBank*32) (pack selectedD.toList)
  let mut requests := #[]
  let mut addresses := #[]
  for p in [:c.readPorts] do
    let a0 := field "r_addr" 32 (p*c.lanes)
    let rot := slice a0 0 bw
    let rv ← rotate s!"rv{p}" c.lanes 1 (field "r_req" c.lanes p) rot
    for b in [:c.lanes] do
      let mut en := bit rv b
      let mut addr := add (slice a0 bw iw) (mux (lt (lit b bw) rot) (lit 1 iw) (lit 0 iw))
      if c.generalRead.testBit p then
        en := lit 0 1; addr := lit 0 iw
        for l in [:c.lanes] do
          let a := field "r_addr" 32 (p*c.lanes+l)
          let hit := band (field "r_req" 1 (p*c.lanes+l)) (eq (slice a 0 bw) (lit b bw))
          en := bor en hit
          addr := bor addr (mux hit (slice a bw iw) (lit 0 iw))
      requests := requests.push (← wire s!"rbe{p}_{b}" 1 en)
      addresses := addresses.push (← wire s!"rba{p}_{b}" iw addr)
  let mut banks := Array.replicate (c.readPorts*c.lanes) (lit 0 32)
  for p in [:c.readPorts] do
    if c.shareMask.testBit p then continue
    for b in [:c.lanes] do
      let mut en := requests[p*c.lanes+b]!
      let mut addr := addresses[p*c.lanes+b]!
      if p == c.shareHost then
        let mut taken := any (field "r_req" c.lanes p) c.lanes
        for g in [:c.readPorts] do
          if c.shareMask.testBit g then
            let req := any (field "r_req" c.lanes g) c.lanes
            let take := band (bnot taken) req
            en := mux take requests[g*c.lanes+b]! en
            addr := mux take addresses[g*c.lanes+b]! addr
            taken := bor taken req
      en ← wire s!"be{p}_{b}" 1 en
      addr ← wire s!"ba{p}_{b}" iw addr
      let i := b*c.writesPerBank
      let name := s!"mem{p}_{b}"
      let rd := s!"memdata{p}_{b}"
      let extra := (List.range (c.writesPerBank-1)).map fun w =>
        (pa[i+w+1]!, pd[i+w+1]!, pv[i+w+1]!)
      let m ← getModule
      setModule <| (m.addWire { name := rd, ty := .bitVector 32 }).addStmt
        (.memory name iw 32 "clk" pa[i]! pd[i]! pv[i]! addr rd true extra [])
      let mut q ← clocked s!"q{p}_{b}" 32 en (ref rd)
      for w in [:c.writesPerBank] do
        let hit ← clocked s!"bh{p}_{b}_{w}" 1 en (band pv[i+w]! (eq pa[i+w]! addr))
        q := mux hit delayed[i+w]! q
      banks := banks.set! (p*c.lanes+b) (← wire s!"qb{p}_{b}" 32 q)
  let mut outputs := []
  for p in [:c.readPorts] do
    let owner := if c.shareMask.testBit p then c.shareHost else p
    for l in [:c.lanes] do
      let i := p*c.lanes+l
      let grant := field "r_en" 1 i
      let fresh ← clocked s!"fresh{i}" 1 one grant
      let sel ← if c.generalRead.testBit p then
          clocked s!"sel{i}" bw grant (slice (field "r_addr" 32 i) 0 bw)
        else do
          let rot ← clocked s!"rot{i}" bw (any (field "r_en" c.lanes p) c.lanes)
            (slice (field "r_addr" 32 (p*c.lanes)) 0 bw)
          wire s!"sel{i}" bw (add rot (lit l bw))
      -- Dynamic indexing lowers to a balanced selection network. A chain of
      -- equality muxes has the same behavior but costs considerably more LUTs.
      let data := pack ((List.range c.lanes).map fun b => banks[owner*c.lanes+b]!)
      let q ← wire s!"lq{i}" 32 (.op .shr [data, .concat [sel, lit 0 5]])
      let held ← clocked s!"held{i}" 32 fresh q
      outputs := outputs ++ [mux fresh q held]
  output "r_data" (c.readPorts*c.lanes*32) (pack outputs)

end OpenTPU.TMem
