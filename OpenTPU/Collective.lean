import OpenTPU.Circuit

/-! Native Sparkle implementation of otpu_coll. The read, p, and q stages,
    grant stalls, single-cycle acknowledgement, and cooldown match the RTL.
    `cmds` is flattened with slice 0 in the least-significant 240 bits. -/
namespace OpenTPU.Collective
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  slices : Nat := 1
  lanes : Nat := 8
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  if c.slices == 0 || c.lanes == 0 then
    throw "collective: slices and lanes must be positive"

def build (cfg : Config) : Module := runModule "otpu_coll_sparkle" do
  let sCount := cfg.slices
  let lanes := cfg.lanes
  clocks
  let req ← input "req" sCount
  let cmds ← input "cmds" (sCount * 240)
  let gnt ← input "gnt" 1
  let data ← input "r_data" (sCount * lanes * 32)
  let cmd := fun k lo w => slice cmds (k * 240 + lo) w
  let word := fun k n => cmd k ((7 - n) * 32) 32
  let idle := eq (ref "st") (lit 0 2)
  let run := eq (ref "st") (lit 1 2)
  let ack := eq (ref "st") (lit 2 2)
  let cool := eq (ref "st") (lit 3 2)
  let start ← wire "start" 1 (band idle (eq req (lit (2^sCount - 1) sCount)))
  let empty ← wire "empty" 1 (bor (eq (cmd 0 232 8) (lit 5 8))
    (bor (eq (cmd 0 128 16) (lit 0 16)) (eq (cmd 0 144 16) (lit 0 16))))
  let launch ← wire "launch" 1 (band start (bnot empty))
  let advance ← wire "advance" 1 (band run gnt)
  let issue ← wire "issue" 1 (band advance (ref "issuing"))
  let endCol ← wire "end_col" 1 (bnot (lt (add (ref "c") (lit lanes)) (ref "cols")))
  let endRow ← wire "end_row" 1 (eq (add (ref "r") (lit 1)) (ref "rows"))
  let endSlice ← wire "end_slice" 1 (eq (add (ref "s") (lit 1)) (lit sCount))
  let lastIssue ← wire "last_issue" 1 (band endCol (band endRow endSlice))
  let lastP ← wire "last_p" 1 (band (ref "pv")
    (band (eq (add (ref "ps") (lit 1)) (lit sCount))
      (band (eq (add (ref "pr") (lit 1)) (ref "rows"))
        (bnot (lt (add (ref "pcl") (lit lanes)) (ref "cols"))))))
  let finish ← wire "finish" 1 (band advance (band (ref "qv") (ref "qlast")))
  let nextC ← wire "next_c" 32 (mux endCol (lit 0) (add (ref "c") (lit lanes)))
  let mut nextRrow := ref "rrow"
  for k in [:sCount] do
    nextRrow := mux (band endCol (band (bnot endRow) (eq (ref "s") (lit k))))
      (add (ref "rrow") (word k 4)) nextRrow
    nextRrow := mux (band endCol (band endRow (band (bnot endSlice)
      (eq (add (ref "s") (lit 1)) (lit k))))) (word k 1) nextRrow
  let nrrow ← wire "next_rrow" 32 nextRrow
  reg "st" 2 true [(start, mux empty (lit 2 2) (lit 1 2)),
    (finish, lit 2 2), (ack, lit 3 2), (cool, lit 0 2)]
  reg "rows" 16 false [(launch, cmd 0 128 16)]
  reg "cols" 16 false [(launch, cmd 0 144 16)]
  reg "drs" 32 false [(launch, word 0 5)]
  reg "seg" 32 false [(launch, word 0 6)]
  reg "s" 32 false [(launch, lit 0),
    (band issue (band endCol (band endRow (bnot endSlice))), add (ref "s") (lit 1))]
  reg "ssel" sCount false [(launch, lit 1 sCount),
    (band issue (band endCol (band endRow (bnot endSlice))), .op .shl [ref "ssel", lit 1])]
  reg "r" 32 false [(launch, lit 0),
    (band issue endCol, mux endRow (lit 0) (add (ref "r") (lit 1)))]
  reg "c" 32 false [(launch, lit 0), (issue, nextC)]
  reg "rrow" 32 false [(launch, word 0 1), (issue, nrrow)]
  reg "ra" 32 false [(launch, word 0 1), (issue, add nrrow nextC)]
  let nextWseg := add (ref "wseg") (ref "seg")
  reg "wseg" 32 false [(launch, word 0 2),
    (band issue (band endCol (band endRow (bnot endSlice))), nextWseg)]
  reg "wrow" 32 false [(launch, word 0 2),
    (band issue (band endCol (bnot endRow)), add (ref "wrow") (ref "drs")),
    (band issue (band endCol (band endRow (bnot endSlice))), nextWseg)]
  reg "issuing" 1 false [(launch, lit 1 1), (band issue lastIssue, lit 0 1)]
  reg "rd_on" 1 true [(launch, lit 1 1), (band issue lastIssue, lit 0 1)]
  reg "pv" 1 true [(launch, lit 0 1), (advance, ref "issuing"), (band advance lastP, lit 0 1)]
  reg "qv" 1 true [(launch, lit 0 1), (advance, ref "pv"), (finish, lit 0 1)]
  reg "qlast" 1 false [(advance, lastP)]
  for (p, v) in [("ps", "s"), ("pr", "r"), ("pcl", "c")] do
    reg p 32 false [(advance, ref v)]
  reg "pwa" 32 false [(advance, add (ref "wrow") (ref "c"))]
  let mut readEn := []
  let mut readAddr := []
  for k in [:sCount] do
    for l in [:lanes] do
      let enabled := band (ref "rd_on") (band (bit (ref "ssel") k) (ref s!"rm{l}"))
      readEn := readEn ++ [enabled]
      readAddr := readAddr ++ [mux enabled (add (ref "ra") (lit l)) (lit 0)]
  let mut writeEn := []
  let mut writeAddr := []
  let mut writeData := []
  for l in [:lanes] do
    reg s!"rm{l}" 1 false [(launch, lt (lit l) (cmd 0 144 16)),
      (issue, lt (add nextC (lit l)) (ref "cols"))]
    reg s!"pm{l}" 1 false [(advance, lt (add (ref "c") (lit l)) (ref "cols"))]
    reg s!"qm{l}" 1 false [(advance, ref s!"pm{l}")]
    reg s!"qwl{l}" 32 false [(advance, add (ref "pwa") (lit l))]
    let mut updates := []
    for k in [:sCount] do
      updates := updates ++ [(band advance (eq (ref "ps") (lit k)), slice data ((k * lanes + l) * 32) 32)]
    reg s!"qd{l}" 32 false updates
    let enabled := band run (band (ref "qv") (ref s!"qm{l}") )
    writeEn := writeEn ++ [enabled]
    writeAddr := writeAddr ++ [mux enabled (ref s!"qwl{l}") (lit 0)]
    writeData := writeData ++ [mux enabled (ref s!"qd{l}") (lit 0)]
  output "ack" 1 ack
  output "r_en" (sCount * lanes) (pack readEn)
  output "r_addr" (sCount * lanes * 32) (pack readAddr)
  output "w_en" lanes (pack writeEn)
  output "w_addr" (lanes * 32) (pack writeAddr)
  output "w_data" (lanes * 32) (pack writeData)

end OpenTPU.Collective
