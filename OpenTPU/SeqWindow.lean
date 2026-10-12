import OpenTPU.SeqSchedule

/-! Stateful instruction window. Slot allocation, age/dependency matrices,
    in-order completion queues, command copies, and profiling readiness state.
    Command RAMs have asynchronous reads followed by explicit enabled registers,
    preserving old-data reads on a simultaneous dispatch/write. -/
namespace OpenTPU.SeqWindow
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

structure Inputs where
  valid : Expr
  command : Expr
  unit : Expr
  footprint : Expr
  ready : Expr
  done : Expr
  cycle : Expr
  eventCycle : Expr

structure Outputs where
  commands : Expr
  start : Expr
  release : Expr
  valid : Expr
  free : Expr
  freeSlot : Expr
  go : Expr
  finish : Expr
  releaseSlot : Expr
  canRelease : Expr
  commandSlots : Expr
  readyCycles : Expr
  busy : Expr

/-- A balanced indexed mux, with zero for indices outside the supplied list. -/
def select (xs : List Expr) (idx : Expr) (iw width : Nat) : Expr := Id.run do
  let mut level := (List.range (2^iw)).map fun i => xs[i]?.getD (lit 0 width)
  for k in [:iw] do
    let values := level.toArray
    level := (List.range (values.size / 2)).map fun i =>
      mux (bit idx k) values[2*i+1]! values[2*i]!
  return level.head!


