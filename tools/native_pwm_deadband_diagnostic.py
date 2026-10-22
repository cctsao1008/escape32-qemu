"""Read-only deadband predicate based on original Rel17 AM13E HAL."""
from dataclasses import dataclass,asdict

@dataclass(frozen=True)
class SourceClamp:
    red_ticks: int
    fed_ticks: int
    min_compare_ticks: int
    source_phases: tuple
    source_compares: tuple
    all_source_pwm_clamped: bool
    source_active_pwm_present: bool
    reason: str
    def to_dict(self):
        return asdict(self)

def native_deadband_source_clamp(logical_aq,logical_compare,aq_active,*,red_ticks,fed_ticks,fed_enabled):
    if any(len(x)!=6 for x in (logical_aq,logical_compare,aq_active)):
        raise ValueError('Six original AQ/Compare values required')
    if not 0<=red_ticks<=0x3fff or not 0<=fed_ticks<=0x3fff or red_ticks<(fed_ticks if fed_enabled else 0):
        raise ValueError('Invalid native hardware deadband ticks')
    if any(not 0<=v<=0xffff for a in (logical_aq,logical_compare,aq_active) for v in a):
        raise ValueError('Only original 16-bit AQ/compare values qualify')
    floor=red_ticks-(fed_ticks if fed_enabled else 0)
    src=tuple(i for i in range(3) if logical_aq[2*i]==0x12)
    compares=tuple(logical_compare[2*i] for i in src)
    clamped=bool(src) and all(c<=floor for c in compares)
    active=any(aq_active[2*i]==0x12 for i in range(3))
    reason=('ORIGINAL_SOURCE_PWM_CLAMPED_BELOW_DEADBAND' if clamped and not active else
            'AT_LEAST_ONE_SOURCE_ABOVE_DEADBAND' if any(c>floor for c in compares) else
            'NO_PHYSICAL_HIGH_SIDE_SOURCE_PROVED')
    return SourceClamp(red_ticks,fed_ticks if fed_enabled else 0,floor,src,compares,clamped,active,reason)
