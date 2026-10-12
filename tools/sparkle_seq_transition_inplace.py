"""Seq negative-control transition exposure without duplicating the netlist.

The checks and transformation match sparkle_transition.expose_steps exactly;
only ownership differs: this function consumes and mutates its input. Tests
compare their ASTs and their outputs, including rejected incomplete mappings.
"""

def expose_steps_inplace(netlist, states):
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

