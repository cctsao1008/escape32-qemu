Optional pinned-source QTest transport correction unblocks pre-start debug reads in RR mode. Await QMP quit acknowledgement and reject unfinalized runs. Add a read-only comparison of complete indexed source events with absolute timestamps, independently of final host polling.

Validation: 10 focused tests pass. Finalized record/replay logs match74,596 events/4820frames exactly. Replay host final-poll failure is retained, not converted into motor PASS.

Related to cctsao1008/escape32-qemu issues #10, #4, #3, #5, #6 and #8 as applicable. Draft for review; do not merge or close issues automatically.
