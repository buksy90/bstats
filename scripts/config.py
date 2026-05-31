import sys
import os
import json
import numpy as np
import cv2

# =====================================================================
# 🛑 ULTRALYTICS AUTO-UPDATE BYPASS PATCH (Forces AMD GPU Execution)
# =====================================================================
import ultralytics.utils.checks
_original_check = ultralytics.utils.checks.check_requirements
def _patched_check(requirements, *args, **kwargs):
    """Intercepts package sweeps and blocks Ultralytics from replacing DirectML."""
    if 'onnxruntime' in str(requirements):
        return True
    return _original_check(requirements, *args, **kwargs)
ultralytics.utils.checks.check_requirements = _patched_check
# =====================================================================

# =====================================================================
# 🔥 AMD DIRECTML ACCELERATION HOOK INJECTION
# =====================================================================
import onnxruntime as ort
_original_init = ort.InferenceSession.__init__
def _patched_init(self, *args, **kwargs):
    kwargs['providers'] = ['DmlExecutionProvider', 'CPUExecutionProvider']
    _original_init(self, *args, **kwargs)
ort.InferenceSession.__init__ = _patched_init
# =====================================================================

# =====================================================================
# ⚙️ GLOBAL ENGINE CONFIGURATIONS
# =====================================================================
RENDER_EVERY_N_SECONDS = 2.0
START_MINUTE = 0.0
DURATION_MINUTES = 2.0       # Set to None for full match processing

# Multi-Factor Auto-Merger Thresholds
AUTO_MERGE_MAX_SECONDS = 4.0
AUTO_MERGE_MAX_METERS = 3.0
COLOR_SIMILARITY_THRESHOLD = 0.65

# Basketball Game Heuristics
POSSESSION_DISTANCE_THRESHOLD_METERS = 1.4
SUB_TIMEOUT_SECONDS = 4.0                    # Multi-second smoothing buffer window
# =====================================================================

# Parse terminal arguments
if len(sys.argv) < 2:
    print("Error: Missing video filename parameter.")
    sys.exit(1)

VIDEO_FILENAME = sys.argv[1]
VIDEO_BASE_NAME, _ = os.path.splitext(VIDEO_FILENAME)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")

VIDEO_PATH = os.path.join(VIDEOS_DIR, VIDEO_FILENAME)
CALIBRATION_PATH = os.path.join(VIDEOS_DIR, "calibration.json")
OUTPUT_LOG_PATH = os.path.join(VIDEOS_DIR, f"{VIDEO_BASE_NAME}_tracking.json")

if not os.path.exists(VIDEO_PATH) or not os.path.exists(CALIBRATION_PATH):
    print(f"Error: Missing asset path configurations:\n-> {VIDEO_PATH}\n-> {CALIBRATION_PATH}")
    sys.exit(1)

# Load Calibration Profile Meta Fields
with open(CALIBRATION_PATH, 'r') as f:
    CALIBRATION = json.load(f)

# =====================================================================
# 📐 FAULT-TOLERANT HOMOGRAPHY & TRANSFORM ENGINE
# =====================================================================
HAS_HOMOGRAPHY = False
HOMOGRAPHY_MATRIX = None

# Verify if court corners exist before initializing matrix operations
if 'court_corners' in CALIBRATION and len(CALIBRATION['court_corners']) >= 4:
    try:
        SRC_CORNERS = np.float32([
            [CALIBRATION['court_corners'][0]['x'], CALIBRATION['court_corners'][0]['y']],
            [CALIBRATION['court_corners'][1]['x'], CALIBRATION['court_corners'][1]['y']],
            [CALIBRATION['court_corners'][2]['x'], CALIBRATION['court_corners'][2]['y']],
            [CALIBRATION['court_corners'][3]['x'], CALIBRATION['court_corners'][3]['y']]
        ])
        DST_CORNERS = np.float32([[0, 0], [280, 0], [280, 150], [0, 150]])
        HOMOGRAPHY_MATRIX = cv2.getPerspectiveTransform(SRC_CORNERS, DST_CORNERS)
        HAS_HOMOGRAPHY = True
    except Exception as e:
        print(f"[Config Engine] Warning: Failed to parse perspective fields: {e}")
else:
    print("[Config Engine] Notice: Missing or incomplete 'court_corners'. Bypassing 2D transformation matrix loops.")

def get_court_meters(pixel_x, pixel_y):
    """Translates generic camera frame pixels into flat 2D bird's eye court meters."""
    if not HAS_HOMOGRAPHY:
        # Fallback approximation mapping space directly using linear pixel division bounds
        return float(pixel_x) / 50.0, float(pixel_y) / 50.0

    pt = np.array([[[pixel_x, pixel_y]]], dtype=np.float32)
    transformed = cv2.perspectiveTransform(pt, HOMOGRAPHY_MATRIX)
    return transformed[0][0][0] / 10.0, transformed[0][0][1] / 10.0

def is_point_in_box(mx, my, box_dict):
    """Checks if a transformed 2D coordinate falls inside a pixel bounding box mapping."""
    if not box_dict:
        return False
    # Translate box to bird's eye space boundary approximations
    bx_m, by_m = get_court_meters(box_dict['x'], box_dict['y'])
    bw_m, bh_m = box_dict['w'] / 50.0, box_dict['h'] / 50.0 # Approximate scaling divisor
    return (bx_m <= mx <= bx_m + bw_m) and (by_m <= my <= by_m + bh_m)

def is_inside_court_boundaries(mx, my):
    """Verifies if the player ground contact position rests inside live borders."""
    return (0 <= mx <= 28.0) and (0 <= my <= 15.0)

def extract_color_profile(img_crop):
    """Splits player crops into regions to generate HSV shirt and shorts signatures."""
    if img_crop.size == 0:
        return None
    hsv = cv2.cvtColor(img_crop, cv2.COLOR_BGR2HSV)
    h, w, _ = hsv.shape
    shirt_zone = hsv[0:int(h*0.4), :]
    shorts_zone = hsv[int(h*0.6):h, :]

    def get_hist(zone):
        if zone.size == 0:
            return None
        hist = cv2.calcHist([zone], [0, 1], None, [8, 8], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        return hist.flatten()

    return {"shirt": get_hist(shirt_zone), "shorts": get_hist(shorts_zone)}