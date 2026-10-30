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
#define AM13E_NATIVE_MOTOR_SIZE 0xb4U
#define AM13E_NATIVE_MOTOR_STEP_NS INT64_C(1000)
#define AM13E_NATIVE_MOTOR_MAGIC UINT32_C(0x4d323645) /* E62M */
#define AM13E_NATIVE_PP 21.0
/* maxon EC 87 flat UAV KV147 (April 2025), terminal Kt=64.9 mNm/A,
 * Kn=147 rpm/V. These are terminal-equivalent constants, NOT the
 * peak amplitude of one sinusoidal phase BEMF.
 *
 * Balanced sinusoidal star: max(e_hi-e_lo) / omega_mech =
 * sqrt(3) * K_phase. Matching the published terminal Kt = Ke_ll_peak
 * therefore requires K_phase=Kt_terminal/sqrt(3).
 *
 * e_phase=K_phase*omega_mech*sin(theta_e+offset) and
 * T=K_phase*sum(I_phase*sin(theta_e+offset)). The SAME constant in
 * both expressions enforces sum(e_phase*I_phase)=T*omega_mech.
 * This convention is a datasheet-equivalent SIM_ONLY approximation:
 * the actual motor's phase waveform/driver/load are not calibrated.
 */
/* Exactly two bounded source models: default KV147 preserves the
 * historical native QEMU plant; opt-in KV210 uses maxon p.1 R/L/Kt.
 * All expansions occur in functions with the AM13ENativeMotor *m. */
#define AM13E_NATIVE_KT_TERMINAL (m->model_profile == 210U ? 0.0454 : 0.0649)
#define AM13E_NATIVE_K_PHASE (AM13E_NATIVE_KT_TERMINAL / 1.7320508075688772935)
#define AM13E_NATIVE_J 0.00013
#define AM13E_NATIVE_L (m->model_profile == 210U ? 0.00000875 : 0.000024)
#define AM13E_NATIVE_R (m->model_profile == 210U ? 0.0283 : 0.053)
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
    memset(m->phase_adc_publications, 0, sizeof(m->phase_adc_publications));
    /* Retain machine-property stress amplitude across QEMU resets;
     * clear only epoch/counters. Default off changes no prior behavior. */
    m->bemf_stress_last_switch_ns = -1;
    m->bemf_stress_switch_edges = m->bemf_stress_trace_count = 0U;
    m->first_ost3_seen = false;
    m->first_ost3_count = m->oc_publications = 0U;
    m->first_ost3_ns = 0;
    m->first_ost3_cpu_pc = m->first_ost3_primask = m->first_ost3_ipsr = 0U;
    m->first_ost3_oc_valid = m->first_ost3_ready = m->first_ost3_trip = 0U;
    m->first_ost3_xbar = m->first_ost3_tzsel = m->first_ost3_prior = 0U;
    m->first_ost3_mux = m->first_ost3_invert = 0U;
    memset(m->first_ost3_oc, 0, sizeof(m->first_ost3_oc));
    memset(m->first_ost3_dac, 0, sizeof(m->first_ost3_dac));
    m->last_ns = 0;
    memset(m->currents, 0, sizeof(m->currents));
    memset(m->bemf_codes, 0, sizeof(m->bemf_codes));
    m->theta = (m->initial_phase_override ?
        (double)m->initial_phase_mdeg / 1000.0 : -30.0) *
        AM13E_NATIVE_PI / 180.0;
    m->omega = 0.0;
    m->last_torque = 0.0;
    m->theta_unwrapped = m->theta;
    m->energy_bus_j = m->energy_copper_j = m->energy_diode_j = 0.0;
    m->energy_bemf_j = m->energy_magnetic_j = 0.0;
    m->energy_backward_euler_j = 0.0;
    m->energy_abs_residual_j = m->energy_max_residual_j = 0.0;
    m->energy_max_star_sum_a = 0.0;
    m->energy_steps = m->energy_diode_steps = 0U;
    m->p0_last_pair = UINT32_MAX;
    m->p0_first_switch_ns = -1;
    m->p0_last_logged_mask = UINT32_MAX;
    m->p0_last_logged_gate = false;
    /* Reset source log counters, not the explicitly configured machine
     * observation window; never touch physical state/solver/Guest. */
    m->source_focus_record_count = 0U;
    m->source_focus_last_logged_mask = UINT32_MAX;
    m->source_focus_last_logged_gate = false;
    m->source_focus_budget_hit = false;
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

