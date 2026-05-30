# This is your main orchestrator script. It maps your modules together, handles frame ingestion,
# runs deep learning tracking, and cleanly writes your analytics output payload to disk.

import cv2
import json
import numpy as np
from tqdm import tqdm

import config
from background_model import generate_static_background
from ball_tracker import HeuristicBallTracker
from track_merger import merge_and_compile_analytics
from ultralytics import YOLO

def main():
    print(f"\n[Core Pipeline] Starting Inference Engine Workspace for file: {config.VIDEO_FILENAME}")

    cap = cv2.VideoCapture(config.VIDEO_PATH)
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    start_frame = int(config.START_MINUTE * 60 * video_fps)
    if config.DURATION_MINUTES is not None:
        end_frame = min(total_video_frames, start_frame + int(config.DURATION_MINUTES * 60 * video_fps))
    else:
        end_frame = total_video_frames
    cap.release()

    target_frames = end_frame - start_frame
    render_step = max(1, int(config.RENDER_EVERY_N_SECONDS * video_fps))

    bg_gray = generate_static_background(start_frame, end_frame)

    print("[AI Engine] Loading YOLOv8 Model Asset layers...")
    onnx_model = YOLO("yolov8m.onnx", task="detect")
    ball_engine = HeuristicBallTracker(config.CALIBRATION, video_fps)

    cap = cv2.VideoCapture(config.VIDEO_PATH)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_idx = start_frame

    track_history = {}
    possession_logs = {}
    event_log = []

    progress_bar = tqdm(total=target_frames, desc="[AI Engine] Tracking Match Data", unit="fr")

    WINDOW_TITLE = "bstats Core Analytics Pipeline"
    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or frame_idx >= end_frame:
            break

        frame_idx += 1
        progress_bar.update(1)

        results = onnx_model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0, 32], verbose=False)

        current_frame_players = {}
        yolo_ball_box = None

        if results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            ids = results[0].boxes.id.cpu().numpy().astype(int)
            clss = results[0].boxes.cls.cpu().numpy().astype(int)

            for box, track_id, cls in zip(boxes, ids, clss):
                x1, y1, x2, y2 = box.astype(int)

                if cls == 0:
                    m_x, m_y = config.get_court_meters(int((x1 + x2) / 2), y2)
                    if 0 <= m_x <= 28 and 0 <= m_y <= 15:
                        current_frame_players[track_id] = (m_x, m_y)

                        if track_id not in track_history:
                            track_history[track_id] = {
                                "first_seen_frame": frame_idx, "last_seen_frame": frame_idx,
                                "first_pos": (m_x, m_y), "last_pos": (m_x, m_y), "distance": 0.0,
                                "heights": [y2 - y1], "widths": [x2 - x1], "color_profiles": [],
                                "raw_presence_frames": []
                            }

                        hist = track_history[track_id]
                        last_x, last_y = hist["last_pos"]
                        step_dist = np.sqrt((m_x - last_x)**2 + (m_y - last_y)**2)

                        if step_dist > 0.05: hist["distance"] += step_dist
                        hist["last_seen_frame"] = frame_idx
                        hist["last_pos"] = (m_x, m_y)
                        hist["heights"].append(y2 - y1)
                        hist["widths"].append(x2 - x1)
                        hist["raw_presence_frames"].append(frame_idx)

                        if frame_idx % 5 == 0:
                            crop = frame[max(0, y1):min(frame.shape[0], y2), max(0, x1):min(frame.shape[1], x2)]
                            profile = config.extract_color_profile(crop)
                            if profile and profile["shirt"] is not None:
                                hist["color_profiles"].append(profile)

                elif cls == 32:
                    yolo_ball_box = box

        b_pixel, b_meters = ball_engine.track_ball_frame(frame, bg_gray, yolo_ball_box, config.get_court_meters, frame_idx)

        if b_pixel is not None:
            bx, by = b_pixel
            lb, rb = config.CALIBRATION['left_basket'], config.CALIBRATION['right_basket']
            if lb['x'] <= bx <= lb['x'] + lb['w'] and lb['y'] <= by <= lb['y'] + lb['h']:
                event_log.append({"frame": frame_idx, "time": f"{frame_idx//int(video_fps)}s", "event": "Ball near Left Rim"})
            elif rb['x'] <= bx <= rb['x'] + rb['w'] and rb['y'] <= by <= rb['y'] + rb['h']:
                event_log.append({"frame": frame_idx, "time": f"{frame_idx//int(video_fps)}s", "event": "Ball near Right Rim"})

            if current_frame_players:
                closest_pid = None
                min_d = float('inf')
                for pid, p_pos in current_frame_players.items():
                    # 🔥 FIXED: Changed bitwise XOR (^) to exponent power (**)
                    d = np.sqrt((b_meters[0] - p_pos[0])**2 + (b_meters[1] - p_pos[1])**2)
                    if d < min_d:
                        min_d = d
                        closest_pid = pid
                if min_d <= config.POSSESSION_DISTANCE_THRESHOLD_METERS:
                    possession_logs[frame_idx] = closest_pid

        if frame_idx % render_step == 0:
            annotated_frame = results[0].plot()
            if b_pixel is not None:
                cv2.circle(annotated_frame, b_pixel, 12, (0, 165, 255), -1)
            cv2.imshow(WINDOW_TITLE, cv2.resize(annotated_frame, (960, 540)))
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()
    progress_bar.close()

    player_metrics = merge_and_compile_analytics(track_history, possession_logs, video_fps, target_frames)

    final_payload = {
        "slice_window": {"start_min": config.START_MINUTE, "duration_min": config.DURATION_MINUTES},
        "total_frames_processed": target_frames,
        "player_metrics": player_metrics,
        "tracked_events": event_log
    }

    with open(config.OUTPUT_LOG_PATH, 'w') as f:
        json.dump(final_payload, f, indent=2)

    print(f"\n[Core Pipeline] Inference completely processed. Data compiled to:\n-> {config.OUTPUT_LOG_PATH}")

if __name__ == "__main__":
    main()