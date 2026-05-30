import sys
import os
import cv2
import numpy as np
import json
from tqdm import tqdm

# =====================================================================
# ⚙️ CONFIGURATION BLOCK
# =====================================================================
RENDER_EVERY_N_SECONDS = 3.0
START_MINUTE = 0.0           # Choose exact minute to start processing
DURATION_MINUTES = 1.0       # Duration of video slice to analyze (None for full video)

# Advanced Auto-Merger Thresholds
AUTO_MERGE_MAX_SECONDS = 4.0
AUTO_MERGE_MAX_METERS = 3.0
COLOR_SIMILARITY_THRESHOLD = 0.65  # 0 to 1 (Higher = stricter color match required)
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

def extract_color_profile(img_crop):
    """Splits crop into shirt/shorts zones and extracts HSV Histograms."""
    if img_crop.size == 0:
        return None
    hsv = cv2.cvtColor(img_crop, cv2.COLOR_BGR2HSV)
    h, w, _ = hsv.shape

    # Isolate Upper 40% (Shirt) and Lower 40% (Shorts)
    shirt_zone = hsv[0:int(h*0.4), :]
    shorts_zone = hsv[int(h*0.6):h, :]

    def get_hist(zone):
        if zone.size == 0: return None
        hist = cv2.calcHist([zone], [0, 1], None, [8, 8], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        return hist.flatten()

    return {"shirt": get_hist(shirt_zone), "shorts": get_hist(shorts_zone)}

print("[AI Engine] Activating Model...")
onnx_model = YOLO("yolov8m.onnx", task="detect")

cap = cv2.VideoCapture(VIDEO_PATH)
video_fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

# Calculate Start/End Boundaries
start_frame = int(START_MINUTE * 60 * video_fps)
if DURATION_MINUTES is not None:
    end_frame = min(total_video_frames, start_frame + int(DURATION_MINUTES * 60 * video_fps))
else:
    end_frame = total_video_frames

target_frames = end_frame - start_frame
cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
frame_idx = start_frame

print(f"[AI Engine] Target Window: Minute {START_MINUTE} to {START_MINUTE + (DURATION_MINUTES or 0)} ({target_frames} frames to process).")
render_interval = max(1, int(RENDER_EVERY_N_SECONDS * video_fps))

track_history = {}
event_log = []

progress_bar = tqdm(total=target_frames, desc="[AI Engine] Analyzing Match", unit="fr")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret or frame_idx >= end_frame:
        break

    frame_idx += 1
    progress_bar.update(1)

    results = onnx_model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0, 32], verbose=False)

    if results[0].boxes.id is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        ids = results[0].boxes.id.cpu().numpy().astype(int)
        clss = results[0].boxes.cls.cpu().numpy().astype(int)

        for box, track_id, cls in zip(boxes, ids, clss):
            x1, y1, x2, y2 = box.astype(int)

            if cls == 0:  # Player Footsteps Tracking
                m_x, m_y = get_court_meters(int((x1 + x2) / 2), y2)
                if 0 <= m_x <= 28 and 0 <= m_y <= 15:
                    # Clip boundaries safely to image limits
                    y1_c, y2_c = max(0, y1), min(frame.shape[0], y2)
                    x1_c, x2_c = max(0, x1), min(frame.shape[1], x2)
                    crop = frame[y1_c:y2_c, x1_c:x2_c]

                    p_height = y2 - y1
                    p_width = x2 - x1

                    if track_id not in track_history:
                        track_history[track_id] = {
                            "start_frame": frame_idx, "end_frame": frame_idx,
                            "first_pos": (m_x, m_y), "last_pos": (m_x, m_y), "distance": 0.0,
                            "heights": [p_height], "widths": [p_width], "color_profiles": []
                        }

                    hist = track_history[track_id]
                    last_x, last_y = hist["last_pos"]
                    step_dist = np.sqrt((m_x - last_x)**2 + (m_y - last_y)**2)

                    if step_dist > 0.05:
                        hist["distance"] += step_dist
                    hist["end_frame"] = frame_idx
                    hist["last_pos"] = (m_x, m_y)
                    hist["heights"].append(p_height)
                    hist["widths"].append(p_width)

                    # Store color profiles periodically to conserve RAM
                    if frame_idx % 5 == 0:
                        profile = extract_color_profile(crop)
                        if profile and profile["shirt"] is not None:
                            hist["color_profiles"].append(profile)

            elif cls == 32:  # Basketball Target Tracking
                ball_x, ball_y = int((x1 + x2) / 2), int((y1 + y2) / 2)
                lb, rb = calibration['left_basket'], calibration['right_basket']
                if lb['x'] <= ball_x <= lb['x'] + lb['w'] and lb['y'] <= ball_y <= lb['y'] + lb['h']:
                    event_log.append({"frame": frame_idx, "time": f"{frame_idx//int(video_fps)}s", "event": "Ball near Left Rim"})
                elif rb['x'] <= ball_x <= rb['x'] + rb['w'] and rb['y'] <= ball_y <= ball_y <= rb['h']:
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
# 🧠 ADVANCED MULTI-FACTOR FUSION AUTO-MERGER
# =====================================================================
print("[AI Engine] Running multi-factor fusion track auto-merger...")
merged_mappings = {}
sorted_track_ids = sorted(track_history.keys(), key=lambda k: track_history[k]["start_frame"])

