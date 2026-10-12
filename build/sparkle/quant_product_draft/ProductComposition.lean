import Std

/-!
Generic synchronous product composition for a parent and Moore children.

The child state/input/output types may themselves be tuples containing all
children. Thus no special assumption about the number of children is needed.
Parent outputs and child inputs may depend on the current external input and
old child outputs; child outputs depend only on old child state. Every step
updates the parent and children simultaneously.

This theorem checks the logical composition rule only. Instantiating its
hypotheses for generated Quant RTL, authenticating external SAT certificates,
and validating the Lean-to-RTL compiler are separate obligations. In
particular, existence of a related reference initial state does not establish
equivalence for independently chosen arbitrary initial states.
-/
namespace OpenTPU.ProductComposition

structure ParentResponse (P I Y : Type) where
  next : P
  childInput : I
  output : Y

structure System (P C X I O Y : Type) where
  parent : P → X → O → ParentResponse P I Y
  childOutput : C → O
  childNext : C → I → C

variable {P G N X I O Y : Type}

def System.step (system : System P G X I O Y) (state : P × G) (input : X) : P × G :=
  let response := system.parent state.1 input (system.childOutput state.2)
  (response.next, system.childNext state.2 response.childInput)

def System.observe (system : System P G X I O Y) (state : P × G) (input : X) : Y :=
  (system.parent state.1 input (system.childOutput state.2)).output

def Related (childRelation : G → N → Prop) (gold : P × G) (native : P × N) : Prop :=
  gold.1 = native.1 ∧ childRelation gold.2 native.2

def run {S X : Type} (step : S → X → S) (inputs : Nat → X) (initial : S) : Nat → S
  | 0 => initial
  | n + 1 => step (run step inputs initial n) (inputs n)

variable (gold : System P G X I O Y) (native : System P N X I O Y)
variable (childRelation : G → N → Prop)

/-- A parent's next state, child inputs, and visible outputs agree for equal
parent state, external input, and child outputs. -/
def ParentAgrees : Prop :=
  ∀ p x o, gold.parent p x o = native.parent p x o

/-- Moore output equality does not assume equality of current child inputs. -/
def ChildOutputsAgree : Prop :=
  ∀ g n, childRelation g n → gold.childOutput g = native.childOutput n

/-- Each child transition preserves its relation for arbitrary equal inputs. -/
def ChildrenPreserve : Prop :=
  ∀ g n i, childRelation g n →
    childRelation (gold.childNext g i) (native.childNext n i)

theorem step_preserves
    (parentAgrees : ParentAgrees gold native)
    (childOutputs : ChildOutputsAgree gold native childRelation)
    (childSteps : ChildrenPreserve gold native childRelation)
    (g : P × G) (n : P × N) (x : X)
    (related : Related childRelation g n) :
    Related childRelation (gold.step g x) (native.step n x) := by
  rcases g with ⟨gp, gc⟩
  rcases n with ⟨np, nc⟩
  rcases related with ⟨parentEqual, childRelated⟩
  cases parentEqual
  have outputEqual := childOutputs gc nc childRelated
  simp only [System.step, Related]
  rw [outputEqual, parentAgrees]
  exact ⟨rfl, childSteps gc nc _ childRelated⟩

theorem observed_outputs_equal
    (parentAgrees : ParentAgrees gold native)
    (childOutputs : ChildOutputsAgree gold native childRelation)
    (g : P × G) (n : P × N) (x : X)
    (related : Related childRelation g n) :
    gold.observe g x = native.observe n x := by
  rcases related with ⟨parentEqual, childRelated⟩
  simp only [System.observe]
  rw [parentEqual, childOutputs g.2 n.2 childRelated, parentAgrees]

/-- Related initial states stay related at every cycle of any input stream. -/
theorem trace_related
    (parentAgrees : ParentAgrees gold native)
    (childOutputs : ChildOutputsAgree gold native childRelation)
    (childSteps : ChildrenPreserve gold native childRelation)
    (inputs : Nat → X) (g₀ : P × G) (n₀ : P × N)
    (initialRelated : Related childRelation g₀ n₀) :
    ∀ t, Related childRelation (run gold.step inputs g₀ t) (run native.step inputs n₀ t) := by
  intro t
  induction t with
  | zero => exact initialRelated
  | succ t inductionHypothesis =>
    exact step_preserves gold native childRelation parentAgrees childOutputs childSteps
      _ _ (inputs t) inductionHypothesis

/-- An allowed reference initialization witness yields relation and observable
output equality for every cycle, without a fill, reset, or input restriction. -/
theorem initialized_refinement
    (parentAgrees : ParentAgrees gold native)
    (childOutputs : ChildOutputsAgree gold native childRelation)
    (childSteps : ChildrenPreserve gold native childRelation)
    (goldInitial : (P × G) → Prop) (n₀ : P × N)
    (initialWitness : ∃ g₀, goldInitial g₀ ∧ Related childRelation g₀ n₀)
    (inputs : Nat → X) :
    ∃ g₀, goldInitial g₀ ∧ ∀ t,
      Related childRelation (run gold.step inputs g₀ t) (run native.step inputs n₀ t) ∧
      gold.observe (run gold.step inputs g₀ t) (inputs t) =
        native.observe (run native.step inputs n₀ t) (inputs t) := by
  rcases initialWitness with ⟨g₀, initialAllowed, initialRelated⟩
  refine ⟨g₀, initialAllowed, ?_⟩
  intro t
  have related := trace_related gold native childRelation parentAgrees childOutputs
    childSteps inputs g₀ n₀ initialRelated t
  exact ⟨related, observed_outputs_equal gold native childRelation parentAgrees childOutputs
    _ _ (inputs t) related⟩

end OpenTPU.ProductComposition
