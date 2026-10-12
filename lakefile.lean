import Lake
open Lake DSL

package opentpu where

require sparkle from "../sparkle"

@[default_target]
lean_lib OpenTPU where

lean_exe «opentpu-gen» where
  root := `OpenTPU.Generate

lean_exe «opentpu-test» where
  root := `OpenTPU.Tests

lean_exe «opentpu-backend-check» where
  root := `OpenTPU.BackendCheck
