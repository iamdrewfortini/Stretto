# SPDX-License-Identifier: Apache-2.0
"""Three SYNTHETIC procedures for tests and demos (illustrative; not real service manuals, and not the owner's recorded jobs)."""
from .procedure import Procedure, step as S

def gearbox():
    return Procedure([
        S("g0", "Photograph the housing before disassembly", adds=["photo_taken"]),
        S("g1", "Unplug the opener", adds=["unplugged"]),
        S("g2", "Remove the light cover and bulb", requires=["unplugged"], adds=["cover_off"]),
        S("g3", "Release the trolley with the emergency cord", requires=["unplugged"], adds=["trolley_released"]),
        S("g4", "Remove the drive belt", requires=["trolley_released"], adds=["belt_off"], removes=["belt_on"], warnings=["belt is under tension"]),
        S("g5", "Unbolt the motor housing", requires=["unplugged", "cover_off"], adds=["housing_open"], removes=["housing_closed"], tools=["socket set"]),
        S("g6", "Remove the worn gear and clean the housing", requires=["housing_open", "belt_off"], adds=["gear_out"]),
        S("g7", "Inspect the gear shaft for wear", requires=["gear_out"], adds=["shaft_ok"]),
        S("g8", "Grease and seat the new gear", requires=["shaft_ok"], adds=["gear_in"], removes=["gear_out"]),
        S("g9", "Close the housing", requires=["gear_in"], adds=["housing_closed"], removes=["housing_open"]),
        S("g10", "Refit the drive belt", requires=["housing_closed"], adds=["belt_on"], removes=["belt_off"]),
        S("g11", "Replace the light cover", requires=["cover_off"], adds=["cover_on"], removes=["cover_off"]),
        S("g12", "Reconnect power and test a full cycle", requires=["belt_on", "cover_on"], adds=["tested"]),
    ], initial=["belt_on", "housing_closed"], goal=["tested", "gear_in"])

def rack():
    return Procedure([
        S("r0", "Take a photo of the empty rack position", adds=["photo_taken"]),
        S("r1", "Confirm rack space and power budget", adds=["plan_ok"]),
        S("r2", "Mount the rails in the rack", requires=["plan_ok"], adds=["rails_on"], tools=["rail kit"]),
        S("r3", "Unbox the server and install RAM and disks", adds=["server_ready"]),
        S("r4", "Slide the server onto the rails", requires=["rails_on", "server_ready"], adds=["server_racked"]),
        S("r5", "Connect power cables to PDU A and B", requires=["server_racked"], adds=["powered"]),
        S("r6", "Connect network cables and label them", requires=["server_racked"], adds=["cabled"]),
        S("r7", "Boot and set the management address", requires=["powered", "cabled"], adds=["booted"]),
        S("r8", "Install the operating system from the image", requires=["booted"], adds=["os_installed"]),
        S("r9", "Register the server in inventory", requires=["os_installed"], adds=["inventoried"]),
    ], goal=["inventoried"])

def detailing():
    return Procedure([
        S("d0", "Photograph the vehicle before starting", adds=["photo_taken"]),
        S("d1", "Rinse the vehicle", adds=["rinsed"]),
        S("d2", "Foam and hand wash", requires=["rinsed"], adds=["washed"]),
        S("d3", "Rinse off the soap", requires=["washed"], adds=["soap_off"]),
        S("d4", "Dry with microfiber towels", requires=["soap_off"], adds=["dry"]),
        S("d5", "Clay bar the paint", requires=["dry"], adds=["smooth"]),
        S("d6", "Polish the paint", requires=["smooth"], adds=["polished"]),
        S("d7", "Apply sealant", requires=["polished"], adds=["sealed"]),
        S("d8", "Clean the glass", requires=["dry"], adds=["glass_clean"]),
        S("d9", "Dress the tires", requires=["dry"], adds=["tires_done"]),
        S("d10", "Final inspection", requires=["sealed", "glass_clean", "tires_done"], adds=["inspected"]),
    ], goal=["inspected"])

ALL = {"garage-door gearbox": gearbox, "server rack install": rack, "vehicle detailing": detailing}