# Process structural averages
for tid, h in track_history.items():
    h["avg_height"] = float(np.mean(h["heights"])) if h["heights"] else 0.0
    h["avg_width"] = float(np.mean(h["widths"])) if h["widths"] else 0.0

def compare_histograms(histA, histB):
    if histA is None or histB is None: return 0.0
    return cv2.compareHist(histA, histB, cv2.HISTCMP_CORREL)

for i, active_id in enumerate(sorted_track_ids):
    if active_id in merged_mappings: continue
    active_data = track_history[active_id]

    for j in range(i + 1, len(sorted_track_ids)):
        candidate_id = sorted_track_ids[j]
        if candidate_id in merged_mappings: continue
        candidate_data = track_history[candidate_id]

        seconds_gap = (candidate_data["start_frame"] - active_data["end_frame"]) / video_fps
        ax, ay = active_data["last_pos"]
        cx, cy = candidate_data["first_pos"]
        meters_gap = np.sqrt((cx - ax)**2 + (cy - ay)**2)

        # Factor 1: Spatial-Temporal Alignment
        if 0 <= seconds_gap <= AUTO_MERGE_MAX_SECONDS and meters_gap <= AUTO_MERGE_MAX_METERS:
            # Factor 2: Bounding Box Shape Compatibility (Height check within 20% margin)
            height_ratio = min(active_data["avg_height"], candidate_data["avg_height"]) / max(active_data["avg_height"], candidate_data["avg_height"])

            if height_ratio > 0.80:
                # Factor 3: Color Signature Evaluation (Shirt & Shorts profiles)
                if active_data["color_profiles"] and candidate_data["color_profiles"]:
                    # Match using the last logged frame of Parent and first frame of Candidate
                    profA = active_data["color_profiles"][-1]
                    profB = candidate_data["color_profiles"][0]

                    shirt_sim = compare_histograms(profA["shirt"], profB["shirt"])
                    shorts_sim = compare_histograms(profA["shorts"], profB["shorts"])
                    combined_color_score = (shirt_sim + shorts_sim) / 2.0

                    if combined_color_score >= COLOR_SIMILARITY_THRESHOLD:
                        merged_mappings[candidate_id] = active_id
                        active_data["end_frame"] = candidate_data["end_frame"]
                        active_data["last_pos"] = candidate_data["last_pos"]
                        active_data["distance"] += candidate_data["distance"]
                        active_data["color_profiles"].extend(candidate_data["color_profiles"])

# Aggregate profiles cleanly
cleaned_metrics = {}
for tid, metrics in track_history.items():
    root_id = tid
    while root_id in merged_mappings:
        root_id = merged_mappings[root_id]
    if root_id not in cleaned_metrics:
        cleaned_metrics[root_id] = {"distance": 0.0, "h": metrics["avg_height"], "w": metrics["avg_width"]}
    cleaned_metrics[root_id]["distance"] += metrics["distance"]

final_player_list = [
    {
        "track_id": int(rid),
        "total_meters_run": round(float(m["distance"]), 2),
        "ui_hints": {"avg_height_pixels": round(m["h"], 1), "avg_width_pixels": round(m["w"], 1)}
    }
    for rid, m in cleaned_metrics.items() if m["distance"] > 2.0  # Wipes track static noise
]

final_payload = {
    "slice_window": {"start_min": START_MINUTE, "duration_min": DURATION_MINUTES},
    "total_frames_processed": frame_idx - start_frame,
    "player_metrics": sorted(final_player_list, key=lambda x: x["total_meters_run"], reverse=True),
    "tracked_events": event_log
}

with open(OUTPUT_LOG_PATH, 'w') as f:
    json.dump(final_payload, f, indent=2)

print(f"[AI Engine] Complete. Track count reduced to {len(final_player_list)} clean profiles.")