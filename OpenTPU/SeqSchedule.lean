import OpenTPU.SeqLogic

/-! The sequencer's window selection logic. Candidates are selected by the age
    matrix, with strict start order for MXU/collectives, VPU completion ordering,
    and separate DRAM-only MXU starts and full-dependency releases. -/
namespace OpenTPU.SeqSchedule
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

def validate (slots : Nat) : Except String Unit := do
  if slots < 2 || slots > 32 || !powerOfTwo slots then
    throw "sequencer window must be a power of two in 2..32"

structure Inputs where
  valid : Expr
  started : Expr
  units : Expr
  dependencies : Expr
  dramDependencies : Expr
  older : Expr
  unitReady : Expr
  unitStart : Expr
  unitDone : Expr
  headSlots : Expr
  releaseSlot : Expr
  releasePending : Expr
  newFootprint : Expr
  footprints : Expr

structure Outputs where
  finish : Expr
  free : Expr
  freeSlot : Expr
  newDependencies : Expr
  newDramDependencies : Expr
  sameStarted : Expr
  selected : Expr
  startSlots : Expr
  canStart : Expr
  candidateAny : Expr
  mxuReady : Expr
  collReady : Expr
  canRelease : Expr

def logic (slots : Nat) (a : Inputs) : CircuitM Outputs := do
  let sw := clog2 slots
  let dep := fun i => slice a.dependencies (slots*i) slots
  let depd := fun i => slice a.dramDependencies (slots*i) slots
  let unit := fun i u => bit a.units (5*i+u)
  let mut fins := []
  let mut freeSlot := lit 0 sw
  for i in [:slots] do
    fins := fins ++ [← wire s!"finish{i}" 1 (any ((List.range 5).map fun u =>
      band (bit a.unitDone u) (eq (slice a.headSlots (sw*u) sw) (lit i sw))))]
  let finish ← wire "finish" slots (pack fins)
  -- The reference scans from WIN-1 downwards, with the lowest free slot winning.
  for i in (List.range slots).reverse do
    freeSlot := mux (bnot (bit a.valid i)) (lit i sw) freeSlot
  freeSlot ← wire "free_slot" sw freeSlot
  let free ← wire "have_free" 1 (bnot (eq a.valid (lit (2^slots-1) slots)))
  let mut ndeps := []
  let mut ndepsD := []
  for i in [:slots] do
    let cf ← wire s!"conflict{i}" 2 (conflicts a.newFootprint (slice a.footprints (322*i) 322))
    let live := band (bit a.valid i) (bnot (bit finish i))
    ndeps := ndeps ++ [band live (bit cf 1)]
    ndepsD := ndepsD ++ [band live (bit cf 0)]
  let newDeps ← wire "ndep" slots (pack ndeps)
  let newDepsD ← wire "ndepd" slots (pack ndepsD)
  let mut same := #[]
  for u in [:5] do
    let mask := pack ((List.range slots).map fun i =>
      if u == 3 then lit 0 1 else every [bit a.valid i, bit a.started i, unit i u])
    same := same.push (← wire s!"same_started{u}" slots mask)
  let mut mrdy := []
  let mut crdy := []
  for i in [:slots] do
    mrdy := mrdy ++ [eq (band (depd i) (bnot same[1]!)) (lit 0 slots)]
    crdy := crdy ++ [eq (band (dep i) (bnot same[4]!)) (lit 0 slots)]
  let mr ← wire "mrdy" slots (pack mrdy)
  let cr ← wire "crdy" slots (pack crdy)
  let mut selected := []
  let mut startSlots := []
  let mut canStart := []
  let mut candAny := []
  for u in [:5] do
    let mut cb := []
    for i in [:slots] do
      let ready := if u == 1 || u == 4 then lit 1 1 else
        eq (band (dep i) (bnot same[u]!)) (lit 0 slots)
      cb := cb ++ [every [bit a.valid i, bnot (bit a.started i), unit i u, ready]]
    let cand ← wire s!"candidate{u}" slots (pack cb)
    let chosen ← wire s!"selected{u}" slots (pack ((List.range slots).map fun i =>
      band (bit cand i) (eq (band (slice a.older (slots*i) slots) cand) (lit 0 slots))))
    let start ← wire s!"start_slot{u}" sw (((List.range slots).map fun i =>
      mux (bit chosen i) (lit i sw) (lit 0 sw)).foldl bor (lit 0 sw))
    let has ← wire s!"candidate_any{u}" 1 (nz cand slots)
    let ready := if u == 1 then nz (band chosen mr) slots else
      if u == 4 then nz (band chosen cr) slots else has
    let can ← wire s!"can_start{u}" 1 (every [ready, bit a.unitReady u, bnot (bit a.unitStart u)])
    selected := selected ++ [chosen]
    startSlots := startSlots ++ [start]
    canStart := canStart ++ [can]
    candAny := candAny ++ [has]
  let releaseDeps ← wire "release_dependencies" slots
    (indexed ((List.range slots).map dep) a.releaseSlot sw slots)
  let canRelease ← wire "can_release" 1 (band a.releasePending
    (eq (band releaseDeps (bnot same[1]!)) (lit 0 slots)))
  return ⟨finish, free, freeSlot, newDeps, newDepsD, pack same.toList, pack selected,
    pack startSlots, pack canStart, pack candAny, mr, cr, canRelease⟩

def build (slots : Nat) : Module := runModule "otpu_seq_schedule_sparkle" do
  let sw := clog2 slots
  let a : Inputs := {
    valid := ← input "sv" slots, started := ← input "sstarted" slots,
    units := ← input "soh" (slots*5), dependencies := ← input "sdep" (slots*slots),
    dramDependencies := ← input "sdepd" (slots*slots), older := ← input "older" (slots*slots),
    unitReady := ← input "urdy" 5, unitStart := ← input "ustart" 5, unitDone := ← input "udone" 5,
    headSlots := ← input "head_slots" (5*sw), releaseSlot := ← input "rel_slot" sw,
    releasePending := ← input "rel_pending" 1, newFootprint := ← input "c_fp" 322,
    footprints := ← input "sfp" (322*slots) }
  let o ← logic slots a
  output "fin" slots o.finish
  output "free" 1 o.free
  output "free_idx" sw o.freeSlot
  output "deps" slots o.newDependencies
  output "dram_deps" slots o.newDramDependencies
  output "same" (5*slots) o.sameStarted
  output "sel" (5*slots) o.selected
  output "starts" (5*sw) o.startSlots
  output "can" 5 o.canStart
  output "candidates" 5 o.candidateAny
  output "mxu_ready" slots o.mxuReady
  output "coll_ready" slots o.collReady
  output "can_rel" 1 o.canRelease

end OpenTPU.SeqSchedule
