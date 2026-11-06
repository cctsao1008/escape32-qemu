"""Synthetic unit inputs only, never simulated or physical qualification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from tools.e62_uploaded_trace_inventory import records,observe,pair,family,audit,PRODUCTION,ORIGINAL
from tools.native_p1_qualification import dshot_value

class UploadedTraceTests(unittest.TestCase):
    def fixture(self):
        rows=[{'seq':1,'vns':100,'kind':'DSHOT','data':[0,0,0,0,0,0]},
              {'seq':2,'vns':500000,'kind':'ROTOR','data':[-72322,-1500,100,-200,100,-1234]},
              {'seq':3,'vns':1000100,'kind':'DSHOT','data':[1,1,dshot_value(200),0,0,0]}]
        e={'candidate_elf_sha256':PRODUCTION,'original_elf_sha256':PRODUCTION,'p0_source_event_count':3,'configured_dshot_frames':2,'host_guest_register_writes':False,'synthetic_timed_bemf_enabled':False,'used_guest_wfi_or_gdb':False,'autonomous_dshot':{'sent':2},'native_dshot_scenario':{'frame_period_ns':1000000,'guest_ready_gating':False,'stages':[[1,0,0,1],[1,200,200,1]],'sha256':'a'*64}}
        return rows,e
    def test_partial_metadata_never_proves_binary_or_cfg_or_lifecycle(self):
        rows,e=self.fixture();r=observe(rows,e)
        self.assertEqual(r['declared_firmware_class'],'production_root_fixes')
        self.assertFalse(r['elf_bytes_verified']);self.assertFalse(r['cfg_available']);self.assertFalse(r['p1_qualified'])
        b=r['boundaries'][1];self.assertEqual(b['rotor_before']['rpm'],-72.322)
        self.assertEqual(b['vns'],1000100);self.assertEqual(b['rotor_age_ns'],500100)
        self.assertIsNone(b['gate_active']);self.assertEqual(b['switch_status'],'INCOMPLETE')
    def test_wrong_declared_command_or_count_rejected(self):
        rows,e=self.fixture();rows[-1]['data'][2]-=1
        with self.assertRaises(ValueError):observe(rows,e)
        rows,e=self.fixture();e['configured_dshot_frames']=3
        with self.assertRaises(ValueError):observe(rows,e)
    def test_production_original_and_experimental_are_distinct(self):
        _,e=self.fixture();self.assertEqual(family(e),'production_root_fixes')
        e.update(candidate_elf_sha256=ORIGINAL,original_elf_sha256=ORIGINAL);self.assertEqual(family(e),'original_rel17_3')
        e['original_elf_sha256']=PRODUCTION
        with self.assertRaises(ValueError):family(e)
    def test_same_reported_settings_never_prove_matched_provenance(self):
        rows,e=self.fixture();other=copy.deepcopy(rows);other[1]['vns']+=4
        r=pair(rows,other,e,e);self.assertTrue(r['same_reported_settings']);self.assertFalse(r['matched_provenance_verified']);self.assertEqual(r['a']['vns'],500000)
    def test_complete_partial_archive_pair_replay(self):
        rows,e=self.fixture()
        raw=''.join('E62_P0_EVENT seq={seq} vns={vns} kind={kind} '.format(**r)+' '.join(k+'='+str(v) for k,v in zip('abcdef',r['data']))+'\n' for r in rows)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);e['qemu_log_bytes']=len(raw.encode())
            for name in ('unit-repeat01','unit-repeat02'):
                prefix=root/name
                prefix.with_suffix('.json').write_text(json.dumps(e))
                prefix.with_suffix('.p0.events.log').write_text(raw)
                prefix.with_suffix('.qemu.log').write_text(raw)
                prefix.with_suffix('.stdout.log').write_text('E62_NATIVE_AUTONOMOUS_NO_WFI_PROBE '+json.dumps(e)+'\n')
            r=audit(root,root/'out')
            self.assertEqual(r['errors'],[]);self.assertEqual(len(r['cases']),2)
            self.assertEqual(len(r['comparisons']),1)
            self.assertEqual(r['status'],'INCOMPLETE_PROVENANCE')
            self.assertFalse(r['comparisons'][0]['matched_provenance_verified'])
    def test_injection_or_missing_observer_contract_rejected(self):
        rows,e=self.fixture();e['host_guest_register_writes']=True
        with self.assertRaises(ValueError):observe(rows,e)
    def test_large_archived_stream_does_not_change_strict_budget(self):
        from tools.e62_acquisition_timeline import read_events
        from tools.native_p0_strict import TraceError
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'large'
            with p.open('w') as f:
                for i in range(1,200002):f.write(f'E62_P0_EVENT seq={i} vns={i} kind=ROTOR a=0 b=0 c=0 d=0 e=0 f=0\n')
            self.assertEqual(sum(1 for _ in records(p)),200001)
            with self.assertRaises(TraceError):read_events(p.read_text().splitlines())
    def test_sequence_gap_unknown_kind_or_backward_time_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'events'
            for text in ('E62_P0_EVENT seq=2 vns=100 kind=DSHOT a=0 b=0 c=0 d=0 e=0 f=0\n','E62_P0_EVENT seq=1 vns=100 kind=MADE_UP a=0 b=0 c=0 d=0 e=0 f=0\n','E62_P0_EVENT broken\n'):
                p.write_text(text)
                with self.assertRaises(ValueError):list(records(p))

if __name__=='__main__':unittest.main()
