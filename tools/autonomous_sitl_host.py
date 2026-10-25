"""Backward compatible public facade for autonomous simulator tools.

Implementation moved to single-purpose modules; historical imports
remain stable for original G13B4 test runner and existing CI scripts.
"""
from tools.sitl_autonomous_transport import (
    AUTO_BASE, AUTO_MAGIC, AUTO_ABI, AUTO_RUNNING, AUTO_DONE,
    AUTO_ERROR, FRAME_NS, REG, compile_autonomous_stages,
    read_auto, configure_auto, native_end_oracle, read_stage_checkpoints,
)
from tools.sitl_autonomous_evidence import (
    summarize_stage_samples, read_timing_evidence,
)
from tools.sitl_stage_oracle import sampled_stage_regression_gate
