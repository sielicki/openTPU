import OpenTPU.Float
import OpenTPU.FloatConvert
import OpenTPU.SeqWindow
import OpenTPU.SeqLogic
import OpenTPU.Backend

/-! Native stream-engine tail. All memories and feedback pipelines are concrete;
    the shared U/Q arithmetic uses native binary32 pipelines. -/
namespace OpenTPU.SeTail
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit
open OpenTPU.SeqLogic

structure Config where
  lanes : Nat := 8
  inputLatency : Nat := 7
  treeDelay : Nat := 1
  deriving Repr

def Config.delay (c : Config) : Nat := Id.run do
  let d := 96+c.treeDelay
  let mut o := (d+7)/8
  for _ in [:6] do
    if o%2 == 0 || o%3 == 0 then o := o+1
  return 83+c.inputLatency+(o*8-d)

def Config.validate (c : Config) : Except String Unit := do
  if c.lanes != 8 || c.delay >= 128 || c.treeDelay > 2^20 then
    throw "SE tail requires LANES=8 and a computed delay below 128 cycles"

private def signal (name : String) (width : Nat) (value : Expr) : CircuitM Expr := do
  let m ← getModule
  setModule <| (m.addWire {name,ty := .bitVector width}).addStmt (.assign name value)
  return ref name

private def delay (name : String) (cycles width : Nat) (en value : Expr) : CircuitM Expr := do
  let mut q := value
  for i in [:cycles] do q ← clocked s!"{name}_{i}" width en q
  return q

private def memory (name : String) (aw dw : Nat) (wa wd we ra : Expr) : CircuitM Expr := do
  let rd := s!"{name}_read"
  let m ← getModule
  setModule <| (m.addWire {name := rd,ty := .bitVector dw}).addStmt
    (.memory name aw dw "clk" wa wd we ra rd true [] [])
  return ref rd

private def arithmetic (name : String) (multiply : Bool) (en a b : Expr) : CircuitM Expr := do
  let result := s!"{name}_result"
  let m ← getModule
  setModule <| m.addWire {name := result,ty := .bitVector 32}
  emitInstance (if multiply then "otpu_se_tail_mul" else "otpu_se_tail_add") name
    [("clk",ref "clk"),("en",en),("a",a),("b",b),("y",ref result)]
  return ref result

private def madd (name : String) (en a b cv : Expr) : CircuitM Expr := do
  let p ← arithmetic s!"{name}_mul" true en a b
  let cd ← delay s!"{name}_cd" 2 32 en cv
  arithmetic s!"{name}_add" false en p cd

private def resetRegister (name : String) (width : Nat) (en value : Expr) : CircuitM Unit :=
  reg name width true [(en,value),(ref "init",lit 0 width)]

private def metadata (v j ns : Expr) :=
  let j32 := zext j 5 32
  let n32 := zext ns 6 32
  pack [j,zext (slice j 0 3) 3 8,band v (eq (add j32 (lit 1)) n32),
    band v (bnot (lt (add j32 (lit 8)) n32)),band v (lt j32 (lit 8)),v]

