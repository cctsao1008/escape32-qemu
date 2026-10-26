/*
 * E62 autonomous, QEMU-virtual-time motor plant, opt-in SIM_ONLY.
 *
 * NOT the legacy Python/WFI replay loop. Never reads Guest PC or WFI.
 * Driven by ACTUAL MCPWM4 clocked AQ/DB history events (not duty).
 * Fixed 1us native virtual timer integrates current/rotor and publishes
 * three modeled back-EMF phase codes into existing CMPSS0 frontend.
 * No firmware register/IRQ/CAP1/TIMG12 writes.
 *
 * ECX87 KV147 datasheet R_LL=0.106 ohm L_LL=48uH, 21 pole pairs,
 * Kt=0.0649, J=1.3e-4 kg*m^2. 24V, friction and ideal diode drop,
 * -30deg initial pose are UNCALIBRATED SIM_ONLY assumptions.
 */
#include <math.h> /* sin, remainder, isfinite, INFINITY, lround */
#define AM13E_NATIVE_MOTOR_BASE UINT32_C(0x5ffeb000)
#define AM13E_NATIVE_MOTOR_SIZE 0x60U
#define AM13E_NATIVE_MOTOR_STEP_NS INT64_C(1000)
#define AM13E_NATIVE_MOTOR_MAGIC UINT32_C(0x4d323645) /* E62M */
#define AM13E_NATIVE_PP 21.0
#define AM13E_NATIVE_KT 0.0649
#define AM13E_NATIVE_J 0.00013
#define AM13E_NATIVE_L 0.000024
#define AM13E_NATIVE_R 0.053
#define AM13E_NATIVE_VBUS 24.0
#define AM13E_NATIVE_DIODE 0.7
#define AM13E_NATIVE_FRICTION 0.0001
#define AM13E_NATIVE_PI 3.14159265358979323846

static void am13e_native_motor_reset(AM13ENativeMotor *m)
{
    if (m->tick_timer) {
        timer_del(m->tick_timer);
    }
    m->active = m->faulted = m->gate = false;
    m->fault_code = m->mask = m->ticks = m->switch_events = 0U;
    m->analog_updates = 0U;
    m->last_ns = 0;
    memset(m->currents, 0, sizeof(m->currents));
    memset(m->bemf_codes, 0, sizeof(m->bemf_codes));
    m->theta = -30.0 * AM13E_NATIVE_PI / 180.0;
    m->omega = 0.0;
    m->last_torque = 0.0;
}
static void am13e_native_motor_fault(AM13ENativeMotor *m, uint32_t code)
{
    if (m->faulted) {
        return;
    }
    m->faulted = true;
    m->fault_code = code;
    if (m->tick_timer) {
        timer_del(m->tick_timer);
    }
    error_report("E62_NATIVE_MOTOR_FAIL_CLOSED code=%u", code);
}

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
        e[p] = AM13E_NATIVE_KT*m->omega*basis[p];
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
    double torque = 0.0;
    for (int p = 0; p < 3; p++) {
        torque += currents[p]*basis[p];
    }
    torque *= AM13E_NATIVE_KT;
    double previous = m->omega;
    double omega = (previous+dt*torque/AM13E_NATIVE_J)/
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
    m->theta = theta;
    m->last_torque = torque;
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
static bool am13e_native_motor_gate_ok(AM13ESimPWM *p)
{
    uint32_t gate = am13e_pwm4_hist_gate_word(p);
    return (gate & 15U) == 15U && p->running &&
           (p->reg[0xb0U/4U] & 0x60000U) == 0U;
}
/* Invoked by native QEMU AQ/DB clock callback or Guest PWM MMIO/Trip
 * event: advance OLD switching state up to this virtual timestamp;
 * immediately latch NEW mask. No ring polling or host control. */
