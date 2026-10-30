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
PRE_PROFILE_HEAD="0b6ffa3397c6ece17ffd115df62ea2bf6abc72b8"
# Immutable pre-profile main tree. Its refactor was an exact source split;
# current main has intentional opt-in motor profile changes.
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

def _git_content(commit, path):
    proc=subprocess.run(["git","show",f"{commit}:{path}"],
                        cwd=ROOT,text=True,capture_output=True,check=False)
    if proc.returncode:
        raise AssertionError("Historical source unavailable: "+path+
                             "\\n"+proc.stderr[-500:])
    return proc.stdout

def recomposed_source(commit=None):
    document=(_git_content(commit,f"machine/{ORIGINAL}") if commit else
              (MACHINE/ORIGINAL).read_text())
    for name in MODULES:
        marker=f'#include "{name}"\n'
        if document.count(marker)!=1:
            raise AssertionError("Missing or duplicated module include: "+name)
        module=(_git_content(commit,f"machine/{name}") if commit else
                (MACHINE/name).read_text())
        document=document.replace(marker,module,1)
    return document

class OriginalVirtualClockModuleContract(unittest.TestCase):
    def test_exact_pre_profile_refactor_equivalence(self):
        # Preserve the original *historical* exact-byte refactor contract.
        # It cannot legitimately compare expanded, opt-in new model source
        # to an immutable 2026 pre-refactor source and claim no drift.
        self.assertEqual(recomposed_source(PRE_PROFILE_HEAD),historical_source(),
                         "Frozen original module split must remain byte-identical")

    def test_current_opt_in_profile_does_not_claim_historical_source_identity(self):
        source=recomposed_source()
        self.assertNotEqual(source,historical_source(),
                            "Current QEMU profile extension must not be labeled "
                            "byte-identical historical motor source")
        body=(MACHINE/ORIGINAL).read_text()
        self.assertIn('case 0x8c:',body)
        self.assertIn('case 0x98:',body)
        self.assertIn('case 0x9c:',body)
        self.assertIn('am13e_native_motor_tick',body)
        self.assertIn('AM13E_NATIVE_K_PHASE',source)
        self.assertIn('m->model_profile == 210U',source)

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
