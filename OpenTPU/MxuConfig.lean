import OpenTPU.Circuit

namespace OpenTPU.Mxu
open OpenTPU.Circuit

structure Config where
  d : Nat := 32
  columns : Nat := 8
  rows : Nat := 8
  depth : Nat := 16
  lanes : Nat := 8
  implementation : Nat := 0
  chainLength : Nat := 16
  sliceId : Nat := 0
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  if c.d == 0 || c.d % 16 != 0 then
    throw "mxu: D must be a positive multiple of 16"
  if c.columns == 0 || c.rows < c.columns || c.rows > 255 then
    throw "mxu: 1 <= MCOLS <= ROWS <= 255 is required"
  if !powerOfTwo c.lanes || !powerOfTwo c.depth || c.depth < 2 then
    throw "mxu: LANES and DEPTH must be powers of two, DEPTH >= 2"
  if c.implementation > 2 then
    throw "mxu: IMPL must be 0, 1, or 2"
  if c.chainLength == 0 then throw "mxu: CL must be positive"
  if c.implementation == 1 && (c.d % c.chainLength != 0 || c.d / c.chainLength > 64) then
    throw "mxu: cascade CL must divide D and D/CL <= 64"
  if c.implementation == 2 then
    let cls := min (c.d/4) c.chainLength
    if (c.d/4) % cls != 0 then throw "mxu: systolic CL must divide D/4"
    if 16 + clog2 c.d > 25 then throw "mxu: systolic sum width must not exceed 25"

def Config.sumWidth (c : Config) : Nat := 16 + clog2 c.d

def Config.dotLatency (c : Config) : Nat :=
  let ng := c.d / c.chainLength
  let tl := if ng ≤ 1 then 0 else if ng ≤ 4 then 1 else if ng ≤ 16 then 2 else 3
  if c.implementation == 0 then 7 else if c.implementation == 2 then
    min (c.d/4) c.chainLength + c.columns + 3
  else c.chainLength + 1 + tl - (if tl ≥ 3 then 1 else 0)

end OpenTPU.Mxu