def logic (slots : Nat) (a : Inputs) : CircuitM Outputs := do
  let sw := clog2 slots
  let one := lit 1 1
  let fields := fun name => (List.range slots).map fun i => ref s!"{name}{i}"
  let headSlots ← wire "head_slots" (5*sw) (pack ((List.range 5).map fun u => ref s!"queue_head{u}"))
  let relSlot ← wire "rel_slot" sw (ref "queue_release")
  let schedule ← SeqSchedule.logic slots {
    valid := ref "sv", started := ref "sstarted", units := pack (fields "soh"),
    dependencies := pack (fields "sdep"), dramDependencies := pack (fields "sdepd"),
    older := pack (fields "older"), unitReady := a.ready, unitStart := ref "ustart_q",
    unitDone := a.done, headSlots := headSlots, releaseSlot := relSlot,
    releasePending := bnot (eq (ref "uq_r") (ref "uq_t1")),
    newFootprint := a.footprint, footprints := pack (fields "sfp") }
  let go ← wire "window_go" 1 (band a.valid schedule.free)
  let allocated ← wire "allocated" slots (.op .shl [lit 1 slots, schedule.freeSlot])
  let mut nextValid := []
  let mut nextStarted := []
  let mut nextReady := []
  for i in [:slots] do
    let take ← wire s!"allocate{i}" 1 (band go (bit allocated i))
    let started ← wire s!"mark_started{i}" 1 (any ((List.range 5).map fun u =>
      band (bit schedule.canStart u) (bit schedule.selected (u*slots+i))))
    let ready ← wire s!"mark_ready{i}" 1 (every [bit (ref "sv") i,
      bnot (bit (ref "sready") i), eq (ref s!"sdep{i}") (lit 0 slots)])
    nextValid := nextValid ++ [mux take one (band (bit (ref "sv") i) (bnot (bit schedule.finish i)))]
    nextStarted := nextStarted ++ [mux take (lit 0 1) (bor (bit (ref "sstarted") i) started)]
    nextReady := nextReady ++ [mux take (lit 0 1) (bor (bit (ref "sready") i) ready)]
    reg s!"sdep{i}" slots true [(one, band (ref s!"sdep{i}") (bnot schedule.finish)),
      (take, schedule.newDependencies)]
    reg s!"sdepd{i}" slots false [(one, band (ref s!"sdepd{i}") (bnot schedule.finish)),
      (take, schedule.newDramDependencies)]
    -- The diagonal is cleared too: the column-clear NBA follows the row write.
    reg s!"older{i}" slots false [(go,
      band (mux take (ref "sv") (ref s!"older{i}")) (bnot allocated))]
    reg s!"soh{i}" 5 false [(take, .op .shl [lit 1 5, a.unit])]
    reg s!"sfp{i}" 322 false [(take, a.footprint)]
    reg s!"srdy_c{i}" 32 false [(ready, a.cycle)]
  reg "sv" slots true [(one, pack nextValid)]
  reg "sstarted" slots true [(one, pack nextStarted)]
  reg "sready" slots true [(one, pack nextReady)]
  reg "ustart_q" 5 true [(one, schedule.canStart)]
  reg "urel_q" 1 true [(one, schedule.canRelease)]
  reg "uq_r" (sw+1) true [(schedule.canRelease, add (ref "uq_r") (lit 1 (sw+1)))]
  let mut commands := []
  let mut commandSlots := []
  let mut readyCycles := []
  let mut busy := []
  for u in [:5] do
    let can := bit schedule.canStart u
    let start := slice schedule.startSlots (u*sw) sw
    reg s!"uq_h{u}" (sw+1) true [(bit a.done u, add (ref s!"uq_h{u}") (lit 1 (sw+1)))]
    reg s!"uq_t{u}" (sw+1) true [(can, add (ref s!"uq_t{u}") (lit 1 (sw+1)))]
    reg s!"ucs{u}" sw false [(can, start)]
    -- Queue entries have one write port and asynchronous indexed reads. Keep
    -- them as memories so synthesis can infer distributed RAM, as in the RTL.
    let m ← getModule
    let m := m.addWire { name := s!"queue_head{u}", ty := .bitVector sw }
    let m := if u == 1 then m.addWire { name := "queue_release", ty := .bitVector sw } else m
    setModule <| m.addStmt (.memory s!"queue_mem{u}" sw sw "clk"
      (slice (ref s!"uq_t{u}") 0 sw) start (band (bnot (ref "rst")) can)
      (slice (ref s!"uq_h{u}") 0 sw) s!"queue_head{u}" true []
      (if u == 1 then [(slice (ref "uq_r") 0 sw, "queue_release")] else []))
    let rd := s!"cmd_read{u}"
    let m ← getModule
    setModule <| (m.addWire { name := rd, ty := .bitVector 240 }).addStmt
      (.memory s!"cmd_mem{u}" sw 240 "clk" schedule.freeSlot a.command
        (band (bnot (ref "rst")) go) start rd true [] [])
    let qEnable := if u == 4 then band (bit a.ready u) (bnot (bit (ref "ustart_q") u)) else can
    reg s!"cmd_q{u}" 240 false [(qEnable, ref rd)]
    commands := commands ++ [ref s!"cmd_q{u}"]
    commandSlots := commandSlots ++ [ref s!"ucs{u}"]
    let ready := select ((List.range slots).map fun i => bit (ref "sready") i) (ref s!"ucs{u}") sw 1
    let stamp := select (fields "srdy_c") (ref s!"ucs{u}") sw 32
    readyCycles := readyCycles ++ [mux ready stamp a.eventCycle]
    busy := busy ++ [band (bnot (ref "rst")) (bnot (eq (ref s!"uq_h{u}") (ref s!"uq_t{u}")))]
  return ⟨pack commands, ref "ustart_q", ref "urel_q", ref "sv", schedule.free,
    schedule.freeSlot, go, schedule.finish, relSlot, schedule.canRelease,
    pack commandSlots, pack readyCycles, pack busy⟩

def build (slots : Nat) : Module := runModule "otpu_seq_window_sparkle" do
  clocks
  let a : Inputs := {
    valid := ← input "c_v" 1, command := ← input "c_cmd" 240,
    unit := ← input "c_unit" 3, footprint := ← input "c_fp" 322,
    ready := ← input "urdy" 5, done := ← input "udone" 5,
    cycle := ← input "cyc" 32, eventCycle := ← input "event_cyc" 32 }
  let o ← logic slots a
  output "ucmd" 1200 o.commands
  output "ustart" 5 o.start
  output "urel" 1 o.release
  output "valid_slots" slots o.valid
  output "have_free" 1 o.free
  output "free_slot" (clog2 slots) o.freeSlot
  output "c_go" 1 o.go
  output "fin" slots o.finish
  output "rel_slot" (clog2 slots) o.releaseSlot
  output "can_rel" 1 o.canRelease
  output "command_slots" (5*clog2 slots) o.commandSlots
  output "ready_cycles" 160 o.readyCycles
  output "busy" 5 o.busy

end OpenTPU.SeqWindow
