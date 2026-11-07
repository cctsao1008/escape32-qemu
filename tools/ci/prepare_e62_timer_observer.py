#!/usr/bin/env python3
"""Pinned read-only callback context: never changes timer ordering/deadlines."""
import argparse
from pathlib import Path
import subprocess
PIN='44f28df24767cf9dca1ddc9b23157737c4cbb645'
CONTEXT='''/* E62 diagnostic context only: thread-local and nested-callback safe. */
typedef struct E62TimerContext {
    QEMUTimer *timer;
    int64_t deadline, snapshot;
} E62TimerContext;
static __thread E62TimerContext e62_timer_context;
bool e62_timer_observation(QEMUTimer *timer, int64_t *deadline, int64_t *snapshot)
{
    if (e62_timer_context.timer != timer) return false;
    *deadline = e62_timer_context.deadline;
    *snapshot = e62_timer_context.snapshot;
    return true;
}

'''
BEFORE='''        /* remove timer from the list before calling the callback */'''
AFTER='''        E62TimerContext e62_previous = e62_timer_context;
        e62_timer_context = (E62TimerContext){ts, ts->expire_time, current_time};
        /* remove timer from the list before calling the callback */'''
CALL='''        cb(opaque);
        qemu_mutex_lock(&timer_list->active_timers_lock);'''
CALL_NEW='''        cb(opaque);
        e62_timer_context = e62_previous;
        qemu_mutex_lock(&timer_list->active_timers_lock);'''
def patch(text):
    if CONTEXT in text:
        if AFTER not in text or CALL_NEW not in text:raise ValueError('Partial timer observer patch')
        return text
    for a in ('typedef struct QEMUClock {',BEFORE,CALL):
        if text.count(a)!=1:raise ValueError('Pinned timer observer anchor changed')
    return text.replace('typedef struct QEMUClock {',CONTEXT+'typedef struct QEMUClock {',1).replace(BEFORE,AFTER,1).replace(CALL,CALL_NEW,1)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);a=p.parse_args()
    if subprocess.check_output(['git','-C',str(a.source),'rev-parse','HEAD'],text=True).strip()!=PIN:raise SystemExit('QEMU pin mismatch')
    path=a.source/'util/qemu-timer.c';s=path.read_text();v=patch(s)
    if v!=s:path.write_text(v)
if __name__=='__main__':main()
