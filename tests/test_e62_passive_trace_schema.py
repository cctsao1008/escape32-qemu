"""Source schema regression: observation admission is not qualification."""
import unittest
from tools.native_p0_strict import parse_events,TraceError


def event(seq,kind):
    return f'E62_P0_EVENT seq={seq} vns={seq} kind={kind} a=1 b=1490 c=12 d=1 e=24000 f=0'


class PassiveSchemaTests(unittest.TestCase):
    def test_first_party_adc_and_clock_records_remain_lossless(self):
        kinds=('ADC_PHASE_EOC','ADC_PHASE_READ','ADC_VBUS_EOC','PWM_TBCTL','PWM_AUDIO_PERIOD')
        e=parse_events([event(i+1,k) for i,k in enumerate(kinds)])
        self.assertEqual([r['kind'] for r in e],list(kinds))
        self.assertEqual(e[2]['data'],(1,1490,12,1,24000,0))

    def test_unknown_malformed_and_gapped_records_still_fail(self):
        for rows in ([event(1,'SYNTHETIC_CAP1')],[event(1,'ADC_PHASE_EOC'),event(3,'ADC_PHASE_READ')],['E62_P0_EVENT invalid']):
            with self.assertRaises(TraceError):parse_events(rows)


if __name__=='__main__':unittest.main()
