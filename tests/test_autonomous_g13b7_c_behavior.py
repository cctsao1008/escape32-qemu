#!/usr/bin/env python3
"""Compile original QEMU C function bodies in deterministic filter/vector stub.

This unit test executes extracted *production function bodies*, not a
parallel Python approximation. QEMU full native tests remain required.
"""
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract_function(source, signature):
    offset = source.find(signature)
    if offset < 0 or source.find(signature, offset + 1) >= 0:
        raise AssertionError('Expected exactly one function: '+signature)
    open_brace = source.find('{', offset)
    if open_brace < 0:
        raise AssertionError('Missing body: '+signature)
    nesting = 0
    for i in range(open_brace,len(source)):
        if source[i] == '{':
            nesting += 1
        elif source[i] == '}':
            nesting -= 1
            if nesting == 0:
                return source[offset:i+1]
    raise AssertionError('Unterminated body: '+signature)


class NativeCFunctionBehavior(unittest.TestCase):
    def test_comparator_filter_and_atomic_vector_behavior(self):
        feedback = (ROOT/'machine/am13e_motor_feedback.inc').read_text()
        sync = extract_function(feedback,
            'static void am13e_g10_pwm_sync(AM13ESimFeedback *f)')
        vector = extract_function(feedback,
            'static bool am13e_g10_stim_vector(AM13ESimFeedback *f,')
        stub = textwrap.dedent(r"""
            #include <stdint.h>
            #include <stdbool.h>
            #include <assert.h>
            #include <string.h>
            typedef struct AM13EMachineState { bool esc_sim; } AM13EMachineState;
            typedef struct AM13ESimFeedback {
                uint16_t cmp[128];
                uint32_t phase_code[3];
                bool phase_valid[3];
                AM13EMachineState *machine;
            } AM13ESimFeedback;
            static bool filter_inflight;
            static unsigned eval_count, route_changes, coherent_reads;
            static bool am13e_g10_cmp_powered(AM13ESimFeedback *f) {
                (void)f; return true;
            }
            static void am13e_g10_cmp_evaluate(AM13ESimFeedback *f) {
                ++eval_count;
                filter_inflight=false; /* real evaluator cancels its timer */
                if (f->phase_code[0]==100 && f->phase_code[1]==200 &&
                    f->phase_code[2]==300 && f->phase_valid[0] &&
                    f->phase_valid[1] && f->phase_valid[2]) {
                    ++coherent_reads;
                }
            }
            static void am13e_auto_route_changed(AM13EMachineState *s) {
                (void)s; ++route_changes;
            }
        """)
        body = textwrap.dedent(r"""
            int main(void) {
                AM13EMachineState machine={.esc_sim=true};
                AM13ESimFeedback f={.machine=&machine};
                f.cmp[0x08/2]=0x80U;
                f.cmp[0x0e/2]=2048U;
                f.cmp[0x0c/2]=2048U;
                filter_inflight=true;
                am13e_g10_pwm_sync(&f);
                assert(filter_inflight && eval_count==0 && route_changes==0);
                f.cmp[0x0c/2]=2100U;
                am13e_g10_pwm_sync(&f);
                assert(!filter_inflight && eval_count==1 && route_changes==1);
                assert(f.cmp[0x0e/2]==2100U);

                uint32_t writes=0;
                uint32_t values[3]={0x10000U|100U,0x10000U|200U,0x10000U|300U};
                eval_count=route_changes=coherent_reads=0U;
                filter_inflight=true;
                assert(am13e_g10_stim_vector(&f,values,&writes));
                assert(writes==3 && eval_count==1 && coherent_reads==1);
                assert(!filter_inflight);
                filter_inflight=true;
                assert(am13e_g10_stim_vector(&f,values,&writes));
                assert(writes==3 && eval_count==1 && filter_inflight);
                values[2]=0x20000U;  /* rejects all, not partial mutate */
                assert(!am13e_g10_stim_vector(&f,values,&writes));
                assert(writes==3 && eval_count==1 && f.phase_code[2]==300U);
                return 0;
            }
        """)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            (p/'fixture.c').write_text(stub+sync+'\n'+vector+'\n'+body)
            compile=subprocess.run(
                ['cc','-std=c11','-Wall','-Wextra','-Werror',
                 str(p/'fixture.c'),'-o',str(p/'fixture')],
                capture_output=True,text=True)
            self.assertEqual(compile.returncode,0,compile.stderr)
            result=subprocess.run([str(p/'fixture')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':
    unittest.main()
