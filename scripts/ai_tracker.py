import sys
import os
import cv2
import numpy as np
import json
from tqdm import tqdm

# =====================================================================
# ⚙️ CONFIGURATION BLOCK (Adjust your test settings here)
# =====================================================================
RENDER_EVERY_N_SECONDS = 3.0  # Render preview window every X seconds of game time
MAX_TEST_MINUTES = 1.0       # Process only first X minutes for testing. Set to None for full video.
# =====================================================================

# =====================================================================
# 🔥 CRITICAL AMD GPU ACCELERATION PATCH (DirectML Override)
# =====================================================================
import onnxruntime as ort
_original_InferenceSession_init = ort.InferenceSession.__init__
def _patched_InferenceSession_init(self, *args, **kwargs):
    providers = kwargs.get('providers', [])
    if 'DmlExecutionProvider' not in providers:
        kwargs['providers'] = ['DmlExecutionProvider', 'CPUExecutionProvider']
    _original_InferenceSession_init(self, *args, **kwargs)
ort.InferenceSession.__init__ = _patched_InferenceSession_init
# =====================================================================

from ultralytics import YOLO

# Verify CLI Arguments
if len(sys.argv) < 2:
    print("Error: Missing video filename.")
    print("Usage: python scripts/ai_tracker.py <video_filename>")
    sys.exit(1)

video_filename = sys.argv[1]
video_base_name, _ = os.path.splitext(video_filename)

# Directory Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")

VIDEO_PATH = os.path.join(VIDEOS_DIR, video_filename)
CALIBRATION_PATH = os.path.join(VIDEOS_DIR, "calibration.json")
OUTPUT_LOG_PATH = os.path.join(VIDEOS_DIR, f"{video_base_name}_tracking.json")

if not os.path.exists(VIDEO_PATH) or not os.path.exists(CALIBRATION_PATH):
    print("Error: Missing video or calibration configuration files.")
    sys.exit(1)

# Load Calibration Coordinates
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

# Load AI Tracking Engine
print("[AI Engine] Activating Model...")
if not os.path.exists("yolov8m.onnx"):
    model = YOLO("yolov8m.pt")
    print("[AI Engine] Exporting graph structure for hardware optimization...")
    model.export(format="onnx", dynamic=True)

onnx_model = YOLO("yolov8m.onnx", task="detect")

# Open Video Stream
cap = cv2.VideoCapture(VIDEO_PATH)
video_fps = cap.get(cv2.CAP_PROP_FPS)
if video_fps <= 0:
    video_fps = 20.0  # Fallback assumption if metadata reading fails

total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
frame_idx = 0

# Calculate structural termination limits if test settings are enabled
if MAX_TEST_MINUTES is not None:
    max_frames_to_process = int(MAX_TEST_MINUTES * 60 * video_fps)
    target_frames = min(total_video_frames, max_frames_to_process)
    print(f"[AI Engine] Test Mode Enabled: Script capped at first {MAX_TEST_MINUTES} minutes ({target_frames} frames).")
else:
    target_frames = total_video_frames
    print(f"[AI Engine] Full Production Mode: Processing complete video asset ({target_frames} frames).")

# Determine rendering interval frame count step
render_interval = max(1, int(RENDER_EVERY_N_SECONDS * video_fps))
print(f"[AI Engine] Visual UI Heartbeat configured to display 1 frame every {RENDER_EVERY_N_SECONDS} seconds ({render_interval} frames).")

player_distances = {}
player_last_positions = {}
event_log = []

# Initialize adaptive progress interface
progress_bar = tqdm(total=target_frames, desc="[AI Engine] Analyzing Match", unit="fr")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame_idx += 1

    # Terminate loop early if the test duration boundary is crossed
    if MAX_TEST_MINUTES is not None and frame_idx > target_frames:
        break

    progress_bar.update(1)

    # Run hardware-accelerated processing
    results = onnx_model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0, 32], verbose=False)

    if results[0].boxes.id is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        ids = results[0].boxes.id.cpu().numpy().astype(int)
        clss = results[0].boxes.cls.cpu().numpy().astype(int)

        for box, track_id, cls in zip(boxes, ids, clss):
            x1, y1, x2, y2 = box
            if cls == 0:  # Player Distance Engine
                m_x, m_y = get_court_meters(int((x1 + x2) / 2), int(y2))
                if 0 <= m_x <= 28 and 0 <= m_y <= 15:
                    if track_id in player_last_positions:
                        last_x, last_y = player_last_positions[track_id]
                        distance = np.sqrt((m_x - last_x)**2 + (m_y - last_y)**2)
                        if distance > 0.05:
                            player_distances[track_id] = player_distances.get(track_id, 0.0) + distance
                    player_last_positions[track_id] = (m_x, m_y)

            elif cls == 32:  # Basketball Event Engine
                ball_x, ball_y = int((x1 + x2) / 2), int((y1 + y2) / 2)
                lb, rb = calibration['left_basket'], calibration['right_basket']
                if lb['x'] <= ball_x <= lb['x'] + lb['w'] and lb['y'] <= ball_y <= lb['y'] + lb['h']:
                    event_log.append({"frame": frame_idx, "time": f"{frame_idx//int(video_fps)}s", "event": "Ball near Left Rim"})
                elif rb['x'] <= ball_x <= rb['x'] + rb['w'] and rb['y'] <= ball_y <= rb['y'] + rb['h']:
                    event_log.append({"frame": frame_idx, "time": f"{frame_idx//int(video_fps)}s", "event": "Ball near Right Rim"})

    # Configurable Visual Refresh Engine
    if frame_idx % render_interval == 0:
        annotated_frame = results[0].plot()
        # Appends window context details showing current structural time code
        window_title = f"bstats AI - Preview (Heartbeat: {RENDER_EVERY_N_SECONDS}s)"
        cv2.imshow(window_title, cv2.resize(annotated_frame, (960, 540)))
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("\n[AI Engine] Run execution interrupted by user.")
            break

cap.release()
cv2.destroyAllWindows()
progress_bar.close()

# Export Generated Analytics Records
final_payload = {
    "total_frames_processed": frame_idx - 1,
    "player_metrics": [
        {
            "track_id": int(tid),
            "total_meters_run": round(float(dist), 2)  # <-- Added float() cast here
        } for tid, dist in player_distances.items()
    ],
    "tracked_events": event_log
}

with open(OUTPUT_LOG_PATH, 'w') as f:
    json.dump(final_payload, f, indent=2)

print(f"\n[AI Engine] Analytics compilation output saved to: {OUTPUT_LOG_PATH}")