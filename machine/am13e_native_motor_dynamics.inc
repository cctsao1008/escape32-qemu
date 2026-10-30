/* Exact idealized 3-phase star / body-diode constrained back-Euler
 * active-set solver. Preserve winding currents across switch events.
 * OPEN terminal requires i=0 only at ENDPOINT; no forced projection
 * at the switch instant. Compare to Python host solver separately.
 */
static bool am13e_native_motor_current_step(AM13ENativeMotor *m, double dt)
{
    const double offs[3] = {0.0, -2.0*AM13E_NATIVE_PI/3.0,
                            2.0*AM13E_NATIVE_PI/3.0};
    double basis[3], e[3], old[3], currents[3], nu = 0.0;
    const double h = dt / AM13E_NATIVE_L;
    const double inv = 1.0 / (1.0 + h*AM13E_NATIVE_R);
    uint32_t masks = m->gate ? m->mask : 0U;
    int driven[3], nfree = 0, freephase[3];
    for (int p = 0; p < 3; p++) {
        bool hi = !!(masks & (1U << (2*p)));
        bool lo = !!(masks & (1U << (2*p+1)));
        if (hi && lo) {
            return false; /* Original G14 unsafe overlap NOT waived. */
        }
        driven[p] = hi ? 1 : lo ? 2 : 0;
        if (!driven[p]) {
            freephase[nfree++] = p;
        }
        basis[p] = sin(m->theta + offs[p]);
        e[p] = AM13E_NATIVE_K_PHASE*m->omega*basis[p];
        old[p] = m->currents[p];
    }
    int combinations = 1;
    for (int j = 0; j < nfree; j++) {
        combinations *= 3;
    }
    bool solved = false;
    for (int trial = 0; trial < combinations && !solved; trial++) {
        int state[3], mode = trial;
        double volts[3], sum = 0.0;
        int fixed = 0;
        for (int p = 0; p < 3; p++) {
            state[p] = driven[p];
        }
        for (int j = 0; j < nfree; j++) {
            state[freephase[j]] = (mode%3 == 0 ? 0 :
                                   mode%3 == 1 ? 3 : 4);
            mode /= 3;
        }
        for (int p = 0; p < 3; p++) {
            if (state[p] == 0) {
                continue;
            }
            volts[p] = state[p] == 1 ? AM13E_NATIVE_VBUS :
                       state[p] == 2 ? 0.0 :
                       state[p] == 3 ? -AM13E_NATIVE_DIODE :
                                      AM13E_NATIVE_VBUS+AM13E_NATIVE_DIODE;
            sum += old[p]/h + volts[p] - e[p];
            fixed++;
        }
        if (fixed) {
            nu = sum/fixed;
        } else {
            double lower = -INFINITY, upper = INFINITY;
            for (int p = 0; p < 3; p++) {
                double offset = e[p] - old[p]/h;
                lower = MAX(lower, -AM13E_NATIVE_DIODE-offset);
                upper = MIN(upper, AM13E_NATIVE_VBUS+
                                  AM13E_NATIVE_DIODE-offset);
            }
            if (lower > upper + 1e-10) {
                continue;
            }
            nu = (lower+upper)/2.0;
        }
        bool admissible = true;
        double icheck = 0.0, iabs = 1.0;
        for (int p = 0; p < 3; p++) {
            if (state[p] == 0) {
                double v = nu+e[p]-old[p]/h;
                if (v < -AM13E_NATIVE_DIODE-1e-8 ||
                    v > AM13E_NATIVE_VBUS+AM13E_NATIVE_DIODE+1e-8) {
                    admissible = false;
                    break;
                }
                currents[p] = 0.0;
            } else {
                currents[p] = (old[p]+h*(volts[p]-nu-e[p]))*inv;
                if ((state[p] == 3 && currents[p] < -1e-9) ||
                    (state[p] == 4 && currents[p] > 1e-9)) {
                    admissible = false;
                    break;
                }
            }
            icheck += currents[p];
            iabs = MAX(iabs, fabs(currents[p]));
            if (!isfinite(currents[p])) {
                admissible = false;
            }
        }
        if (!admissible || fabs(icheck) > 1e-8*iabs) {
            continue;
        }
        solved = true;
    }
    if (!solved) {
        return false;
    }
    /* Electrical energy identity is independently checked at EACH
     * backward-Euler step. At floating-open terminals endpoint I=0;
     * diode voltages are modeled explicitly, no switch projection.
     * delta E_magnetic + numerical Euler loss + I²R + eI == VI.
     * This is not a calibration or convergence certificate by itself.
     */
    double terminal_j=0.0, bus_j=0.0, diode_j=0.0;
    double copper_j=0.0, bemf_j=0.0, magnetic_j=0.0, euler_j=0.0;
    bool diode_used=false;
    for (int p=0;p<3;p++) {
        int state = driven[p];
        /* The winning active-set diode state must be remembered; it
         * is not simply the initially commanded MOSFET leg. */
        if (state == 0 && currents[p] != 0.0) {
            /* inferred from the actual terminal diode voltage and
             * current polarity; the current solver checks signs. */
            state = currents[p] > 0.0 ? 3 : 4;
        }
        double voltage = state == 1 ? AM13E_NATIVE_VBUS :
                         state == 2 ? 0.0 :
                         state == 3 ? -AM13E_NATIVE_DIODE :
                         state == 4 ? AM13E_NATIVE_VBUS+AM13E_NATIVE_DIODE :
                         0.0;
        double i = currents[p], di=i-old[p];
        terminal_j += voltage*i*dt;
        if (state == 1 || state == 4) bus_j += AM13E_NATIVE_VBUS*i*dt;
        if (state == 3 || state == 4) {
            diode_j += AM13E_NATIVE_DIODE*fabs(i)*dt;
            diode_used=true;
        }
        copper_j += AM13E_NATIVE_R*i*i*dt;
        bemf_j += e[p]*i*dt;
        magnetic_j += 0.5*AM13E_NATIVE_L*(i*i-old[p]*old[p]);
        euler_j += 0.5*AM13E_NATIVE_L*di*di;
    }
    double residual = terminal_j-copper_j-bemf_j-magnetic_j-euler_j;
    double scale = MAX(1.0,fabs(terminal_j));
    if (!isfinite(residual) || fabs(residual)>1e-8*scale ||
        fabs(bus_j-diode_j-terminal_j)>1e-8*scale) {
        return false; /* energy identity fails CLOSED */
    }
    double torque = 0.0;
    for (int p = 0; p < 3; p++) {
        torque += currents[p]*basis[p];
    }
    torque *= AM13E_NATIVE_K_PHASE;
    double previous = m->omega;
    /* APC static V=0 analytic propeller load is an OPT-IN product-study
     * assumption. Do not inject its rotor angle, speed, or torque to Guest. */
    double prop_torque = AM13E_NATIVE_APC ?
        am13e_native_apc_prop_torque(previous) : 0.0;
    if (!isfinite(prop_torque)) {
        return false; /* No unsupported >6000rpm extrapolation. */
    }
    double omega = (previous+dt*(torque-prop_torque)/AM13E_NATIVE_J)/
                   (1.0+dt*AM13E_NATIVE_FRICTION/AM13E_NATIVE_J);
    double theta = remainder(m->theta+AM13E_NATIVE_PP*
                             (previous+omega)*dt/2.0,
                             2.0*AM13E_NATIVE_PI);
    if (!isfinite(torque) || !isfinite(omega) || !isfinite(theta) ||
        fabs(omega)*AM13E_NATIVE_PP*dt > 0.35) {
        return false;
    }
    memcpy(m->currents, currents, sizeof(currents));
    m->omega = omega;
    m->theta_unwrapped += AM13E_NATIVE_PP*(previous+omega)*dt/2.0;
    m->theta = theta;
    m->last_torque = torque;
    m->last_prop_torque = prop_torque;
    m->energy_bus_j += bus_j;
    m->energy_diode_j += diode_j;
    m->energy_copper_j += copper_j;
    m->energy_bemf_j += bemf_j;
    m->energy_magnetic_j += magnetic_j;
    m->energy_backward_euler_j += euler_j;
    m->energy_abs_residual_j += fabs(residual);
    m->energy_max_residual_j = MAX(m->energy_max_residual_j,fabs(residual));
    m->energy_max_star_sum_a = MAX(m->energy_max_star_sum_a,
                                   fabs(currents[0]+currents[1]+currents[2]));
    ++m->energy_steps;
    m->energy_diode_steps += diode_used;
    return true;
}
static bool am13e_native_motor_advance(AM13ENativeMotor *m, int64_t now)
{
    if (now < m->last_ns || now-m->last_ns > INT64_C(10000000)) {
        return false; /* No catch-up after unobserved >10ms virtual gap. */
    }
    int64_t remain = now-m->last_ns;
    while (remain > 0) {
        int64_t ns = MIN(remain, AM13E_NATIVE_MOTOR_STEP_NS);
        if (!am13e_native_motor_current_step(m, ns*1e-9)) {
            return false;
        }
        remain -= ns;
    }
    m->last_ns = now;
    return true;
}
