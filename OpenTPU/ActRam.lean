import OpenTPU.Circuit

/-! Activation RAM: native Sparkle byte banks, scale banks and quantizer write
    pipeline. The synchronous read is expressed as RAM + enabled output register,
    preserving old-data semantics even on a write/read collision. -/
namespace OpenTPU.ActRam
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  depth : Nat := 32
  columns : Nat := 8
  rows : Nat := 8
  blocks : Nat := 64
  lanes : Nat := 8
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  if c.depth < 2 || (c.depth > 32 && c.depth % 32 != 0) then
    throw "ACT RAM: D must be >= 2 and a multiple of 32 when above 32"
  if !powerOfTwo c.blocks || c.blocks < 2 || c.blocks > 65536 then
    throw "ACT RAM: BLOCKS must be a power of two in 2..65536"
  if clog2 c.depth + clog2 c.blocks > 32 then
    throw "ACT RAM: packed write address exceeds 32 bits"
  if c.columns == 0 || c.columns > 256 || c.rows == 0 || c.rows > 256 || c.rows % c.columns != 0 then
    throw "ACT RAM: ROWS must be a positive multiple of MCOLS, both <= 256"
  if c.rows > c.columns && !powerOfTwo c.columns then
    throw "ACT RAM: multiple groups require power-of-two MCOLS"
  if c.lanes == 0 || c.depth % c.lanes != 0 then
    throw "ACT RAM: LANES must divide D"

/-- Select a column. For a single non-power-of-two group, enumerate the byte-sized
    row domain rather than relying on a hardware division primitive. -/
private def isColumn (c : Config) (row : Expr) (j : Nat) : Expr :=
  if c.columns == 1 then lit 1 1
  else if powerOfTwo c.columns then eq (slice row 0 (clog2 c.columns)) (lit j (clog2 c.columns))
  else (List.range 256).foldl (fun a r =>
    if r % c.columns == j then bor a (eq row (lit r 8)) else a) (lit 0 1)

