"""Expose complete synchronous state for an exact one-step equivalence proof.

Both modules' current register bits become shared arbitrary inputs. Every D bit
becomes a checked next-state output. This proves the induction step directly,
without asking SAT to rediscover equality of separate copies of current state.
No datapath is abstracted. Callers must separately establish their intended
initial-state relation (for dispatch it is equality of every register bit).
"""
import copy


def expose_steps(netlist, states):
    netlist = copy.deepcopy(netlist)
    for name, module in netlist["modules"].items():
        q_to_d = {}
        remove = []
        clock = module["ports"]["clk"]["bits"]
        for cell_name, cell in module["cells"].items():
            kind = cell["type"]
            if kind == "$dff":
                ports = cell["connections"]
                if ports["CLK"] != clock or int(cell["parameters"]["CLK_POLARITY"], 2) != 1:
                    raise RuntimeError(f"{name}: unsupported clock on {cell_name}")
                if len(ports["Q"]) != len(ports["D"]):
                    raise RuntimeError(f"{name}: malformed flop {cell_name}")
                for q, d in zip(ports["Q"], ports["D"]):
                    if not isinstance(q, int) or q in q_to_d:
                        raise RuntimeError(f"{name}: multiply driven or constant state bit")
                    q_to_d[q] = d
                remove.append(cell_name)
            elif kind not in {"$mux", "$pmux", "$bmux", "$bwmux", "$demux", "$eq", "$ne", "$eqx", "$add", "$sub", "$mul", "$div", "$mod", "$shift", "$shiftx",
                              "$not", "$neg", "$logic_not", "$logic_and", "$logic_or", "$and", "$or",
                              "$xor", "$xnor", "$reduce_and", "$reduce_or", "$reduce_xor",
                              "$reduce_bool", "$lt", "$le", "$gt", "$ge", "$shl", "$shr", "$sshr"}:
                raise RuntimeError(f"{name}: unsupported cell in transition proof: {kind}")
        covered = set()
        for state, width in states.items():
            bits = module["netnames"][state]["bits"]
            if len(bits) != width or any(b not in q_to_d or b in covered for b in bits):
                raise RuntimeError(f"{name}: incomplete/overlapping state correspondence for {state}")
            covered.update(bits)
            for port, direction, value in [(f"state_{state}", "input", bits),
                                           (f"next_{state}", "output", [q_to_d[b] for b in bits])]:
                if port in module["ports"] or port in module["netnames"]:
                    raise RuntimeError(f"{name}: transition port collision: {port}")
                module["ports"][port] = {"direction": direction, "bits": value}
                module["netnames"][port] = {"hide_name": 0, "bits": value, "attributes": {}}
        if covered != set(q_to_d):
            raise RuntimeError(f"{name}: state mapping omits {len(set(q_to_d)-covered)} flip-flop bits")
        for cell in remove:
            del module["cells"][cell]
        for net in module["netnames"].values():
            net.get("attributes", {}).pop("init", None)
    return netlist


def step_miter(netlist):
    if set(netlist["modules"]) != {"gold", "gate"}:
        raise RuntimeError("transition proof expects exactly gold and gate modules")
    gold = netlist["modules"]["gold"]["ports"]
    gate = netlist["modules"]["gate"]["ports"]
    if set(gold) != set(gate) or any(
        gold[p]["direction"] != gate[p]["direction"] or len(gold[p]["bits"]) != len(gate[p]["bits"])
        for p in gold):
        raise RuntimeError("transition proof port interface mismatch")
    inputs, outputs = [], []
    for p, decl in gold.items():
        (inputs if decl["direction"] == "input" else outputs).append((p, len(decl["bits"])))
    ports = [f"input wire [{w-1}:0] {p}" for p, w in inputs] + ["output wire ok"]
    lines = ["module step_miter(\n" + ",\n".join(ports) + "\n);"]
    for p, w in outputs:
        lines.append(f"wire [{w-1}:0] gold_{p}, gate_{p};")
    for kind in ["gold", "gate"]:
        connections = [f".{p}({p})" for p, _ in inputs]
        connections += [f".{p}({kind}_{p})" for p, _ in outputs]
        lines.append(f"{kind} {kind}_instance(" + ",".join(connections) + ");")
    lines.append("assign ok = " + " &&\n".join(f"gold_{p} == gate_{p}" for p, _ in outputs) + ";")
    lines.append("endmodule\n")
    return "\n".join(lines)
