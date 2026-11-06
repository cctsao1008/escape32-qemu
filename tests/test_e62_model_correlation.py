"""Synthetic UNIT fixtures, explicitly not bench measurements."""
import copy
import unittest
from tools.e62_model_correlation import correlate


def fixture():
    a=dict(origin='PHYSICAL_BENCH',sensor_calibration='UNIT',fixture_identity='UNIT',
           motor_id='UNIT',propeller_id='UNIT',clock_synchronization='UNIT',
           uncertainty={'rpm':5,'voltage_v':.1,'current_a':.2},
           samples=[dict(t_ns=t,rpm=100,voltage_v=24,current_a=2) for t in (0,1000000)])
    b=dict(origin='SIM_ONLY',effective_parameters={'classification':'UNIT'},samples=copy.deepcopy(a['samples']))
    return a,b


class CorrelationTests(unittest.TestCase):
    def test_error_band_is_not_hardware_or_model_approval(self):
        a,b=fixture();b['samples'][1]['rpm']=110
        r=correlate(a,b)
        self.assertEqual(r['error_bands']['rpm']['outside_measurement_uncertainty'],1)
        self.assertAlmostEqual(r['error_bands']['rpm']['rmse'],50**.5)
        self.assertFalse(r['model_calibrated']);self.assertFalse(r['hardware_qualified'])

    def test_rejects_unmatched_timestamps_missing_samples_and_nonfinite(self):
        for kind in ('time','sample','nan','origin','uncertainty','calibration'):
            with self.subTest(kind=kind):
                a,b=fixture()
                if kind=='time':b['samples'][1]['t_ns']+=1
                if kind=='sample':b['samples'].pop()
                if kind=='nan':b['samples'][0]['rpm']=float('nan')
                if kind=='origin':a['origin']='SIM_ONLY'
                if kind=='uncertainty':a['uncertainty']['rpm']=0
                if kind=='calibration':a['sensor_calibration']=''
                with self.assertRaises(ValueError):correlate(a,b)


if __name__=='__main__':unittest.main()
