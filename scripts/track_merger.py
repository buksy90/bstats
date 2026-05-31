# This module manages post-processing track cleaning, auto-merging ID fragments by matching clothing
# color signatures and player heights, and computing substitution and ball possession logs.

import numpy as np
import cv2
from config import AUTO_MERGE_MAX_SECONDS, AUTO_MERGE_MAX_METERS, COLOR_SIMILARITY_THRESHOLD, SUB_TIMEOUT_SECONDS, is_point_in_substitution_zone, is_inside_court_boundaries

def merge_and_compile_analytics(track_history, possession_logs, frame_momentum_history, calibration, video_fps, total_processed_frames):
    print("[Post-Processor] Launching multi-factor fusion track auto-merger...")
    merged_mappings = {}
    sorted_ids = sorted(track_history.keys(), key=lambda k: track_history[k]["first_seen_frame"])

    for tid, h in track_history.items():
        h["avg_height"] = float(np.mean(h["heights"])) if h["heights"] else 0.0
        h["avg_width"] = float(np.mean(h["widths"])) if h["widths"] else 0.0

    # 1. Human-In-The-Loop Pre-Seeding Priority Mapping
    # Match raw tracks to user-defined player seeds from calibration if jersey/size matches
    player_seeds = calibration.get("player_seeds", [])
    seed_profiles = {}
    for seed in player_seeds:
        seed_profiles[seed["name"]] = {
            "team": seed["team"],
            "boxes": seed.get("boxes", [])
        }

    # 2. Sequential Structural Cluster Merger Loop
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

                if height_ratio > 0.80:
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
                            active_data["frame_positions"].update(candidate_data["frame_positions"])
                            active_data["color_profiles"].extend(candidate_data["color_profiles"])

    # 3. Resolve Ground Truth Identities from User Seeding Profiles
    final_profiles = {}
    track_to_name_map = {}

    for tid, metrics in track_history.items():
        root_id = tid
        while root_id in merged_mappings:
            root_id = merged_mappings[root_id]

        # Correlate track ID to user seed mapping profile names
        assigned_name = f"Player_{root_id}"
        assigned_team = "light"  # Default clustering fallback

        # Cross check if this track fits any user-marked boxes from calibration data
        for seed in player_seeds:
            if "boxes" in seed and len(seed["boxes"]) > 0:
                if abs(metrics["first_seen_frame"]/video_fps - seed["boxes"][0]["timestamp"]) < 5.0:
                    assigned_name = seed["name"]
                    assigned_team = seed["team"]
                    break

        track_to_name_map[tid] = assigned_name

        if assigned_name not in final_profiles:
            final_profiles[assigned_name] = {
                "name": assigned_name,
                "team": assigned_team,
                "distance": 0.0,
                "h": metrics["avg_height"],
                "w": metrics["avg_width"],
                "presence_frames": [],
                "frame_positions": {},
                "possession_count": 0
            }

        final_profiles[assigned_name]["distance"] += metrics["distance"]
        final_profiles[assigned_name]["presence_frames"].extend(metrics["raw_presence_frames"])
        final_profiles[assigned_name]["frame_positions"].update(metrics["frame_positions"])

    # Map compiled possession metrics onto human names
    resolved_possession_logs = {}
    for f_idx, raw_tid in possession_logs.items():
        if raw_tid in track_to_name_map:
            name = track_to_name_map[raw_tid]
            resolved_possession_logs[f_idx] = name
            if name in final_profiles:
                final_profiles[name]["possession_count"] += 1

    def time_str(f):
        ts = int(f // video_fps)
        return f"{ts // 60:02d}:{ts % 60:02d}"

    player_metrics_output = []
    timeout_frames = int(SUB_TIMEOUT_SECONDS * video_fps)
    inbound_play_frames_limit = int(20.0 * video_fps) # 20 Second Playmaker filter threshold

    for name, p in final_profiles.items():
        if p["team"] == "spectator": continue # Exclude spectators from game loops
        if p["distance"] < 1.5: continue

        frames = sorted(list(set(p["presence_frames"])))
        if not frames: continue

        raw_sub_events = []
        played_frames_accumulator = 0
        seg_start = frames[0]
        seg_prev = frames[0]

        for f in frames[1:]:
            if f - seg_prev > timeout_frames:
                # Read foot location at last visible point to verify if inside the bench box matrix
                last_pos = p["frame_positions"].get(seg_prev, (0, 0))

                # FIXED: Relational point verification queries swapped seamlessly onto python contours
                is_in_sub_box = is_point_in_substitution_zone(last_pos[0], last_pos[1])
                is_outside_court = not is_inside_court_boundaries(last_pos[0], last_pos[1])

                if is_outside_court or is_in_sub_box:
                    raw_sub_events.append({"type": "sub_in", "frame": int(seg_start)})
                    raw_sub_events.append({"type": "sub_out", "frame": int(seg_prev)})
                    played_frames_accumulator += (seg_prev - seg_start) + 1
                    seg_start = f
            seg_prev = f

        raw_sub_events.append({"type": "sub_in", "frame": int(seg_start)})
        raw_sub_events.append({"type": "sub_out", "frame": int(seg_prev)})
        played_frames_accumulator += (seg_prev - seg_start) + 1

        # 🔥 RETROACTIVE PLAY FILTER: Erase sub loops if gone for less than 20 seconds
        filtered_sub_events = []
        i = 0
        while i < len(raw_sub_events):
            if i + 2 < len(raw_sub_events) and raw_sub_events[i]["type"] == "sub_out":
                next_in_frame = raw_sub_events[i+1]["frame"]
                time_elapsed_outside = next_in_frame - raw_sub_events[i]["frame"]

                if time_elapsed_outside < inbound_play_frames_limit:
                    # Player was just inbounding or executing corner play, skip appending sub actions
                    i += 2
                    continue
            filtered_sub_events.append(raw_sub_events[i])
            i += 1

        # Format timelines cleanly for final JSON payload export
        formatted_subs = []
        for ev in filtered_sub_events:
            formatted_subs.append({
                "type": ev["type"],
                "frame": ev["frame"],
                "time": time_str(ev["frame"])
            })

        player_metrics_output.append({
            "name": name,
            "team": p["team"],
            "total_meters_run": round(float(p["distance"]), 2),
            "minutes_played": round(float(played_frames_accumulator / video_fps / 60.0), 2),
            "minutes_rested": max(0.0, round(float((total_processed_frames - played_frames_accumulator) / video_fps / 60.0), 2)),
            "possession_seconds": round(float(p["possession_count"] / video_fps), 1),
            "sub_events": formatted_subs,
            "ui_hints": {"avg_height_pixels": round(p["h"], 1), "avg_width_pixels": round(p["w"], 1)}
        })

    # 5. Macroscopic Possession Block Generator Core
    possessions_timeline = []
    all_possession_frames = sorted(resolved_possession_logs.keys())

    if all_possession_frames:
        current_block = {
            "start_frame": all_possession_frames[0],
            "team": final_profiles[resolved_possession_logs[all_possession_frames[0]]]["team"],
            "players_touched": [resolved_possession_logs[all_possession_frames[0]]]
        }

        for f in all_possession_frames[1:]:
            handler_name = resolved_possession_logs[f]
            handler_team = final_profiles[handler_name]["team"]

            # If team maintains ball lock, accumulate touches onto continuous segment
            if handler_team == current_block["team"] and (f - current_block["start_frame"] < video_fps * 6.0):
                if handler_name not in current_block["players_touched"]:
                    current_block["players_touched"].append(handler_name)
            else:
                # Terminate segment block and extract macroscopic event characteristics
                end_f = f - 1
                mom_vec = frame_momentum_history.get(end_f, (0.0, 0.0))

                # Deduce structural transition events via macro total team union velocity vector loops
                end_event = "pass"
                if np.abs(mom_vec[0]) > 1.8: end_event = "turnover" # Sudden court direction reversal

                possessions_timeline.append({
                    "start": time_str(current_block["start_frame"]),
                    "end": time_str(end_f),
                    "team": current_block["team"],
                    "start_event": "possession_gain",
                    "end_event": end_event,
                    "players_touched_ball": current_block["players_touched"]
                })

                current_block = {
                    "start_frame": f,
                    "team": handler_team,
                    "players_touched": [handler_name]
                }

        # Append trailing timeline segment closures
        possessions_timeline.append({
            "start": time_str(current_block["start_frame"]),
            "end": time_str(all_possession_frames[-1]),
            "team": current_block["team"],
            "start_event": "possession_gain",
            "end_event": "clock_stop",
            "players_touched_ball": current_block["players_touched"]
        })

    return player_metrics_output, possessions_timeline