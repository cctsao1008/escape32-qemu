#!/usr/bin/env python3
"""E62 QEMU single-virtual-clock module split: fail-closed source contract.

The refactor MUST preserve the *exact* original C implementation after
textual module expansion, not merely a similar simulation result. This
independently prevents current-step, gate, BEMF, IRQ, or timing waivers.
CI fetches the pinned pre-refactor commit as read-only history.
"""
from __future__ import annotations
import pathlib
import re
import subprocess
import sys
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
OLD_HEAD="ed29fc304c45465d9144343ef8a9264ddad8b067"
MACHINE=ROOT/"machine"
ORIGINAL="am13e_native_motor_plant.inc"
MODULES=(
    "am13e_native_motor_dynamics.inc",
    "am13e_native_analog_frontend.inc",
    "am13e_native_pwm_coupling.inc",
)

def historical_source():
    proc=subprocess.run(["git","show",f"{OLD_HEAD}:machine/{ORIGINAL}"],
                        cwd=ROOT,text=True,capture_output=True,check=False)
    if proc.returncode:
        raise AssertionError("Pre-refactor source unavailable; need "
                             "fetch-depth: 0 or fetch pinned old commit: "+
                             proc.stderr[-500:])
    return proc.stdout

def recomposed_source():
    document=(MACHINE/ORIGINAL).read_text()
    for name in MODULES:
        marker=f'#include "{name}"\n'
        if document.count(marker)!=1:
            raise AssertionError("Missing or duplicated module include: "+name)
        document=document.replace(marker,(MACHINE/name).read_text(),1)
    return document

class OriginalVirtualClockModuleContract(unittest.TestCase):
    def test_exact_source_equivalence(self):
        self.assertEqual(recomposed_source(),historical_source(),
                         "Refactoring must preserve original C function bodies "
                         "byte-for-byte, including callback ordering")

    def test_module_order_and_no_host_threads(self):
        body=(MACHINE/ORIGINAL).read_text()
        offsets=[body.index(f'#include "{name}"') for name in MODULES]
        self.assertEqual(offsets,sorted(offsets))
        for name in MODULES:
            mod=(MACHINE/name).read_text()
            self.assertFalse(re.search(r"\bpthread_(?:create|join)\b|"
                                       r"\bqemu_thread_create\b|"
                                       r"\bstd::thread\b",mod),name)
        self.assertIn("am13e_native_motor_tick",body)
        self.assertIn("AM13E_NATIVE_MOTOR_STEP_NS",body)

    def test_original_source_owned_pwm_and_analog_paths(self):
        pwm_history=(MACHINE/"am13e_pwm_history.inc").read_text()
        coupler=(MACHINE/MODULES[2]).read_text()
        analog=(MACHINE/MODULES[1]).read_text()
        feedback=(MACHINE/"am13e_motor_feedback.inc").read_text()
        dynamics=(MACHINE/MODULES[0]).read_text()
        self.assertIn("am13e_native_motor_pwm_event(p, mask, true);",
                      pwm_history)
        self.assertIn("am13e_native_motor_advance(m, now)",coupler)
        self.assertLess(coupler.index("am13e_native_motor_advance(m, now)"),
                        coupler.index("m->mask = newmask"))
        self.assertIn("m->currents",dynamics)
        self.assertIn("am13e_g10_stim_vector(",analog)
        self.assertIn("am13e_g10_cmp_evaluate(f)",feedback)
        self.assertIn("am13e_g10_ecap_edge(f, level)",feedback)

    def test_qemu_build_entrypoint_is_executable(self):
        self.assertTrue(((ROOT/"build.sh").stat().st_mode & 0o111) != 0,
                        "QEMU build.sh must keep git executable mode 100755")

    def test_qemu_worktree_materializes_every_native_module(self):
        script=(ROOT/"build.sh").read_text()
        for name in MODULES:
            self.assertIn(f"'{name}'",script)
        self.assertIn("module_source.is_symlink()",script)
        self.assertIn("module_target.is_symlink()",script)
        self.assertIn("module_target.write_bytes(module_source.read_bytes())",
                      script)
        self.assertIn("module_target.read_bytes() != module_source.read_bytes()",
                      script)

    def test_p1_diagnostic_and_qualification_source_not_replaced(self):
        controller=(ROOT/"tools/native_p1_qualification.py").read_text()
        self.assertIn("STARTUP_SIGNIFICANT_DIRECTION_REVERSAL",controller)
        self.assertIn("SIGNIFICANT", (ROOT/"tools/native_p0_strict.py").read_text())
        self.assertIn("significant_rotor_direction_changes",controller)

if __name__=="__main__":
    unittest.main(verbosity=2)
