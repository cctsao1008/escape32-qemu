/* SIM_ONLY APC 24x12E fixed-airflow=0 mph analytical data.
 * Exact maker source: https://www.apcprop.com/files/PER3_24x12E.dat
 * v2022-0915, simulation date 2022-09-22; static Torque N*m.
 * These are calculated aerodynamic points, NOT measured E62 hardware.
 * Propeller/hub inertia is unknown: source-machine J1/J2/J5 sensitivity.
 * Only -machine ecx87-kv210-apc24x12e-47v-j1/j2/j5 enables this.
 * Historical 24V motor-only source and firmware are byte-for-byte unchanged.
 */
static double am13e_native_apc_prop_torque(double omega)
{
    static const double rpm_points[6] = {1000.,2000.,3000.,4000.,5000.,6000.};
    static const double tq_points[6] = {0.132,0.494,1.085,1.913,2.996,4.362};
    double rpm = fabs(omega)*60.0/(2.0*AM13E_NATIVE_PI);
    if (!isfinite(rpm) || rpm>6000.0+1e-8) {
        return NAN; /* Domain limit: maxon EC87 published 6000rpm. */
    }
    rpm=MIN(rpm,6000.0); /* Floating-point epsilon at the documented cap. */
    if (rpm<=rpm_points[0]) {
        double s=rpm/rpm_points[0];
        return copysign(tq_points[0]*s*s,omega);
    }
    for (unsigned i=1; i<6U; ++i) {
        if (rpm<=rpm_points[i]) {
            double f=(rpm-rpm_points[i-1])/
                     (rpm_points[i]-rpm_points[i-1]);
            double tq=tq_points[i-1]+f*(tq_points[i]-tq_points[i-1]);
            return copysign(tq,omega);
        }
    }
    return NAN;
}
