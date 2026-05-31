# This is your main orchestrator script. It maps your modules together, handles frame ingestion,
# runs deep learning tracking, and cleanly writes your analytics output payload to disk.

import cv2
import json
import numpy as np
from tqdm import tqdm
import onnxruntime as ort

available_providers = ort.get_available_providers()
print("\n[AI Environment] Registering available hardware execution layers:")
for provider in available_providers: print(f" -> Found: {provider}")
if 'DmlExecutionProvider' not in available_providers:
    print("\n⚠️ WARNING: 'DmlExecutionProvider' was not detected by ONNX Runtime. CPU fallback mode activated.\n")
else:
    print("🚀 SUCCESS: AMD DirectML acceleration layer hooked successfully!\n")

import config
from background_model import generate_static_background
from ball_tracker import HeuristicBallTracker
from track_merger import merge_and_compile_analytics
from ultralytics import YOLO

def main():
    print(f"\n[Core Pipeline] Starting Inference Engine Workspace for file: {config.VIDEO_FILENAME}")

    # 1. Initialize Video Frame metadata dimensions
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

    player_seeds = config.CALIBRATION.get("player_seeds", [])
    sub_zone = config.CALIBRATION.get("substitution_zone", [])

    cap = cv2.VideoCapture(config.VIDEO_PATH)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_idx = start_frame

    track_history, possession_logs, frame_momentum_history, last_player_positions = {}, {}, {}, {}
    progress_bar = tqdm(total=target_frames, desc="[AI Engine] Analyzing Match Timeline", unit="fr")

    WINDOW_TITLE = "bstats Debug Tracking Canvas"
    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_AUTOSIZE)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or frame_idx >= end_frame:
            break

        frame_idx += 1
        progress_bar.update(1)

        results = onnx_model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0, 32], verbose=False)
        current_frame_players, yolo_ball_box, player_displacements = {}, None, []

        if results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            ids = results[0].boxes.id.cpu().numpy().astype(int)
            clss = results[0].boxes.cls.cpu().numpy().astype(int)

            for box, track_id, cls in zip(boxes, ids, clss):
                x1, y1, x2, y2 = box.astype(int)
                if cls == 0:
                    foot_x = int((x1 + x2) / 2)
                    foot_y = y2
                    m_x, m_y = config.get_court_meters(foot_x, foot_y)
                    current_frame_players[track_id] = (m_x, m_y)

                    if track_id in last_player_positions:
                        dx = m_x - last_player_positions[track_id][0]
                        dy = m_y - last_player_positions[track_id][1]
                        player_displacements.append((dx, dy))
                    last_player_positions[track_id] = (m_x, m_y)

                    if track_id not in track_history:
                        track_history[track_id] = {
                            "first_seen_frame": frame_idx, "last_seen_frame": frame_idx,
                            "first_pos": (m_x, m_y), "last_pos": (m_x, m_y), "distance": 0.0,
                            "heights": [y2 - y1], "widths": [x2 - x1], "color_profiles": [],
                            "raw_presence_frames": [], "frame_positions": {}
                        }

                    hist = track_history[track_id]
                    lx, ly = hist["last_pos"]
                    step_dist = np.sqrt((m_x - lx)**2 + (m_y - ly)**2)

                    if step_dist > 0.05: hist["distance"] += step_dist
                    hist["last_seen_frame"] = frame_idx
                    hist["last_pos"] = (m_x, m_y)
                    hist["heights"].append(y2 - y1)
                    hist["widths"].append(x2 - x1)
                    hist["raw_presence_frames"].append(frame_idx)
                    hist["frame_positions"][frame_idx] = (m_x, m_y)

                    if frame_idx % 6 == 0:
                        crop = frame[max(0, y1):min(frame.shape[0], y2), max(0, x1):min(frame.shape[1], x2)]
                        profile = config.extract_color_profile(crop)
                        if profile and profile["shirt"] is not None:
                            hist["color_profiles"].append(profile)

                elif cls == 32:  # Ball Object Detection Bounding Anchor
                    yolo_ball_box = box

        if player_displacements:
            mean_momentum = np.mean(player_displacements, axis=0)
            frame_momentum_history[frame_idx] = (float(mean_momentum[0]), float(mean_momentum[1]))
        else:
            frame_momentum_history[frame_idx] = (0.0, 0.0)

        # 4. Trigger Secondary Core Ball Tracker Engine
        b_pixel, b_meters = ball_engine.track_ball_frame(frame, bg_gray, yolo_ball_box, config.get_court_meters, frame_idx)

        if b_pixel is not None:
            if current_frame_players:
                closest_pid, min_d = None, float('inf')
                for pid, p_pos in current_frame_players.items():
                    d = np.sqrt((b_meters[0] - p_pos[0])**2 + (b_meters[1] - p_pos[1])**2)
                    if d < min_d: min_d = d; closest_pid = pid
                if min_d <= config.POSSESSION_DISTANCE_THRESHOLD_METERS: possession_logs[frame_idx] = closest_pid

        if frame_idx % render_step == 0:
            preview_canvas = frame.copy()
            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy(); ids = results[0].boxes.id.cpu().numpy().astype(int); clss = results[0].boxes.cls.cpu().numpy().astype(int)
                for box, track_id, cls in zip(boxes, ids, clss):
                    x1, y1, x2, y2 = box.astype(int)
                    if cls == 0:
                        p_name = f"ID_{track_id}"
                        p_team = "light"
                        for seed in player_seeds:
                            if "boxes" in seed and len(seed["boxes"]) > 0:
                                if abs(frame_idx/video_fps - seed["boxes"][0]["timestamp"]) < 15.0:
                                    p_team = seed["team"]

                        f_mx, f_my = config.get_court_meters(int((x1+x2)/2), y2)
                        is_outside = not config.is_inside_court_boundaries(f_mx, f_my)

                        # FIXED: Linked character flag validations directly onto polygon contour maps
                        is_in_bench = config.is_point_in_substitution_zone(f_mx, f_my)
                        if is_outside or is_in_bench: p_name = f"#{p_name}"

                        draw_color = (0, 255, 0) if p_team == "light" else (0, 0, 255)
                        if p_team == "spectator": draw_color = (0, 255, 255)

                        cv2.rectangle(preview_canvas, (x1, y1), (x2, y2), draw_color, 2)
                        cv2.putText(preview_canvas, p_name, (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, draw_color, 2)

            if b_pixel is not None:
                bx, by = b_pixel
                cv2.rectangle(preview_canvas, (bx - 12, by - 12), (bx + 12, by + 12), (0, 165, 255), 2)
                cv2.putText(preview_canvas, "BALL", (bx - 15, by - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 2)

            # FIXED: Reconfigured to render the custom 4-Point polygon boundary cleanly using polylines
            if sub_zone and len(sub_zone) >= 4:
                pts_array = np.array([[pt['x'], pt['y']] for pt in sub_zone], dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(preview_canvas, [pts_array], True, (240, 50, 240), 2)

            cv2.imshow(WINDOW_TITLE, preview_canvas)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()
    progress_bar.close()

    # 6. Execute Advanced Spatial Track Analytics compilation pass
    player_metrics, possessions_timeline = merge_and_compile_analytics(
        track_history, possession_logs, frame_momentum_history, config.CALIBRATION, video_fps, target_frames
    )

    final_payload = {
        "slice_window": {"start_min": config.START_MINUTE, "duration_min": config.DURATION_MINUTES},
        "total_frames_processed": target_frames,
        "possessions": possessions_timeline,
        "player_metrics": player_metrics
    }

    with open(config.OUTPUT_LOG_PATH, 'w') as f:
        json.dump(final_payload, f, indent=2)

    print(f"\n[Core Pipeline] Processing completely finished. Advanced tracking metrics compiled to:\n-> {config.OUTPUT_LOG_PATH}")

if __name__ == "__main__":
    main()