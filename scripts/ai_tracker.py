import sys
import os
import cv2
import numpy as np
import json
from tqdm import tqdm

# =====================================================================
# ⚙️ CONFIGURATION BLOCK
# =====================================================================
RENDER_EVERY_N_SECONDS = 0.5
MAX_TEST_MINUTES = 1.0       # Set to None for full video processing
AUTO_MERGE_MAX_SECONDS = 2.5 # Max time gap to allow auto-merging players
AUTO_MERGE_MAX_METERS = 2.0  # Max distance gap to allow auto-merging players
# =====================================================================

import onnxruntime as ort
_original_InferenceSession_init = ort.InferenceSession.__init__
def _patched_InferenceSession_init(self, *args, **kwargs):
    kwargs['providers'] = ['DmlExecutionProvider', 'CPUExecutionProvider']
    _original_InferenceSession_init(self, *args, **kwargs)
ort.InferenceSession.__init__ = _patched_InferenceSession_init

from ultralytics import YOLO

if len(sys.argv) < 2:
    print("Error: Missing video filename.")
    sys.exit(1)

video_filename = sys.argv[1]
video_base_name, _ = os.path.splitext(video_filename)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")
VIDEO_PATH = os.path.join(VIDEOS_DIR, video_filename)
CALIBRATION_PATH = os.path.join(VIDEOS_DIR, "calibration.json")
OUTPUT_LOG_PATH = os.path.join(VIDEOS_DIR, f"{video_base_name}_tracking.json")

with open(CALIBRATION_PATH, 'r') as f:
    calibration = json.load(f)

src_corners = np.float32([
    [calibration['court_corners'][0]['x'], calibration['court_corners'][0]['y']],
    [calibration['court_corners'][1]['x'], calibration['court_corners'][1]['y']],
    [calibration['court_corners'][2]['x'], calibration['court_corners'][2]['y']],
    [calibration['court_corners'][3]['x'], calibration['court_corners'][3]['y']]
])
dst_corners = np.float32([[0, 0], [280, 0], [280, 150], [0, 150]])
M = cv2.getPerspectiveTransform(src_corners, dst_corners)

def get_court_meters(pixel_x, pixel_y):
    point = np.array([[[pixel_x, pixel_y]]], dtype=np.float32)
    transformed = cv2.perspectiveTransform(point, M)
    return transformed[0][0][0] / 10.0, transformed[0][0][1] / 10.0

print("[AI Engine] Activating Model...")
onnx_model = YOLO("yolov8m.onnx", task="detect")

cap = cv2.VideoCapture(VIDEO_PATH)
video_fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
frame_idx = 0

if MAX_TEST_MINUTES is not None:
    target_frames = min(total_video_frames, int(MAX_TEST_MINUTES * 60 * video_fps))
else:
    target_frames = total_video_frames

render_interval = max(1, int(RENDER_EVERY_N_SECONDS * video_fps))

# Tracks comprehensive metadata logs for post-processing stitching
track_history = {} # { track_id: { start_frame: F, end_frame: F, last_pos: (x,y), first_pos: (x,y), distance: D } }
event_log = []

