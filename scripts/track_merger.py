# This module manages post-processing track cleaning, auto-merging ID fragments by matching clothing
# color signatures and player heights, and computing substitution and ball possession logs.

import numpy as np
import cv2
from config import AUTO_MERGE_MAX_SECONDS, AUTO_MERGE_MAX_METERS, COLOR_SIMILARITY_THRESHOLD, SUB_TIMEOUT_SECONDS

def merge_and_compile_analytics(track_history, possession_logs, video_fps, total_processed_frames):
    print("[Post-Processor] Launching multi-factor fusion track auto-merger...")
    merged_mappings = {}
    sorted_ids = sorted(track_history.keys(), key=lambda k: track_history[k]["first_seen_frame"])

    for tid, h in track_history.items():
        h["avg_height"] = float(np.mean(h["heights"])) if h["heights"] else 0.0
        h["avg_width"] = float(np.mean(h["widths"])) if h["widths"] else 0.0

    # 1. Multi-Factor Cluster Merger Loop
    for i, active_id in enumerate(sorted_ids):
        if active_id in merged_mappings: continue
        active_data = track_history[active_id]

        for j in range(i + 1, len(sorted_ids)):
            candidate_id = sorted_ids[j]
            if candidate_id in merged_mappings: continue
            candidate_data = track_history[candidate_id]

            seconds_gap = (candidate_data["first_seen_frame"] - active_data["last_seen_frame"]) / video_fps
            ax, ay = active_data["last_pos"]
            cx, cy = candidate_data["first_pos"]
            meters_gap = np.sqrt((cx - ax)**2 + (cy - ay)**2)

            if 0 <= seconds_gap <= AUTO_MERGE_MAX_SECONDS and meters_gap <= AUTO_MERGE_MAX_METERS:
                height_ratio = min(active_data["avg_height"], candidate_data["avg_height"]) / max(active_data["avg_height"], candidate_data["avg_height"])

                if height_ratio > 0.80: # Bounding Box dimensions match within 20%
                    if active_data["color_profiles"] and candidate_data["color_profiles"]:
                        profA = active_data["color_profiles"][-1]
                        profB = candidate_data["color_profiles"][0]

                        shirt_sim = cv2.compareHist(profA["shirt"], profB["shirt"], cv2.HISTCMP_CORREL)
                        shorts_sim = cv2.compareHist(profA["shorts"], profB["shorts"], cv2.HISTCMP_CORREL)

                        if ((shirt_sim + shorts_sim) / 2.0) >= COLOR_SIMILARITY_THRESHOLD:
                            merged_mappings[candidate_id] = active_id
                            active_data["last_seen_frame"] = candidate_data["last_seen_frame"]
                            active_data["last_pos"] = candidate_data["last_pos"]
                            active_data["distance"] += candidate_data["distance"]
                            active_data["raw_presence_frames"].extend(candidate_data["raw_presence_frames"])
                            active_data["color_profiles"].extend(candidate_data["color_profiles"])

    # 2. Compile Consolidated Profiles & Substitution State Machine
    final_profiles = {}
    for tid, metrics in track_history.items():
        root_id = tid
        while root_id in merged_mappings:
            root_id = merged_mappings[root_id]

        if root_id not in final_profiles:
            final_profiles[root_id] = {"distance": 0.0, "h": metrics["avg_height"], "w": metrics["avg_width"], "presence_frames": [], "possession_count": 0}

        final_profiles[root_id]["distance"] += metrics["distance"]
        final_profiles[root_id]["presence_frames"].extend(metrics["raw_presence_frames"])

    # Map compiled player possession frame metrics
    for frame_idx, handler_id in possession_logs.items():
        root_handler = handler_id
        while root_handler in merged_mappings:
            root_handler = merged_mappings[root_handler]
        if root_handler in final_profiles:
            final_profiles[root_handler]["possession_count"] += 1

    # Generate Output List Structure
    output_list = []
    timeout_frames = int(SUB_TIMEOUT_SECONDS * video_fps)

    def time_str(f):
        ts = int(f // video_fps)
        return f"{ts // 60:02d}:{ts % 60:02d}"

    for rid, p in final_profiles.items():
        if p["distance"] < 2.0: continue # Clear out brief tracking noise fragments

        frames = sorted(list(set(p["presence_frames"])))
        if not frames: continue

        sub_events = []
        played_frames_accumulator = 0
        seg_start = frames[0]
        seg_prev = frames[0]

        for f in frames[1:]:
            if f - seg_prev > timeout_frames:
                sub_events.append({"type": "sub_in", "frame": int(seg_start), "time": time_str(seg_start)})
                sub_events.append({"type": "sub_out", "frame": int(seg_prev), "time": time_str(seg_prev)})
                played_frames_accumulator += (seg_prev - seg_start) + 1
                seg_start = f
            seg_prev = f

        sub_events.append({"type": "sub_in", "frame": int(seg_start), "time": time_str(seg_start)})
        sub_events.append({"type": "sub_out", "frame": int(seg_prev), "time": time_str(seg_prev)})
        played_frames_accumulator += (seg_prev - seg_start) + 1

        output_list.append({
            "track_id": int(rid),
            "total_meters_run": round(float(p["distance"]), 2),
            "minutes_played": round(float(played_frames_accumulator / video_fps / 60.0), 2),
            "minutes_rested": round(float((total_processed_frames - played_frames_accumulator) / video_fps / 60.0), 2),
            "possession_seconds": round(float(p["possession_count"] / video_fps), 1),
            "sub_events": sorted(sub_events, key=lambda x: x["frame"]),
            "ui_hints": {"avg_height_pixels": round(p["h"], 1), "avg_width_pixels": round(p["w"], 1)}
        })

    return sorted(output_list, key=lambda x: x["total_meters_run"], reverse=True)