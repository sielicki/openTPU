import OpenTPU.VpuLanes
import OpenTPU.VpuDatapathMax
import OpenTPU.SeTail
import OpenTPU.Physical

namespace OpenTPU.VpuDatapath
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.VpuDatapathSupport

private def memory (name : String) (aw : Nat) (wa wd we ra : Expr) : CircuitM Expr := do
  let rd ← declared s!"{name}_read" 32
  let m ← getModule
  setModule <| m.addStmt (.memory name aw 32 "clk" wa wd we ra s!"{name}_read" true [] [])
  return rd

/-- Exact boundary of the command/issue/sequence/write/stream control assembly. -/
def build (c : Config) : Except String Module := do
  validate c
  return runModule "otpu_vpu_datapath_sparkle" do
    clocks
    for (n,w) in [("en",1),("mi",mw c),("ta_data",32*c.lanes),("tb_data",32*c.lanes),
      ("od_one",1),("od_sc",1),("ss_act",1),("s_first",1),("s_init",1),("sen",1),
      ("s_cfg",23),("s_fk",3),("s_fi",5),("s_fd",256),("s_in_v",1),("s_in_d",256),
      ("vt_q",1),("q_cap",1),("q_rl",1),("q_sub",8),("q_pd",32*c.lanes),
      ("mx_have",1),("mx_run",32),("mx_ri",17),("red_act",1),("func",8),("tag",8),
      ("imm",32),("rdb",1),("rows_done",16),("fl",16)] do let _ ← input n w
    let en := ref "en"
    let stream := if c.comp8 then ref "ss_act" else lit 0 1
    let mss := lit (19*2^(85+cbw c+c.lanes)) (mw c)
    let minput := mux stream mss (ref "mi")
    reg "m0" (mw c) true [(en,minput)]
    reg "m0d" 28 true [(en,VpuDecode.decode (field c minput "func"))] (VpuDecode.decodeValue 0)
    reg "xa" (32*c.lanes) false [(en,ref "ta_data")]
    reg "xb" (32*c.lanes) false [(en,ref "tb_data")]
    let m := ref "m0"
    let mr ← signal "m0r" 41 (reductionMeta c m)
    let mut xc := []
    let mut xd := []
    for l in [:c.lanes] do
      let we := band en (field c m "fill")
      let wa := field c m "cb"
      let ra := field c (ref "mi") "cb"
      let cr ← memory s!"cbuf{l}" (cbw c) wa (word (ref "xb") l) we ra
      let dr ← memory s!"dbuf{l}" (cbw c) wa (mux (ref "od_one") (lit 0x3f800000)
        (mux (ref "od_sc") (word (ref "xa") 0) (word (ref "xa") l))) we ra
      xc := xc ++ [← clocked s!"xc{l}" 32 en cr]
      xd := xd ++ [← clocked s!"xd{l}" 32 en dr]
    for (n,w) in [("s_xd",256),("s_xa",256),("s_xm",17),("c_uy",256),("c_qy",256),
      ("c_sel",3),("c_sa",96*c.lanes),("c_sb",96*c.lanes),("c_sc",96*c.lanes),("c_se",96*c.lanes),
      ("c_hold",1),("lane_pacc",32*c.lanes),("mo",25+c.lanes),("lres",32*c.lanes),
      ("lmm",c.lanes),("lmv",32*c.lanes),("root",32),("root_o",32),("root_v",1),
      ("t_yv",1),("ss_y_d",256),("t_ov",1),("ss_o_d",32),("t_qc",1),("t_qrl",1),
      ("t_qsub",8),("t_qd",256),("mx_new",32),("mx_ni",17),("mxm",41),
      ("am4_v",1),("am4_l",1),("am4_a",20),("am4_m",32),("am4_i",32)] do let _ ← declared n w
    let sm ← if c.comp8 then delay "s_mt" 7 17 (ref "s_xm") else pure (lit 0 17)
    let mtq ← delay "mtq" (if rma c then 3 else 2) 41 mr
    let mt ← delay "mt" 4 41 mtq
    let mut partials := []
    let mut ras := []
    let mut rbs := []
    let mut rfs := []
    for l in [:c.lanes] do
      let x := word (ref "xa") l
      let mask := bit (field c m "mask") l
      let sa := pack [slice x 0 23,mux mask (slice x 23 8) (lit 0 8),band mask (bit x 31)]
      let sb := mux (field c m "sq") sa (mux (band (field c m "dot") mask)
        (laneY c m (ref "xb") l) (lit 0x3f800000))
      ras := ras ++ [mux stream (word (ref "s_xd") l) sa]
      rbs := rbs ++ [mux stream (word (ref "s_xa") l) sb]
      if rma c then
        let p := word (ref "lane_pacc") l
        let fb ← delay s!"red_fb{l}" (64/c.lanes-8) 32 p
        let fbq ← clocked s!"red_fbq{l}" 32 en (mux (field c (ref "mi") "first") (lit 0) fb)
        rfs := rfs ++ [mux (ref "s_first") (lit 0) fbq]
        partials := partials ++ [p]
      else
        let p ← declared s!"red_partial{l}" 32
        let term ← arithmetic s!"red_mul{l}" true sa sb
        let sum ← arithmetic s!"red_add{l}" false (mux (rm mtq "first") (lit 0) p) term
        emitAssign s!"red_partial{l}" sum
        rfs := rfs ++ [lit 0]
        partials := partials ++ [p]
    emitInstance "otpu_vpu_lanes_sparkle" "u_lanes"
      [("clk",ref "clk"),("rst",ref "rst"),("en",en),("m0",m),("m0d",ref "m0d"),
       ("xa",ref "xa"),("xb",ref "xb"),("xc",pack xc),("xd",pack xd),
       ("rsa",pack ras),("rsb",pack rbs),("rfb",pack rfs),("c_uy",ref "c_uy"),("c_qy",ref "c_qy"),
       ("mo",ref "mo"),("lres",ref "lres"),("lmm",ref "lmm"),("lmv",ref "lmv"),
       ("pacc",ref "lane_pacc"),("o_c_hold",ref "c_hold"),("o_c_sel",ref "c_sel"),
       ("o_c_sa",ref "c_sa"),("o_c_sb",ref "c_sb"),("o_c_sc",ref "c_sc"),("o_c_se",ref "c_se")]
    emitInstance "otpu_vpu_max_sparkle" "u_max"
      [("clk",ref "clk"),("rst",ref "rst"),("en",en),("xa",ref "xa"),("mask",field c m "mask"),
       ("m0r",mr),("col",field c m "col"),("mx_have",ref "mx_have"),("mx_run",ref "mx_run"),
       ("mx_ri",ref "mx_ri"),("red_act",ref "red_act"),("func",ref "func"),("tag",ref "tag"),
       ("imm",ref "imm"),("mx_new",ref "mx_new"),("mx_ni",ref "mx_ni"),("mxm",ref "mxm"),
       ("o_am4_v",ref "am4_v"),("o_am4_l",ref "am4_l"),("o_am4_a",ref "am4_a"),
       ("o_am4_m",ref "am4_m"),("o_am4_i",ref "am4_i")]
    let sum := any ([16,18,19].map fun f => eq (ref "func") (lit f 8))
    let cap ← wire "capture" 1 (bor (ref "q_cap") (mux stream (band (bit sm 16) (bit sm 14))
      (every [ref "red_act",sum,live mt (ref "tag"),rm mt "final"])))
    let last ← wire "tree_last" 1 (mux (ref "q_cap") (ref "q_rl") (mux stream (bit sm 13) (rm mt "row_last")))
    let subrow := mux (ref "q_cap") (ref "q_sub") (mux stream (slice sm 5 8) (rm mt "sub"))
    let unused ← declared "tree_collision" 1
    emitInstance "otpu_vtree_sparkle" "u_tree"
      [("clk",ref "clk"),("rst",bor (ref "rst") (ref "s_init")),("en",en),
       ("pacc",mux (ref "q_cap") (ref "q_pd") (pack partials)),("cap",cap),("row_last",last),
       ("sub",subrow),("root",ref "root"),("root_o",ref "root_o"),("root_v",ref "root_v"),("schedule_collision",unused)]
    let lw := clog2 c.lanes
    let mut rbuf := []
    for l in [:c.lanes] do
      let wa := slice (ref "rows_done") lw (16-lw)
      let ra := slice (ref "fl") lw (16-lw)
      let we := every [en,ref "red_act",sum,ref "root_v",ref "rdb",eq (slice (ref "rows_done") 0 lw) (lit l lw),
        lt wa (lit (256/c.lanes) (16-lw))]
      let read ← memory s!"rbuf{l}" (cbw c) (slice wa 0 (cbw c)) (ref "root") we (slice ra 0 (cbw c))
      -- The source has undefined out-of-range reads. Its synthesized RAM uses
      -- the low address bits; valid buffered rows are always below 256.
      rbuf := rbuf ++ [read]
    if c.comp8 then
      emitInstance "otpu_se_tail_sparkle" "u_tail"
        [("clk",ref "clk"),("rst",ref "rst"),("init",ref "s_init"),("cfg",ref "s_cfg"),
         ("fk",ref "s_fk"),("fi",ref "s_fi"),("fd",ref "s_fd"),("pe",ref "sen"),
         ("in_v",ref "s_in_v"),("in_d",ref "s_in_d"),("xd",ref "s_xd"),("xa",ref "s_xa"),("xm",ref "s_xm"),
         ("kv",ref "root"),("kv_v",band (ref "root_v") (bnot (ref "vt_q"))),
         ("y_v",ref "t_yv"),("y_d",ref "ss_y_d"),("o_v",ref "t_ov"),("o_d",ref "ss_o_d"),
         ("qp_cap",ref "t_qc"),("qp_row_last",ref "t_qrl"),("qp_sub",ref "t_qsub"),("qp_d",ref "t_qd"),
         ("qo_v",band (ref "root_v") (ref "vt_q")),("qo_d",ref "root_o"),("cm",bnot stream),("cen",en),
         ("u_sel",bit (ref "c_sel") 1),("u_a",slice (ref "c_sa") 256 256),("u_b",slice (ref "c_sb") 256 256),
         ("u_c",slice (ref "c_sc") 256 256),("u_e",slice (ref "c_se") 256 256),
         ("q_sel",bit (ref "c_sel") 2),("q_a",slice (ref "c_sa") 512 256),("q_b",slice (ref "c_sb") 512 256),
         ("q_c",slice (ref "c_sc") 512 256),("u_y",ref "c_uy"),("q_y",ref "c_qy")]
    else
      for (n,w) in [("s_xd",256),("s_xa",256),("s_xm",17),("c_uy",256),("c_qy",256),
        ("t_yv",1),("ss_y_d",256),("t_ov",1),("ss_o_d",32),("t_qc",1),("t_qrl",1),("t_qsub",8),("t_qd",256)] do
        emitAssign n (lit 0 w)
    for (n,w,e) in [("s_xm_first",1,bit (ref "s_xm") 15),("t_qc",1,ref "t_qc"),
      ("t_qrl",1,ref "t_qrl"),("t_qsub",8,ref "t_qsub"),("t_qd",256,ref "t_qd"),
      ("cap",1,cap),("vt_rl",1,last),("t_yv",1,ref "t_yv"),("t_ov",1,ref "t_ov"),
      ("ss_y_d",256,ref "ss_y_d"),("ss_o_d",32,ref "ss_o_d"),
      ("mo_mask",c.lanes,slice (ref "mo") 21 c.lanes),("mo_waddr",20,slice (ref "mo") 1 20),
      ("mo_v",1,bit (ref "mo") (24+c.lanes)),("mo_all_last",1,bit (ref "mo") 0),
      ("lres",32*c.lanes,ref "lres"),("lmm",c.lanes,ref "lmm"),("lmv",32*c.lanes,ref "lmv"),
      ("mxm_waddr",20,rm (ref "mxm") "waddr"),("mxm_v",1,rm (ref "mxm") "v"),
      ("mxm_tag",8,rm (ref "mxm") "tag"),("mxm_row_last",1,rm (ref "mxm") "row_last"),
      ("mxm_all_last",1,rm (ref "mxm") "all_last"),("rbuf_q",32*c.lanes,pack rbuf),
      ("am4_a",20,ref "am4_a"),("am4_m",32,ref "am4_m"),("am4_i",32,ref "am4_i"),
      ("am4_v",1,ref "am4_v"),("am4_l",1,ref "am4_l"),("root",32,ref "root"),
      ("root_v",1,ref "root_v"),("mx_new",32,ref "mx_new"),("mx_ni",17,ref "mx_ni"),("c_hold",1,ref "c_hold")] do
      -- Ports are deliberately prefixed to keep internal drivers distinct.
      output s!"o_{n}" w e

