from util import database, toolchain, bitdiff, progress


with database.transact() as db:
    for device_name, device in db.items():
        if not device_name.endswith("BE"): continue

        progress(device_name)

        package, pinout = next(iter(device['pins'].items()))
        config = device['global']['config']

        def run_used(pad, **kwargs):
            return toolchain.run(
                f"module top(input I, output Q); "
                f"assign Q = I; "
                f"endmodule",
                {'I': pinout[pad]},
                f"{device_name}-{package}", **kwargs)

        def run_unused(except_pads, **kwargs):
            ins  = []
            outs = []
            code = []
            pins = {}

            index = 0
            code.append(f"wire Y{index};")
            for pad, pin in pinout.items():
                if pad in except_pads: continue
                pins[pad] = pin
                if pad.startswith("M"):
                    outs.append(pad)
                    code.append(f"OR2 o{index}(1'b0, Y{index}, {pad}); "
                                f"wire Y{index+1} = {pad}; ")
                else:
                    ins .append(pad)
                    code.append(f"wire Y{index+1}; "
                                f"OR2 o{index}(Y{index}, {pad}, Y{index+1}); ")
                index += 1
            code.append(f"DFF dff(1'b0, Y{index}, Y0); ")

            return toolchain.run(
                f"module top(input {', '.join(ins)}, output {', '.join(outs)}); "
                f"{' '.join(code)} "
                f"endmodule",
                pins,
                f"{device_name}-{package}", **kwargs)

        for pad, net_name in (
            ('R',  'r_pad'),
            ('C1', 'c1_pad'),
            ('C2', 'c2_pad'),
            ('E1', 'e1_pad'),
        ):
            f_norm    = run_used(pad)
            f_hyst    = run_used(pad, strategy={'schmitt_trigger':'I'})

            # The fitter contains an atrocious bug that causes it to be unable to distinguish
            # between termination on pins 38 and 40 (TQFP-44). We work around that by setting
            # the termination for all unused pins, and making sure exactly one pin is unused.
            #
            # Depressing.
            f_highz   = run_unused(pad)
            f_pullup  = run_unused(pad, strategy={'pull_up_Unused':'on'})
            f_pulldn  = run_unused(pad, strategy={'unused_To_Ground':'on'})
            f_pinkeep = run_unused(pad, strategy={'unused_To_PinKeeper':'on'})

            config.update({
                f"{net_name}_schmitt_trigger": bitdiff.describe(1, {
                    'off': f_norm,
                    'on':  f_hyst,
                }),
                f"{net_name}_term": bitdiff.describe(2, {
                    'high_z':     f_highz,
                    'pull_up':    f_pullup,
                    'pull_down':  f_pulldn,
                    'bus_keeper': f_pinkeep
                })
            })