def build (c : Config) : Except String Module := do
  c.validate
  return runModule "otpu_se_tail_sparkle" do
    clocks
    for (name,width) in [("init",1),("cfg",23),("fk",3),("fi",5),("fd",256),
      ("pe",1),("in_v",1),("in_d",256),("kv",32),("kv_v",1),("qo_v",1),("qo_d",32),
      ("cm",1),("cen",1),("u_sel",1),("u_a",256),("u_b",256),("u_c",256),("u_e",256),
      ("q_sel",1),("q_a",256),("q_b",256),("q_c",256)] do
      let _ ← input name width
    let pe := ref "pe"
    let cen := ref "cen"
    let cm := ref "cm"
    let fk := ref "fk"
    let cfg := ref "cfg"
    let one := lit 1 1
    let nz := lit 0x80000000
    let fo := lit 0x3f800000
    let mode := slice cfg 4 2
    let gsrc := slice cfg 2 2
    for (name,width,value) in [("ns",6,slice cfg 17 6),("c_asel",1,bit cfg 6),
      ("c_kz",1,bnot (bit cfg 7)),("c_a2p",1,eq mode (lit 3 2)),
      ("c_c2z",1,bor (eq mode (lit 2 2)) (eq mode (lit 3 2))),
      ("c_gcol",1,eq gsrc (lit 1 2)),("c_qen",1,bit cfg 1),("c_pad",1,bit cfg 0),
      ("b1",32,mux (eq mode (lit 0 2)) (ref "e") fo),
      ("gk",32,mux (eq gsrc (lit 2 2)) fo (ref "e"))] do
      let _ ← clocked name width one value
    let _ ← clocked "e" 32 (eq fk (lit 4 3)) (slice (ref "fd") 0 32)
    let _ ← clocked "beta" 32 (eq fk (lit 5 3)) (slice (ref "fd") 0 32)
    let fa ← signal "fa" 1 (bor (band (eq fk (lit 2 3)) (bnot (ref "c_asel"))) (eq fk (lit 6 3)))
    let mut vectors := #[]
    for l in [:8] do
      for (name,enable,index) in [("kb",fa,ref "jn"),("kb2",eq fk (lit 2 3),ref "uj"),
        ("qb",eq fk (lit 1 3),ref "uj"),("vb",eq fk (lit 3 3),slice (ref "rv") 3 5),
        ("gb",eq fk (lit 7 3),ref "uj")] do
        let rd ← memory s!"{name}{l}" 5 32 (ref "fi") (slice (ref "fd") (32*l) 32) enable index
        let _ ← signal s!"{name}_value{l}" 32 (if name == "vb" then rd else
          mux (band (ref "c_pad") (bnot (eq (slice index 3 2) (lit 0 2)))) (lit 0) rd)
      vectors := vectors.push (ref s!"vb_value{l}")
      let _ ← clocked s!"xd{l}" 32 pe (slice (ref "in_d") (32*l) 32)
      let _ ← clocked s!"xa{l}" 32 pe (ref s!"kb_value{l}")
    let vr ← signal "vr" 32 (SeqWindow.select vectors.toList (slice (ref "rv") 0 3) 3 32)
    resetRegister "jn" 5 (band pe (ref "in_v"))
      (mux (eq (add (zext (ref "jn") 5 32) (lit 1)) (zext (ref "ns") 6 32)) (lit 0 5) (add (ref "jn") (lit 1 5)))
    resetRegister "x0" 17 pe (metadata (ref "in_v") (ref "jn") (ref "ns"))
    resetRegister "rv" 8 (band pe (ref "kv_v")) (add (ref "rv") (lit 1 8))
    let _ ← clocked "d1a" 32 pe (mux (ref "c_kz") (lit 0) (ref "kv"))
    let _ ← clocked "d2a" 32 pe (mux (ref "c_a2p") (ref "p1") (ref "vd"))
    let _ ← clocked "d2c" 32 pe (mux (ref "c_c2z") nz (FloatConvert.neg (ref "p1")))
    let _ ← clocked "d3a" 32 pe (ref "s2")
    for (name,n,width,value) in [("d1v",1,1,ref "kv_v"),("vd",7,32,vr),
      ("d2v",7,1,ref "d1v"),("d3v",7,1,ref "d2v"),("dv",6,1,ref "d3v")] do
      let q ← delay name n width pe value
      let _ ← signal name width q
    for (name,a,b,cv) in [("p1",ref "d1a",ref "b1",nz),
      ("s2",ref "d2a",fo,ref "d2c"),("dd",ref "d3a",ref "beta",nz)] do
      let q ← madd name pe a b cv
      let _ ← signal name 32 q
    resetRegister "wc" 7 pe (add (ref "wc") (lit 1 7))
    resetRegister "warm" 8 (band pe (bnot (eq (ref "warm") (lit c.delay 8)))) (add (ref "warm") (lit 1 8))
    let ud := pack (((List.range 8).map fun l => ref s!"xd{l}") ++ [ref "x0"])
    let ub ← memory "ub" 7 273 (ref "wc") ud pe (sub (ref "wc") (lit (c.delay-1) 7))
    let ubq ← clocked "ub_q" 273 pe ub
    let um ← signal "um" 17 (mux (eq (ref "warm") (lit c.delay 8)) (slice ubq 256 17) (lit 0 17))
    let _ ← signal "uj" 5 (slice um 0 5)
    let first ← signal "first" 1 (band (bit um 16) (eq (slice um 0 5) (lit 0 5)))
    let pop ← signal "d_pop" 1 (band pe first)
    let held := bor (ref "rst") (ref "init")
    let dq ← memory "dq" 3 32 (ref "dq_t") (ref "dd") (band (bnot held) (band pe (ref "dv"))) (ref "dq_h")
    resetRegister "dq_h" 3 pop (add (ref "dq_h") (lit 1 3))
    resetRegister "dq_t" 3 (band pe (ref "dv")) (add (ref "dq_t") (lit 1 3))
    resetRegister "dq_n" 4 pe (sub (add (ref "dq_n") (zext (ref "dv") 1 4)) (zext pop 1 4))
    let cur ← clocked "d_cur" 32 pop dq
    let row ← signal "d_row" 32 (mux first dq cur)
    let pad ← signal "upad" 1 (band (ref "c_pad") (bnot (eq (slice um 3 2) (lit 0 2))))
    let uy ← delay "uy" 7 17 pe um
    let yqd ← signal "yq_d" 17 (mux (ref "c_qen") uy (lit 0 17))
    let yqq ← delay "yq" 2 17 pe yqd
    let yqt ← delay "yt" 4 17 pe yqq
    let fq ← delay "fq" 1 1 pe (bit yqd 15)
    let mut ys := []
    let mut qs := []
    for l in [:8] do
      let word := fun name => slice (ref name) (32*l) 32
      let ra ← clocked s!"ura{l}" 32 cen (mux cm (word "u_a") (slice ubq (32*l) 32))
      let rg ← clocked s!"urg{l}" 32 cen (mux cm (word "u_b")
        (mux pad (lit 0) (mux (ref "c_gcol") (ref s!"gb_value{l}") (ref "gk"))))
      let rc ← clocked s!"urc{l}" 32 cen (mux cm (word "u_c") (mux pad (lit 0) row))
      let re ← clocked s!"ure{l}" 32 cen (mux cm (word "u_e") (ref s!"kb2_value{l}"))
      let p ← arithmetic s!"um{l}" true cen ra rg
      let q ← arithmetic s!"uc{l}" true cen rc re
      let nw ← arithmetic s!"ua{l}" false cen p q
      ys := ys ++ [nw]
      let qy ← delay s!"qd{l}" 7 32 pe (ref s!"qb_value{l}")
      let qa ← clocked s!"qa{l}" 32 cen (word "q_a")
      let qb ← clocked s!"qrb{l}" 32 cen (word "q_b")
      let qc ← clocked s!"qc{l}" 32 cen (word "q_c")
      let qc2 ← clocked s!"qc2_{l}" 32 cen qc
      let tq ← arithmetic s!"qm{l}" true cen (mux cm qa nw) (mux cm qb qy)
      let fb ← delay s!"fb{l}" 3 32 cen (ref s!"qadd{l}_result")
      let fbq ← clocked s!"fbq{l}" 32 cen (mux cm qc2 (mux fq (lit 0) fb))
      let pq ← arithmetic s!"qadd{l}" false cen fbq tq
      qs := qs ++ [pq]
    output "xd" 256 (pack ((List.range 8).map fun l => ref s!"xd{l}"))
    output "xa" 256 (pack ((List.range 8).map fun l => ref s!"xa{l}"))
    output "xm" 17 (ref "x0")
    output "y_v" 1 (bit uy 16)
    output "y_d" 256 (pack ys)
    output "u_y" 256 (pack ys)
    output "q_y" 256 (pack qs)
    output "qp_d" 256 (pack qs)
    output "qp_cap" 1 (band (band (bit yqt 16) (bit yqt 14)) (ref "c_qen"))
    output "qp_row_last" 1 (bit yqt 13)
    output "qp_sub" 8 (slice yqt 5 8)
    output "o_v" 1 (band (ref "qo_v") (ref "c_qen"))
    output "o_d" 32 (ref "qo_d")

