# This module extracts an empty court background completely automatically without user assistance
# by collecting frames evenly across the timeline and processing a mathematical median filter
# to eliminate moving bodies.

import cv2
import numpy as np
import random
from config import VIDEO_PATH

def generate_static_background(start_frame, end_frame, num_samples=30):
    """Builds a pristine background image of the court via Temporal Median Filtering."""
    print(f"[Background Core] Generating static environment reference using {num_samples} frames...")
    cap = cv2.VideoCapture(VIDEO_PATH)

    # Calculate sampling distribution array indices
    sample_indices = np.linspace(start_frame, end_frame - 5, num_samples, dtype=int)
    frames_pool = []

    for idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if ret:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frames_pool.append(gray)

    cap.release()

    if not frames_pool:
        raise ValueError("Failed to extract valid background sequence samples.")

    # Stack frames along depth axis and calculate the median pixel value
    median_frame = np.median(frames_pool, axis=0).astype(dtype=np.uint8)
    print("[Background Core] Pristine background modeling completed successfully.")
    return median_frame