def build (c : Config) : Module := runModule "otpu_actram_sparkle" do
  clockOnly
  for (name, width) in [("we", c.lanes), ("w_row", 8), ("w_idx", 32),
      ("w_data", c.lanes * 8), ("w_dup", 1), ("w_off", 8), ("swe", 1),
      ("s_row", 8), ("s_blk", 16), ("s_data", 32), ("ren", 1), ("r_use", 1),
      ("r_blk", 16), ("r_blk2", 16), ("r_hi", c.columns), ("r_grp", 8)] do
    let _ ← input name width
  let dw := clog2 c.depth
  let bw := clog2 c.blocks
  let groups := c.rows / c.columns
  let gw := if groups > 1 then clog2 groups else 0
  let aw := bw + gw
  let one := lit 1 1
  for (name, width) in [("we", c.lanes), ("w_row", 8), ("w_idx", dw + bw),
      ("w_data", c.lanes * 8), ("w_dup", 1), ("w_off", 8), ("swe", 1),
      ("s_row", 8), ("s_blk", bw), ("s_data", 32)] do
    let v := if name == "w_idx" || name == "s_blk" then slice (ref name) 0 width else ref name
    let i ← clocked s!"{name}_i" width one v
    let _ ← clocked s!"{name}_h" width one i
  let sb ← clocked "sb" bw one (ref "s_blk_h")
  let sd ← clocked "sd" 32 one (ref "s_data_h")
  let mut byteEn := #[]
  let mut byteData := #[]
  -- Enable indexing wraps in the DW-sized domain. Data indexing in the reference
  -- is widened by its multiplication by 8: out-of-range bytes are discarded.
  -- Keep that distinction even for unaligned writes outside QACT's contract.
  let span := 2^dw
  let paddedEn := if c.lanes == span then ref "we_h"
    else Expr.concat [lit 0 (span - c.lanes), ref "we_h"]
  let paddedData := if c.lanes == span then ref "w_data_h"
    else Expr.concat [lit 0 ((span - c.lanes) * 8), ref "w_data_h"]
  let index := slice (ref "w_idx_h") 0 dw
  let rotatedEn ← wire "rotated_en" (2 * span)
    (.op .shl [.concat [paddedEn, paddedEn], index])
  let placedData ← wire "placed_data" (span * 8)
    (.op .shl [paddedData, .concat [index, lit 0 3]])
  for b in [:c.depth] do
    byteEn := byteEn.push (← clocked s!"wbe{b}" 1 one (bit rotatedEn (span + b)))
    byteData := byteData.push (← clocked s!"wd{b}" 8 one (slice placedData (b * 8) 8))
  let dupW ← wire "dup_w_row" 8 (add (ref "w_row_h") (ref "w_off_h"))
  let dupS ← wire "dup_s_row" 8 (add (ref "s_row_h") (ref "w_off_h"))
  let group := fun row => if groups > 1 then slice row (clog2 c.columns) gw else lit 0 1
  let address := fun grp blk => if groups > 1 then Expr.concat [grp, blk] else blk
  let dupWi ← wire "dup_w_row_i" 8 (add (ref "w_row_i") (ref "w_off_i"))
  let dupSi ← wire "dup_s_row_i" 8 (add (ref "s_row_i") (ref "w_off_i"))
  let mut hazard := lit 0 1
  let mut rd := []
  let mut scales := []
  for j in [:c.columns] do
    let wFirst := isColumn c (ref "w_row_h") j
    let sFirst := isColumn c (ref "s_row_h") j
    let wselN := band (bor wFirst (band (ref "w_dup_h") (isColumn c dupW j)))
      (bnot (eq (ref "we_h") (lit 0 c.lanes)))
    let sselN := band (ref "swe_h") (bor sFirst (band (ref "w_dup_h") (isColumn c dupS j)))
    let wgrp := mux wFirst (group (ref "w_row_h")) (group dupW)
    let sgrp := mux sFirst (group (ref "s_row_h")) (group dupS)
    let ssel ← clocked s!"ssel{j}" 1 one sselN
    let sg ← clocked s!"sg{j}" (max 1 gw) one sgrp
    let rb := mux (bit (ref "r_hi") j) (slice (ref "r_blk2") 0 bw) (slice (ref "r_blk") 0 bw)
    let ra ← wire s!"ra{j}" aw (address (slice (ref "r_grp") 0 (max 1 gw)) rb)
    let sa ← wire s!"sa{j}" aw (address sg sb)
    let wiFirst := isColumn c (ref "w_row_i") j
    let siFirst := isColumn c (ref "s_row_i") j
    let wiSelect := band (bor wiFirst (band (ref "w_dup_i") (isColumn c dupWi j)))
      (bnot (eq (ref "we_i") (lit 0 c.lanes)))
    let siSelect := band (ref "swe_i") (bor siFirst (band (ref "w_dup_i") (isColumn c dupSi j)))
    let wiAddr := address (mux wiFirst (group (ref "w_row_i")) (group dupWi))
      (slice (ref "w_idx_i") dw bw)
    let siAddr := address (mux siFirst (group (ref "s_row_i")) (group dupSi)) (ref "s_blk_i")
    let whAddr := address wgrp (slice (ref "w_idx_h") dw bw)
    let shAddr := address sgrp (ref "s_blk_h")
    for (enable, addr) in [(wiSelect, wiAddr), (siSelect, siAddr),
        (wselN, whAddr), (sselN, shAddr), (ssel, sa)] do
      hazard := bor hazard (band enable (eq addr ra))
    let scale ← emitMemoryComboRead s!"scale{j}" aw 32 "clk" sa sd ssel ra
    scales := scales ++ [← clocked s!"rs{j}" 32 (ref "ren") (ref scale)]
    let pb := min c.depth 32
    for p in [:c.depth / pb] do
      -- Replicate the third-stage address and enable per physical piece, as in RTL.
      let wb ← clocked s!"wb{j}_{p}" bw one (slice (ref "w_idx_h") dw bw)
      let ws ← clocked s!"wsel{j}_{p}" 1 one wselN
      let wg ← clocked s!"wg{j}_{p}" (max 1 gw) one wgrp
      let wa ← wire s!"wa{j}_{p}" aw (address wg wb)
      if p == 0 then hazard := bor hazard (band ws (eq wa ra))
      for b in [:pb] do
        let byte := p * pb + b
        let data ← emitMemoryComboRead s!"act{j}_{byte}" aw 8 "clk" wa byteData[byte]!
          (band ws byteEn[byte]!) ra
        rd := rd ++ [← clocked s!"rd{j}_{byte}" 8 (ref "ren") (ref data)]
  output "hazard" 1 hazard
  output "r_data" (c.columns * c.depth * 8) (pack rd)
  output "r_scale" (c.columns * 32) (pack scales)

end OpenTPU.ActRam