/-- Keep the terminal flip-flops of the reference delay lines out of SRLs. -/
def laneRegisterHints (c : Config) : Backend.RegisterHints :=
  let endpoint := fun n => (n,[Backend.RegisterAttribute.keep,.noShiftRegister])
  ((List.range (nsx c)).map fun s => endpoint s!"meta_slot{s}_6") ++
  (if nsx c > 1 then [endpoint "meta_pre_2"] else []) ++
  ((List.range (nll c)).flatMap fun l => (List.range 10).flatMap fun s =>
    let p := s!"lane{l}_slot{s}"
    [endpoint s!"{p}_f_5",endpoint s!"{p}_dst_delay_5"] ++
    (if s <= 8 then [endpoint s!"{p}_k1_5",endpoint s!"{p}_k2_5",endpoint s!"{p}_ii_5"] else []) ++
    (if s > 0 then [endpoint s!"{p}_c_1"] else []))

def registerHints (c : Config) : Backend.RegisterHints :=
  let endpoint := fun n => (n,[Backend.RegisterAttribute.keep,.noShiftRegister])
  [endpoint s!"mtq_{if rma c then 2 else 1}",endpoint "mt_3"] ++
  (if c.comp8 then [endpoint "s_mt_6"] else []) ++
  (if rma c && 64/c.lanes > 8 then (List.range c.lanes).map fun l =>
    endpoint s!"red_fb{l}_{64/c.lanes-9}" else [])

def toVerilog (c : Config) : Except String String := do
  let top ← build c
  let lanes ← VpuLanes.build c
  let maxTree ← VpuDatapathMax.build c
  let emit := Sparkle.Backend.Verilog.toVerilog
  let tree ← Physical.vtree ⟨c.lanes,4⟩
  let streams ← if c.comp8 then do
    let composite ← SeComposite.toVerilog ⟨c.lanes,21,3,2,true⟩
    let tail ← SeTail.toVerilog ⟨8,7,1⟩
    pure (composite ++ tail)
    else pure ""
  let top ← Backend.withRegisterHints top (registerHints c)
    (memoryHints := (List.range c.lanes).map fun l => (s!"rbuf{l}",.distributed))
  let lanes ← Backend.withRegisterHints lanes (laneRegisterHints c)
  return top ++ lanes ++ emit maxTree ++ tree ++ streams ++
    emit {Float.multiply 2 with name := "otpu_vpu_datapath_mul"} ++
    emit {Float.addition 4 with name := "otpu_vpu_datapath_add"}

end OpenTPU.VpuDatapath
