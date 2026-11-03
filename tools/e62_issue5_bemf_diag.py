"""Read-only E62 #5 Firmware BEMF decision ring decoder.

Firmware am13e-port-v2 exports am13e_bemf_diag_seq and
am13e_bemf_diag_ring. Access through a halted Guest RSP with ELF-resolved
symbol addresses; never modify SRAM or force a CAP1/IRQ. Ring has 64 entries
of 6 little-endian 32-bit words. Do not infer wall-clock time from tick.
"""
DEPTH = 64
WORDS_PER_ENTRY = 6
DECISIONS = {1: "ACCEPTED", 2: "REJECTED_EARLY", 3: "TIMEOUT"}


def signed(v):
    return v - (1 << 32) if v & 0x80000000 else v


def decode_entry(words, sequence):
    if len(words) != WORDS_PER_ENTRY:
        raise ValueError("incomplete diagnostic entry")
    tick, capture, ival, delay, sync, decision = words
    if decision not in DECISIONS:
        raise ValueError("invalid diagnostic decision")
    return {
        "seq": sequence,
        "tick": tick,
        "capture_us": signed(capture),
        "ival_before": signed(ival),
        "delay_us": signed(delay),
        "sync_before": sync,
        "decision": DECISIONS[decision],
        "original_early_threshold_us": signed(ival) >> 1,
    }


def snapshot(read32, seq_address, ring_address, limit=64):
    if not 1 <= limit <= DEPTH:
        raise ValueError("invalid ring limit")
    before = read32(seq_address)
    start = max(0, before - min(before, limit))
    out = []
    for seq in range(start, before):
        addr = ring_address + (seq % DEPTH) * WORDS_PER_ENTRY * 4
        out.append(decode_entry(
            [read32(addr + 4 * i) for i in range(WORDS_PER_ENTRY)], seq))
    after = read32(seq_address)
    if after != before:
        raise RuntimeError("BEMF diagnostic ring changed during read")
    return {"seq_after": before, "overwritten": before > DEPTH,
            "entries": out}

def snapshot_first(read32, seq_address, first_address):
    """Read immutable first 64 callbacks even after rolling history wraps.

    Must be sampled with the Guest halted; seq read-back prevents
    concurrent writes. A count over 64 is reported, never treated as
    complete startup history.
    """
    before = read32(seq_address)
    count = min(before, DEPTH)
    entries = []
    for seq in range(count):
        addr = first_address + seq * WORDS_PER_ENTRY * 4
        entries.append(decode_entry(
            [read32(addr + 4 * i) for i in range(WORDS_PER_ENTRY)], seq))
    after = read32(seq_address)
    if after != before:
        raise RuntimeError("BEMF first-history changed during read")
    return {"seq_after": before, "first_history_capped": before > DEPTH,
            "entries": entries}