static void am13e_native_motor_pwm_event(AM13ESimPWM *p,
                                         uint32_t newmask, bool valid)
{
    AM13ENativeMotor *m = &p->machine->native_motor;
    if (!m->enabled || m->faulted) {
        return;
    }
    bool gate = am13e_native_motor_gate_ok(p);
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    if (m->active && !am13e_native_motor_advance(m, now)) {
        am13e_native_motor_fault(m, 1U);
        return;
    }
    if (gate && !valid) {
        am13e_native_motor_fault(m, 2U);
        return; /* Never accept an invalid source-level evaluator. */
    }
    for (int k = 0; k < 3; k++) {
        if ((newmask & (3U << (2*k))) == (3U << (2*k)) && gate) {
            am13e_native_motor_fault(m, 5U); /* G14 same-leg overlap */
            return;
        }
    }
    if (!m->active && gate && valid && newmask) {
        m->active = true;
        m->last_ns = now;
        timer_mod(m->tick_timer, now+AM13E_NATIVE_MOTOR_STEP_NS);
    }
    if (m->active) {
        m->mask = newmask & 0x3fU;
        m->gate = gate && valid;
        ++m->switch_events;
        am13e_native_motor_publish(m);
    }
}
/* Native virtual-clock callback; no PC/WFI/GDB requirement.
 * Rotor and analog voltage run while original Guest is executing.
 */
static void am13e_native_motor_tick(void *opaque)
{
    AM13ENativeMotor *m = opaque;
    if (!m->enabled || !m->active || m->faulted) {
        return;
    }
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    if (!am13e_native_motor_advance(m, now)) {
        am13e_native_motor_fault(m, 1U);
        return;
    }
    ++m->ticks;
    am13e_native_motor_publish(m);
    if (!m->faulted) {
        timer_mod(m->tick_timer, now+AM13E_NATIVE_MOTOR_STEP_NS);
    }
}
/* Read-only SIM_ONLY instrumentation, never a Guest silicon MMIO. */
static MemTxResult am13e_native_motor_read(void *opaque, hwaddr off,
                                         uint64_t *v, unsigned size,
                                         MemTxAttrs attrs)
{
    AM13ENativeMotor *m = opaque;
    if (!m->enabled || !m->machine->esc_sim || size != 4U ||
        (off & 3U) || off >= AM13E_NATIVE_MOTOR_SIZE) {
        return MEMTX_ERROR;
    }
    switch (off) {
    case 0x00: *v=AM13E_NATIVE_MOTOR_MAGIC; break;
    case 0x04: *v=(m->enabled?1U:0U)|(m->active?2U:0U)|
                   (m->faulted?4U:0U)|(m->gate?8U:0U); break;
    case 0x08: *v=m->ticks; break;
    case 0x0c: *v=m->switch_events; break;
    case 0x10: *v=m->analog_updates; break;
    case 0x14: *v=m->fault_code; break;
    case 0x18: *v=m->mask; break;
    case 0x1c: *v=m->bemf_codes[0]; break;
    case 0x20: *v=m->bemf_codes[1]; break;
    case 0x24: *v=m->bemf_codes[2]; break;
    case 0x28: *v=(uint32_t)m->last_ns; break;
    case 0x2c: *v=(uint64_t)m->last_ns>>32U; break;
    case 0x30: *v=(uint32_t)lround(m->omega*60.0/
                                   (2.0*AM13E_NATIVE_PI)); break;
    case 0x34: *v=(uint32_t)lround(m->theta*180000.0/
                                   AM13E_NATIVE_PI); break;
    default: return MEMTX_ERROR;
    }
    return MEMTX_OK;
}
static MemTxResult am13e_native_motor_write(void *opaque, hwaddr off,
                                          uint64_t value, unsigned size,
                                          MemTxAttrs attrs)
{
    return MEMTX_ERROR;
}
static const MemoryRegionOps am13e_native_motor_ops = {
    .read_with_attrs = am13e_native_motor_read,
    .write_with_attrs = am13e_native_motor_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size=4, .max_access_size=4 },
};
