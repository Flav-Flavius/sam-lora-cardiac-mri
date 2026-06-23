"""SAM + LoRA (ACDC) package.

Modules:
- data: lightweight dataset utilities for ACDC-like 2D slices
- preprocess: normalization, resampling, label remapping
- prompts: point/box/grid prompt generators and jitter
- metrics: Dice, HD95, Boundary F, LV mass error
- visualize: PNG panels for quick QA
- sam_wrapper: thin wrapper to load SAM and run mask decoder
- lora: PEFT-based LoRA adapters and application to SAM
"""

__all__ = [
    "data",
    "preprocess",
    "prompts",
    "metrics",
    "visualize",
    "sam_wrapper",
    "lora",
]

