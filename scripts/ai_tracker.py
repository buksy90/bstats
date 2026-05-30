import cv2
import numpy as np
import json
import os
import sys
from ultralytics import YOLO

# 1. Setup File Paths
# Ensure the user passed the video filename argument
if len(sys.argv) < 2:
    print("Error: Missing video filename.")
    print("Usage: python scripts/ai_tracker.py <video_filename>")
    print("Example: python scripts/ai_tracker.py 28_5_1st_2.mp4")
    sys.exit(1)

# Grab filename from CLI args (equivalent to JavaScript's process.argv[2])
video_filename = sys.argv[1]
video_base_name, _ = os.path.splitext(video_filename)

# 1. Setup File Paths (Aligned with your updated 'videos' folder structure)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")

VIDEO_PATH = os.path.join(VIDEOS_DIR, video_filename)
CALIBRATION_PATH = os.path.join(VIDEOS_DIR, "calibration.json")
OUTPUT_LOG_PATH = os.path.join(VIDEOS_DIR, f"{video_base_name}_tracking.json")

# Quick sanity check before spinning up heavy AI engines
if not os.path.exists(VIDEO_PATH):
    print(f"Error: Target video file not found at {VIDEO_PATH}")
    sys.exit(1)
if not os.path.exists(CALIBRATION_PATH):
    print(f"Error: Calibration configuration missing at {CALIBRATION_PATH}. Run calibration first.")
    sys.exit(1)


# 2. Load Your Calibration Data
with open(CALIBRATION_PATH, 'r') as f:
    calibration = json.load(f)

# Extract points from your JSON response
src_corners = np.float32([
    [calibration['court_corners'][0]['x'], calibration['court_corners'][0]['y']], # Top-Left
    [calibration['court_corners'][1]['x'], calibration['court_corners'][1]['y']], # Top-Right
    [calibration['court_corners'][2]['x'], calibration['court_corners'][2]['y']], # Bottom-Right
    [calibration['court_corners'][3]['x'], calibration['court_corners'][3]['y']]  # Bottom-Left
])

# Define the destination grid representing your true 28m x 15m court dimensions (scaled x10 for accuracy)
dst_corners = np.float32([
    [0, 0],       # Top-Left mapping
    [280, 0],     # Top-Right mapping (28 meters)
    [280, 150],   # Bottom-Right mapping
    [0, 150]      # Bottom-Left mapping (15 meters)
])

# Calculate the Homography Matrix for perspective transformations
M = cv2.getPerspectiveTransform(src_corners, dst_corners)

def get_court_meters(pixel_x, pixel_y):
    """Converts pixel coordinates to real world (X, Y) meters on court."""
    point = np.array([[[pixel_x, pixel_y]]], dtype=np.float32)
    transformed = cv2.perspectiveTransform(point, M)
    real_x = transformed[0][0][0] / 10.0 # Scaling back to true meters
    real_y = transformed[0][0][1] / 10.0
    return real_x, real_y

# 3. Initialize AI Models
print("[AI Engine] Loading YOLOv8 Model...")
model = YOLO("yolov8m.pt") # 'm' (medium) balances accuracy and speed on your RX 7800 XT

# Export model to ONNX format with DirectML execution provider capabilities
if not os.path.exists("yolov8m.onnx"):
    print("[AI Engine] Optimizing model for AMD GPU via ONNX export...")
    model.export(format="onnx", dynamic=True)

# Re-load the highly efficient tracking engine
onnx_model = YOLO("yolov8m.onnx", task="detect")

# 4. Process Video Stream
cap = cv2.VideoCapture(VIDEO_PATH)
frame_idx = 0

# Data structures to keep track of match states
player_distances = {} # { track_id: total_meters_run }
player_last_positions = {} # { track_id: (last_m_x, last_m_y) }
event_log = []

print("[AI Engine] Starting analysis loop. Press 'q' to stop visualization preview.")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame_idx += 1

    # Run tracking using ByteTrack engine built natively into Ultralytics
    # classes=[0, 32] filters detections specifically to People (0) and Sports Balls (32)
    results = onnx_model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0, 32], verbose=False)

    if results[0].boxes.id is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        ids = results[0].boxes.id.cpu().numpy().astype(int)
        clss = results[0].boxes.cls.cpu().numpy().astype(int)

        for box, track_id, cls in zip(boxes, ids, clss):
            x1, y1, x2, y2 = box

            if cls == 0: # Person/Player Detected
                # Target the center bottom position of bounding box (the feet)
                feet_x = int((x1 + x2) / 2)
                feet_y = int(y2)

                # Convert feet coordinates to real world court meters
                m_x, m_y = get_court_meters(feet_x, feet_y)

                # Verify if player position falls inside the legal active boundary grid
                if 0 <= m_x <= 28 and 0 <= m_y <= 15:
                    if track_id in player_last_positions:
                        last_x, last_y = player_last_positions[track_id]
                        # Calculate distance traveled between frames (Euclidean Distance Formula)
                        distance = np.sqrt((m_x - last_x)**2 + (m_y - last_y)**2)

                        # Disregard tracking jitters/shake below 5cm per frame
                        if distance > 0.05:
                            player_distances[track_id] = player_distances.get(track_id, 0.0) + distance

                    player_last_positions[track_id] = (m_x, m_y)

            elif cls == 32: # Basketball Detected
                ball_x = int((x1 + x2) / 2)
                ball_y = int((y1 + y2) / 2)

                # Baseline validation checking if ball coordinates cross your rim targets
                lb = calibration['left_basket']
                rb = calibration['right_basket']

                if lb['x'] <= ball_x <= lb['x'] + lb['w'] and lb['y'] <= ball_y <= lb['y'] + lb['h']:
                    event_log.append({"frame": frame_idx, "time": f"{frame_idx//20}s", "event": "Ball near Left Rim"})
                elif rb['x'] <= ball_x <= rb['x'] + rb['w'] and rb['y'] <= ball_y <= rb['y'] + rb['h']:
                    event_log.append({"frame": frame_idx, "time": f"{frame_idx//20}s", "event": "Ball near Right Rim"})

    # Optional Preview Window (Can be hidden to maximize system processing speeds)
    # Renders the live analytical tracking progress visually over frame
    if frame_idx % 2 == 0:
        annotated_frame = results[0].plot()
        cv2.imshow("bstats - AI Tracking Engine Core", cv2.resize(annotated_frame, (960, 540)))
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()

# 5. Compile and Save Tracking Analytics Payload Structure
final_payload = {
    "total_frames_processed": frame_idx,
    "player_metrics": [
        {"track_id": int(tid), "total_meters_run": round(dist, 2)}
        for tid, dist in player_distances.items()
    ],
    "tracked_events": event_log
}

with open(OUTPUT_LOG_PATH, 'w') as f:
    json.dump(final_payload, f, indent=2)

print(f"\n[AI Engine] Batch processing completed successfully!")
print(f"[AI Engine] Structured asset data logged cleanly to: {OUTPUT_LOG_PATH}")