#include "am13e_native_motor_dynamics.inc"
#include "am13e_native_analog_frontend.inc"
#include "am13e_native_pwm_coupling.inc"
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
    if(m->ticks % 1000U == 0U) {
        am13e_p0_event(m->machine,"ROTOR",
                       (int64_t)llround(m->omega*60.0/
                                           (2.0*AM13E_NATIVE_PI)*1000.0),
                       (int64_t)llround(m->theta_unwrapped*1000.0),
                       (int64_t)llround(m->currents[0]*1000.0),
                       (int64_t)llround(m->currents[1]*1000.0),
                       (int64_t)llround(m->currents[2]*1000.0),
                       (int64_t)llround(m->last_torque*1000000.0));
        am13e_p0_event(m->machine,"ENERGY",
                       (int64_t)llround(m->energy_bus_j*1e9),
                       (int64_t)llround(m->energy_diode_j*1e9),
                       (int64_t)llround(m->energy_copper_j*1e9),
                       (int64_t)llround(m->energy_bemf_j*1e9),
                       (int64_t)llround(m->energy_magnetic_j*1e9),
                       (int64_t)llround(m->energy_backward_euler_j*1e9));
        am13e_p0_event(m->machine,"INVARIANT",m->energy_steps,
                       m->energy_diode_steps,
                       (int64_t)llround(m->energy_abs_residual_j*1e12),
                       (int64_t)llround(m->energy_max_residual_j*1e12),
                       (int64_t)llround(m->energy_max_star_sum_a*1e6),0);
        /* P1 frontend source-only monitor. Phase voltage ADC codes
         * originate from the native rotor BEMF, not a host fixture.
         * OC is independent current-sense hardware path.
         * Fields: three BEMF 12-bit codes, selected phase,
         * selected 12-bit DAC threshold, cmp filter output.
         */
        unsigned selected=m->machine->sim_mc_mux[0]&7U;
        AM13ESimFeedback *fb=&m->machine->feedback;
        am13e_p0_event(m->machine,"BEMF_FRONTEND",
                       m->bemf_codes[0],m->bemf_codes[1],
                       m->bemf_codes[2],selected,
                       fb->cmp[0x0eU/2U]&0xfffU,
                       fb->filtered);
        /* Source native physical OC before any interposing Host MMIO:
         * code12+VALID16 on each of three actual modeled comparators.
         */
        AM13ETrip *trip=&m->machine->trip;
        uint32_t valid=0,ready=0,above=0;
        for(unsigned i=0;i<3U;++i) {
            if(trip->oc_valid[i]) valid|=(1U<<i);
            if(am13e_g13b2_cmp_ready(m->machine,i)) ready|=(1U<<i);
            if(am13e_g13b2_cmp_trip(m->machine,i)) above|=(1U<<i);
        }
        am13e_p0_event(m->machine,"OC_FRONTEND",
                       trip->oc_input[0],trip->oc_input[1],
                       trip->oc_input[2],valid,ready,above);
    }
    am13e_native_motor_publish(m);
    if (!m->faulted) {
        am13e_native_motor_publish_oc(m);
    }
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
    case 0x38: *v=m->oc_publications; break;
    case 0x3c: *v=m->first_ost3_count; break;
    case 0x40: *v=m->first_ost3_cpu_pc; break;
    case 0x44: *v=(uint32_t)m->first_ost3_ns; break;
    case 0x48: *v=(uint64_t)m->first_ost3_ns>>32U; break;
    case 0x4c: *v=m->first_ost3_oc_valid; break;
    case 0x50: *v=m->first_ost3_ready; break;
    case 0x54: *v=m->first_ost3_trip; break;
    case 0x58: *v=m->first_ost3_xbar; break;
    case 0x5c: *v=m->first_ost3_tzsel; break;
    case 0x60: *v=m->first_ost3_oc[0]; break;
    case 0x64: *v=m->first_ost3_oc[1]; break;
    case 0x68: *v=m->first_ost3_oc[2]; break;
    case 0x6c: *v=m->first_ost3_dac[0]; break;
    case 0x70: *v=m->first_ost3_dac[1]; break;
    case 0x74: *v=m->first_ost3_dac[2]; break;
    case 0x78: *v=m->first_ost3_mux; break;
    case 0x7c: *v=m->first_ost3_primask; break;
    case 0x80: *v=m->first_ost3_ipsr; break;
    case 0x84: *v=m->first_ost3_prior; break;
    case 0x88: *v=m->first_ost3_invert; break;
    /* Non-silicon read-only effective plant, never guest-authored:
     * Kv rpm/V; phase R micro-ohm; phase L nH; terminal Kt micro-Nm/A;
     * virtual DC bus mV. Preserve all prior QTest offsets. */
    case 0x8c: *v=m->model_profile == 210U ? 210U : 147U; break;
    case 0x90: *v=(uint32_t)llround(AM13E_NATIVE_R*1e6); break;
    case 0x94: *v=(uint32_t)llround(AM13E_NATIVE_L*1e9); break;
    case 0x98: *v=(uint32_t)llround(AM13E_NATIVE_KT_TERMINAL*1e6); break;
    case 0x9c: *v=(uint32_t)llround(AM13E_NATIVE_VBUS*1e3); break;
    /* Configured initial electrical angle, signed millidegrees.
     * Read-only provenance; NOT instantaneous theta or a rotor sensor. */
    case 0xa0: *v=(uint32_t)(m->initial_phase_override ?
                             m->initial_phase_mdeg : -30000); break;
    case 0xa4: *v=m->machine->esc_sim_native_adc_bemf ? 1U : 0U; break;
    case 0xa8: *v=m->phase_adc_publications[0]; break;
    case 0xac: *v=m->phase_adc_publications[1]; break;
    case 0xb0: *v=m->phase_adc_publications[2]; break;
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
