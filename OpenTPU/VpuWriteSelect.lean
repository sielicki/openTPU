import OpenTPU.VpuIssue

namespace OpenTPU.VpuWriteSelect
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

/-- Ordered arbitration of elementwise, maximum/index, sum and buffered-row writes.
    Priority is retained even for overlapping completion inputs. -/
def build (lanes : Nat) : Except String Module := do
  if lanes < 2 || lanes > 16 then throw "VPU write selection requires 2..16 lanes"
  return runModule "otpu_vpu_write_select_sparkle" do
    for (n,w) in [("mo_v",1),("mo_mask",lanes),("mo_waddr",20),("lres",32*lanes),
      ("lmm",lanes),("lmv",32*lanes),("red_act",1),("func",8),("tag",8),
      ("mxm_v",1),("mxm_tag",8),("mxm_row_last",1),("mxm_waddr",20),("mx_new",32),
      ("am4_v",1),("am4_a",20),("am4_m",32),("am4_i",32),
      ("root_v",1),("rdb",1),("wr_row",20),("root",32),
      ("flushing",1),("fl",16),("rows",16),("dst",20),("rbuf_q",32*lanes)] do
      let _ ← input n w
    let maximum := every [ref "red_act",eq (ref "func") (lit 17 8),ref "mxm_v",
      eq (ref "mxm_tag") (ref "tag"),ref "mxm_row_last"]
    let sum := every [ref "red_act",([16,18,19] : List Nat).foldl
      (fun p f => bor p (eq (ref "func") (lit f 8))) (lit 0 1),ref "root_v",bnot (ref "rdb")]
    let mut enables := []
    let mut addresses := []
    let mut values := []
    for l in [:lanes] do
      let element := band (ref "mo_v") (bit (ref "mo_mask") l)
      let mut en := element
      let mut addr := mux element (add (ref "mo_waddr") (lit l 20)) (lit 0 20)
      let mut value := mux element (slice (ref "lres") (32*l) 32) (lit 0)
      let mut mm := band element (bit (ref "lmm") l)
      if l == 0 then
        en := bor en maximum
        addr := mux maximum (ref "mxm_waddr") addr
        value := mux maximum (ref "mx_new") value
        mm := band mm (bnot maximum)
      if l < 2 then
        en := bor en (ref "am4_v")
        addr := mux (ref "am4_v") (add (ref "am4_a") (lit l 20)) addr
        value := mux (ref "am4_v") (ref (if l == 0 then "am4_m" else "am4_i")) value
        mm := band mm (bnot (ref "am4_v"))
      if l == 0 then
        en := bor en sum
        addr := mux sum (ref "wr_row") addr
        value := mux sum (ref "root") value
        mm := band mm (bnot sum)
      let flush := band (ref "flushing") (lt (add (zext (ref "fl") 16 32) (lit l)) (zext (ref "rows") 16 32))
      en := bor en flush
      addr := mux flush (add (add (ref "dst") (zext (ref "fl") 16 20)) (lit l 20)) addr
      value := mux flush (slice (ref "rbuf_q") (32*l) 32) value
      mm := band mm (bnot flush)
      enables := enables ++ [en]
      addresses := addresses ++ [slice addr 0 20]
      values := values ++ [mux mm (slice (ref "lmv") (32*l) 32) value]
    output "cw_en" lanes (pack enables)
    output "cw_addr" (20*lanes) (pack addresses)
    output "cw_data" (32*lanes) (pack values)

end OpenTPU.VpuWriteSelect
