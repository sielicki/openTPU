import OpenTPU.Backend

namespace OpenTPU.BoardSignals
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

/-- Board-local synchronizers, stable temperature sampling, reset stages and LEDs. -/
def build : Module := runModule "otpu_board_signals_sparkle" do
  clocks
  for (n,w) in [("calib",2),("temp",12),("i2c_pin",5),("run",1),("halted",1),("error",1)] do
    let _ ← input n w
  for (n,w,d) in [("cal_s1",2,ref "calib"),("cal_s2",2,ref "cal_s1"),
      ("tmp_s1",12,ref "temp"),("tmp_s2",12,ref "tmp_s1"),("tmp_s3",12,ref "tmp_s2"),
      ("i2c_s1",5,ref "i2c_pin"),("i2c_s2",5,ref "i2c_s1"),
      ("core_rst",1,bor (ref "rst") (bnot (ref "run"))),("coll_rst",1,ref "core_rst"),
      ("hb",27,add (ref "hb") (lit 1 27))] do
    let _ ← clocked n w (lit 1 1) d
  let sample := band (eq (ref "tmp_s2") (ref "tmp_s3"))
    (band (bit (ref "cal_s2") 0) (bnot (eq (ref "tmp_s3") (lit 0 12))))
  reg "temp_q" 12 true [(sample,ref "tmp_s3")]
  reg "temp_v" 1 true [(sample,lit 1 1)]
  for (n,w) in [("cal_s2",2),("temp_q",12),("temp_v",1),("i2c_s2",5),("core_rst",1),("coll_rst",1)] do
    output s!"o_{n}" w (ref n)
  output "led" 3 (pack [bit (ref "hb") 26,band (ref "run") (bnot (ref "halted")),band (ref "halted") (bnot (ref "error"))])

def toVerilog : Except String String :=
  Backend.withRegisterHints build
    ((["cal_s1","cal_s2","tmp_s1","tmp_s2","i2c_s1","i2c_s2"].map fun n =>
      (n,[Backend.RegisterAttribute.asyncRegister])) ++ [("core_rst",[.maxFanout 256])])

end OpenTPU.BoardSignals
