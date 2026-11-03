/*
 * G13B2 virtual-board analog calibration contract.
 *
 * This file describes the external board transfer functions presented to
 * the unmodified AM13E runtime-calibration path. It is QEMU test-fixture
 * data, NOT Quanta E62 electrical design data and not a firmware
 * simulation-mode switch.
 *
 * Virtual board model:
 *   ADC reference/span: 3.3 V, ideal gain/offset
 *   VBUS sense:         ADC pin = VBUS / 20
 *   BEMF neutral:       phase sense = (33/470) * VBUS/2
 *   CMPSS DAC:          VDDA = 3.3 V, ideal gain/offset
 *   reference validity: 64 ms (1024 x 16 kHz ticks)
 *
 * The virtual DC bus is constant over a run. Reference validity therefore
 * exceeds the Rel17 32.768 ms BEMF timeout: loss of a zero crossing must be
 * decided by the motor-control timeout, not by an unrelated 2 ms synthetic
 * host-test freshness value.
 *
 * QEMU must present matching external ADC voltages. The Guest derives the
 * CMPSS DACH reference through the normal AM13E ADC/reference lifecycle.
 */
#pragma once

#define AM13E_BOARD_ADC_REFERENCE_MODE DL_SYSCTL_VREF_INTERNAL_3_3_V
#define AM13E_BOARD_ADC_PACKAGE_QFN48 0

#define AM13E_BOARD_SC5_CALIBRATION { \
    .adc_span_uv=3300000U, .adc_gain_ppm=1000000U, \
    .bus_num=1U, .bus_den=20U, \
    .phase_num={33U,33U,33U}, .phase_den={470U,470U,470U}, \
    .vdda_uv=3300000U, .dac_gain_ppm=1000000U, \
    .bus_min_uv=10000000U, .bus_max_uv=80000000U, \
    .max_age_ticks=1024U \
}