progress_bar = tqdm(total=target_frames, desc="[AI Engine] Analyzing Match", unit="fr")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret or (MAX_TEST_MINUTES is not None and frame_idx >= target_frames):
        break

    frame_idx += 1
    progress_bar.update(1)

    results = onnx_model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0, 32], verbose=False)

    if results[0].boxes.id is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        ids = results[0].boxes.id.cpu().numpy().astype(int)
        clss = results[0].boxes.cls.cpu().numpy().astype(int)

        for box, track_id, cls in zip(boxes, ids, clss):
            x1, y1, x2, y2 = box

            if cls == 0:  # Player Core Processing
                m_x, m_y = get_court_meters(int((x1 + x2) / 2), int(y2))
                if 0 <= m_x <= 28 and 0 <= m_y <= 15:
                    if track_id not in track_history:
                        track_history[track_id] = {
                            "start_frame": frame_idx, "end_frame": frame_idx,
                            "first_pos": (m_x, m_y), "last_pos": (m_x, m_y), "distance": 0.0
                        }
                    else:
                        hist = track_history[track_id]
                        last_x, last_y = hist["last_pos"]
                        step_dist = np.sqrt((m_x - last_x)**2 + (m_y - last_y)**2)

                        if step_dist > 0.05:
                            hist["distance"] += step_dist
                        hist["end_frame"] = frame_idx
                        hist["last_pos"] = (m_x, m_y)

            elif cls == 32:  # Basketball Processing
                ball_x, ball_y = int((x1 + x2) / 2), int((y1 + y2) / 2)
                lb, rb = calibration['left_basket'], calibration['right_basket']
                if lb['x'] <= ball_x <= lb['x'] + lb['w'] and lb['y'] <= ball_y <= lb['y'] + lb['h']:
                    event_log.append({"frame": frame_idx, "time": f"{frame_idx//int(video_fps)}s", "event": "Ball near Left Rim"})
                elif rb['x'] <= ball_x <= rb['x'] + rb['w'] and rb['y'] <= ball_y <= rb['y'] + rb['h']:
                    event_log.append({"frame": frame_idx, "time": f"{frame_idx//int(video_fps)}s", "event": "Ball near Right Rim"})

    if frame_idx % render_interval == 0:
        annotated_frame = results[0].plot()
        cv2.imshow("bstats AI - Core Pipeline", cv2.resize(annotated_frame, (960, 540)))
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()
progress_bar.close()

# =====================================================================
# 🧠 SPATIAL-TEMPORAL POST-PROCESSING AUTO-MERGER
# =====================================================================
print("[AI Engine] Running post-processing track auto-merger...")
merged_mappings = {} # Maps broken_id -> parent_id

# Sort tracks chronologically by when they appeared on the court
sorted_track_ids = sorted(track_history.keys(), key=lambda k: track_history[k]["start_frame"])

for i, active_id in enumerate(sorted_track_ids):
    # If this ID was already swallowed by an earlier merge mapping, skip it
    if active_id in merged_mappings:
        continue

    active_data = track_history[active_id]

    # Look ahead to see if any later track matches this profile
    for j in range(i + 1, len(sorted_track_ids)):
        candidate_id = sorted_track_ids[j]
        if candidate_id in merged_mappings:
            continue

        candidate_data = track_history[candidate_id]

        # Calculate Time Gap (in seconds)
        frame_gap = candidate_data["start_frame"] - active_data["end_frame"]
        seconds_gap = frame_gap / video_fps

        # Calculate Physical Proximity Gap (in meters)
        ax, ay = active_data["last_pos"]
        cx, cy = candidate_data["first_pos"]
        meters_gap = np.sqrt((cx - ax)**2 + (cy - ay)**2)

        # HEURISTIC CHECK: Did an ID vanish and reappear close by within a tight window?
        if 0 <= seconds_gap <= AUTO_MERGE_MAX_SECONDS and meters_gap <= AUTO_MERGE_MAX_METERS:
            # High certainty match detected! Merge candidate into active track chain
            merged_mappings[candidate_id] = active_id

            # Update parent track meta boundaries to include candidate properties
            active_data["end_frame"] = candidate_data["end_frame"]
            active_data["last_pos"] = candidate_data["last_pos"]
            active_data["distance"] += candidate_data["distance"]

# Compile final unified profiles
cleaned_metrics = {}
for tid, metrics in track_history.items():
    # Resolve root parent target ID
    root_id = tid
    while root_id in merged_mappings:
        root_id = merged_mappings[root_id]

    if root_id not in cleaned_metrics:
        cleaned_metrics[root_id] = 0.0
    cleaned_metrics[root_id] += metrics["distance"]

# Filter out tracking fragments (noise like a player's hand registering for 2 frames)
final_player_list = [
    {"track_id": int(rid), "total_meters_run": round(float(dist), 2)}
    for rid, dist in cleaned_metrics.items() if dist > 1.0  # Must run at least 1 meter to be counted
]

# Write cleanly structured schema
final_payload = {
    "total_frames_processed": frame_idx,
    "player_metrics": sorted(final_player_list, key=lambda x: x["total_meters_run"], reverse=True),
    "tracked_events": event_log
}

with open(OUTPUT_LOG_PATH, 'w') as f:
    json.dump(final_payload, f, indent=2)

print(f"[AI Engine] Auto-merge complete. Reduced track count down from {len(track_history)} to {len(final_player_list)} lines.")
print(f"[AI Engine] Output successfully saved to: {OUTPUT_LOG_PATH}")