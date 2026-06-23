"""Apply LoRA to SAM via PEFT.

This module provides a minimal adapter application targeting attention
projection layers in the image encoder and optionally the mask decoder.
"""

from __future__ import annotations

from typing import List, Optional

from peft import LoraConfig, TaskType, get_peft_model

def apply_lora_to_sam(sam_model, rank: int = 8, alpha: int = 16, target_modules: Optional[List[str]] = None):
    """Wraps a SAM model with PEFT LoRA.

    target_modules should contain substrings to match modules, e.g. ["q_proj","k_proj","v_proj","o_proj"].
    """
    if target_modules is None:
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj"]
    config = LoraConfig(
        r=rank,
        lora_alpha=alpha,
        target_modules=target_modules,
        lora_dropout=0.0,
        bias="none",
        task_type=TaskType.FEATURE_EXTRACTION,
    )
    peft_model = get_peft_model(sam_model, config)
    return peft_model


