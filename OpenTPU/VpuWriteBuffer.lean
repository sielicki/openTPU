import OpenTPU.VpuIssue

namespace OpenTPU.VpuWriteBuffer
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

structure Config where
  lanes : Nat := 8
  buffered : Bool := true
  streams : Bool := true
  deriving Repr

def Config.se (c : Config) := c.streams && c.lanes == 8

def build (c : Config) : Except String Module := do
  if !powerOfTwo c.lanes || c.lanes < 2 || c.lanes > 16 then
    throw "VPU write buffer requires power-of-two LANES in 2..16"
  return runModule "otpu_vpu_write_buffer_sparkle" do
    clocks
    for (n,w) in [("gnt",1),("ss_act",1),("sen",1),("ss_act_d",1),("ss_pe",1),
      ("done_i",1),("cw_en",c.lanes),("cw_addr",20*c.lanes),("cw_data",32*c.lanes)] do
      let _ ← input n w
    let pending ← wire "pdn" 1 (bor (ref "done_i") (ref "dpend"))
    if !c.buffered then
      reg "tw_en_r" c.lanes true [(ref "gnt",ref "cw_en")]
      reg "tw_a_r" (20*c.lanes) false [(ref "gnt",ref "cw_addr")]
      reg "tw_data_r" (32*c.lanes) false [(ref "gnt",ref "cw_data")]
      reg "done_r" 1 true [(lit 1 1,band pending (ref "gnt"))]
      reg "dpend" 1 true [(lit 1 1,band pending (bnot (ref "gnt")))]
      output "en" 1 (if c.se then mux (ref "ss_act") (ref "sen") (ref "gnt") else ref "gnt")
      output "wb_e" 1 (eq (ref "tw_en_r") (lit 0 c.lanes))
      output "tw_en" c.lanes (ref "tw_en_r")
      output "tw_a" (20*c.lanes) (ref "tw_a_r")
      output "tw_data" (32*c.lanes) (ref "tw_data_r")
    else
      let slots := if c.se then 4 else 2
      let pw := clog2 slots
      let width := 53*c.lanes+1
      let select := fun index => OpenTPU.SeqWindow.select ((List.range slots).map fun i => ref s!"wq{i}") index pw width
      let hd ← wire "hd" width (select (ref "wh"))
      let nh ← wire "nh" width (select (slice (add (ref "wh") (lit 1 pw)) 0 pw))
      let push ← wire "push" 1 (band (ref "en_r") (bor (bnot (eq (ref "cw_en") (lit 0 c.lanes))) pending))
      let pop ← wire "pop" 1 (band (bnot (eq (ref "wn") (lit 0 (pw+1)))) (ref "gnt"))
      let p0 ← wire "wn_p0" (pw+1) (add (ref "wn") (zext push 1 (pw+1)))
      let p1 ← wire "wn_p1" (pw+1) (sub p0 (lit 1 (pw+1)))
      let packed := pack [pending,ref "cw_data",ref "cw_addr",ref "cw_en"]
      -- Reference RAM writes are outside the reset branch.
      for i in [:slots] do
        let _ ← clocked s!"wq{i}" width (band push (eq (ref "wt") (lit i pw))) packed
      reg "wh" pw true [(pop,add (ref "wh") (lit 1 pw))]
      reg "wt" pw true [(push,add (ref "wt") (lit 1 pw))]
      reg "wn" (pw+1) true [(lit 1 1,mux pop p1 p0)]
      let newHead ← wire "new_head" 1 (band push (bor (eq (ref "wn") (lit 0 (pw+1)))
        (band (eq (ref "wn") (lit 1 (pw+1))) pop)))
      let takeNext := band pop (bnot newHead)
      reg "hen" c.lanes true [(newHead,ref "cw_en"),(takeNext,mux (lt (lit 1 (pw+1)) (ref "wn"))
        (slice nh (1+52*c.lanes) c.lanes) (lit 0 c.lanes))]
      let lw := clog2 c.lanes
      reg "hrot" lw false [(newHead,slice (ref "cw_addr") 0 lw),(takeNext,slice nh (1+32*c.lanes) lw)]
      let room := mux pop (lt p1 (lit 2 (pw+1))) (lt p0 (lit 2 (pw+1)))
      if c.se then
        reg "en_q" 1 true [(lit 1 1,mux (ref "ss_act_d") (ref "ss_pe") room)]
        reg "en_r" 1 true [(lit 1 1,ref "en_q")]
      else
        reg "en_r" 1 true [(lit 1 1,room)]
      reg "done_r" 1 true [(lit 1 1,band pop (bit hd 0))]
      reg "dpend" 1 true [(lit 1 1,band pending (bnot (ref "en_r")))]
      output "en" 1 (ref "en_r")
      output "wb_e" 1 (eq (ref "wn") (lit 0 (pw+1)))
      output "tw_en" c.lanes (ref "hen")
      output "tw_data" (32*c.lanes) (slice hd 1 (32*c.lanes))
      output "tw_a" (20*c.lanes) (pack ((List.range c.lanes).map fun l =>
        pack [slice (add (ref "hrot") (lit l lw)) 0 lw,slice hd (1+32*c.lanes+20*l+lw) (20-lw)]))
    output "done" 1 (ref "done_r")
    output "o_dpend" 1 (ref "dpend")

end OpenTPU.VpuWriteBuffer
