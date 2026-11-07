"""Export source sample figures; connecting lines are not additional measurements."""
import argparse,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--seed',type=Path);p.add_argument('--output-prefix',type=Path,required=True);a=p.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,figsize=(10,8),sharex=True)
    for name,path,color in [('Baseline',a.baseline,'#365f9d'),('Acceptance only',a.candidate,'#c45a29'),('Interval seed',a.seed,'#36915e')]:
        if path is None:continue
        d=json.loads(path.read_text())['demands'][0];t=d['source_demand']['vns'];rows=[s for s in d['samples'] if s['after_demand_ns']<=25_000_000];x=[s['after_demand_ns']/1e6 for s in rows]
        for ax,key in zip(axes,('electrical_angle_deg','torque_nm','rpm')):ax.plot(x,[s[key] for s in rows],'.-',ms=4,lw=.8,color=color,label=name)
        accepted=d['first_accepted_capture_with_timer_chain'];changed=d['first_changed_pair']
        for ax in axes:
            if accepted:ax.axvline((accepted['cap1_ns']-t)/1e6,color=color,ls='--',lw=.7,alpha=.7)
            if changed:ax.axvline((changed['source']['vns']-t)/1e6,color=color,ls=':',lw=.9,alpha=.7)
    for ax in axes:ax.grid(alpha=.2);ax.axhline(0,color='gray',lw=.6)
    axes[0].set_ylabel('Electrical angle (deg, unwrapped)');axes[1].set_ylabel('Torque (Nm)');axes[2].set_ylabel('Signed RPM');axes[2].set_xlabel('ms after actual source DShot demand');axes[0].legend(loc='upper left')
    fig.suptitle('Matched -30 degree reset-pose startup: source rotor samples (SIM_ONLY)')
    fig.text(.5,.015,'Dots: actual 1ms samples. Lines connect samples only. Dashed: accepted capture + timer chain. Dotted: physical pair change.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.035,1,.96));a.output_prefix.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('svg','png'):fig.savefig(a.output_prefix.with_suffix('.'+ext),dpi=160)
if __name__=='__main__':main()