/-- Emit the source FIFO diagnostic on the core also used by the VPU datapath. -/
def withFifoDiagnostic (core : String) : Except String String := do
  let ending := "\nendmodule\n"
  if !core.endsWith ending || (core.splitOn ending).length != 2 then
    throw "SE tail diagnostic requires exactly one complete emitted core"
  let diagnostic := "
`ifndef SYNTHESIS
  always @(posedge clk)
    if (!rst && pe && ((d_pop && dq_n == 0) || (dv && !d_pop && {28'd0, dq_n} == 32'd8)))
      $fatal(1, \"otpu_se_tail: d FIFO %s\", (d_pop && dq_n == 0) ? \"underflow\" : \"overflow\");
`endif
"
  return core.replace ending (diagnostic ++ "endmodule\n")

def toVerilog (c : Config) : Except String String := do
  let core ← build c
  let endpoints := [("d1v",0),("vd",6),("d2v",6),("d3v",6),("dv",5),
    ("uy",6),("yq",1),("yt",3),("fq",0),("p1_cd",1),("s2_cd",1),("dd_cd",1)] ++
    ((List.range 8).flatMap fun l => [(s!"qd{l}",6),(s!"fb{l}",2)])
  let core ← Backend.withRegisterHints core (endpoints.map fun (name,i) =>
    (s!"{name}_{i}",[Backend.RegisterAttribute.keep,.noShiftRegister]))
    (memoryHints := [("ub",.block)])
  let core ← withFifoDiagnostic core
  return core ++ Sparkle.Backend.Verilog.toVerilog {Float.multiply 2 with name := "otpu_se_tail_mul"} ++
    Sparkle.Backend.Verilog.toVerilog {Float.addition 4 with name := "otpu_se_tail_add"}

end OpenTPU.SeTail
