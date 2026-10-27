static void am13e_native_motor_publish(AM13ENativeMotor *m)
{
    const double offs[3] = {0.0, -2.0*AM13E_NATIVE_PI/3.0,
                            2.0*AM13E_NATIVE_PI/3.0};
    uint32_t words[3];
    for (int p = 0; p < 3; p++) {
        double bemf = AM13E_NATIVE_KT*m->omega*
                      sin(m->theta+offs[p]);
        double voltage = 1.65+0.02*bemf;
        if (!isfinite(voltage) || voltage < 0.0 || voltage > 3.3) {
            am13e_native_motor_fault(m, 3U);
            return; /* NO silent analog saturation/clipping. */
        }
        uint32_t code = (uint32_t)round(4095.0*voltage/3.3);
        if (code > 4095U) {
            am13e_native_motor_fault(m, 3U);
            return;
        }
        words[p] = 0x10000U | code;
        m->bemf_codes[p] = code;
    }
    uint32_t changed = 0U;
    if (!am13e_g10_stim_vector(&m->machine->feedback, words, &changed)) {
        am13e_native_motor_fault(m, 4U);
        return;
    }
    m->analog_updates += changed;
}
/* Real motor state drives the simulated physical overcurrent inputs.
 * QEMU trip comparator channels n=0/1/2 select W/V/U respectively.
 * Earlier host tests supplied code 1000 as an external zero-current
 * fixture. Native mode instead uses 1000 + 4*abs(I_phase[A]): a
 * deliberately UNCALIBRATED SIM_ONLY sensing assumption. The original
 * CMPSS route, DAC limit, Trip and OST logic remain fully active.
 * Never saturate an unrepresentable reading into a healthy code.
 */
static void am13e_native_motor_publish_oc(AM13ENativeMotor *m)
{
    AM13EMachineState *s = m->machine;
    const unsigned phase_for_oc[3] = {2U, 1U, 0U};
    uint16_t code[3];
    for (unsigned n = 0; n < 3U; ++n) {
        double raw = 1000.0 + 4.0*fabs(m->currents[phase_for_oc[n]]);
        if (!isfinite(raw) || raw > 4095.0) {
            am13e_native_motor_fault(m, 6U);
            return;
        }
        code[n] = (uint16_t)lround(raw);
    }
    for (unsigned n = 0; n < 3U; ++n) {
        s->trip.oc_input[n] = code[n];
        s->trip.oc_valid[n] = true;
    }
    ++m->oc_publications;
    am13e_g13b2_trip_update(s);
}

