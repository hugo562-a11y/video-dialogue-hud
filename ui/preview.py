"""PreviewMixin — 預覽畫布的渲染、縮放、ROI 框選與氣泡拖曳。"""
from __future__ import annotations

from PIL import Image, ImageTk


class PreviewMixin:

    # ------------------------------------------------------------------ 圖像設置
    def set_preview_image(self, pil_img: Image.Image, reset_view: bool = False):
        old_size = self.preview_pil_orig.size if self.preview_pil_orig is not None else None
        self.preview_pil_orig = pil_img
        if reset_view or old_size != self.preview_pil_orig.size:
            self.preview_zoom = 1.0
            self.canvas_offset = [0, 0]
        if self.renderer.video_width and self.preview_pil_orig:
            self.preview_scale_x = self.preview_pil_orig.size[0] / self.renderer.video_width
            self.preview_scale_y = self.preview_pil_orig.size[1] / self.renderer.video_height
        self._refresh_canvas()

    def _refresh_canvas(self):
        if self.preview_pil_orig is None:
            return
        ow, oh = self.preview_pil_orig.size
        nw = max(1, int(ow * self.preview_zoom))
        nh = max(1, int(oh * self.preview_zoom))
        scaled = self.preview_pil_orig.resize((nw, nh), Image.Resampling.LANCZOS)
        self._canvas_tk_img = ImageTk.PhotoImage(scaled)
        cw = self.preview_canvas.winfo_width() or 600
        ch = self.preview_canvas.winfo_height() or 400
        cx = cw // 2 + self.canvas_offset[0]
        cy = ch // 2 + self.canvas_offset[1]
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(cx, cy, anchor="center", image=self._canvas_tk_img)
        self._draw_person_rois_on_canvas()
        self._draw_preview_boxes_on_canvas()
        self.preview_canvas.create_text(
            cw - 8, ch - 8, anchor="se",
            text=f"{int(self.preview_zoom * 100)}%",
            fill="#AAB0C0", font=("Consolas", 11),
        )

    def _draw_person_rois_on_canvas(self):
        for idx, roi in enumerate(self.renderer.person_rois, start=1):
            x1, y1 = self._video_to_canvas(roi[0], roi[1])
            x2, y2 = self._video_to_canvas(roi[2], roi[3])
            self._draw_person_marker(idx, (x1, y1, x2, y2), f"人物 {idx}")

    def _draw_preview_boxes_on_canvas(self):
        speakers = set(self.renderer.data_processor.get_unique_speakers()) if self.renderer.data_processor.has_data() else None
        for box in self.preview_boxes:
            tid = int(box["id"])
            label = self.renderer.yolo_id_to_speaker.get(tid, f"人物 {tid}")
            # 如果腳本中不包含該說話者，就不要在畫面上繪製其人物框
            if speakers is not None and label not in speakers:
                continue
            x1, y1 = self._video_to_canvas(box["bbox"][0], box["bbox"][1])
            x2, y2 = self._video_to_canvas(box["bbox"][2], box["bbox"][3])
            self._draw_person_marker(tid, (x1, y1, x2, y2), label)

    def _draw_person_marker(self, tid: int, rect, label: str):
        x1, y1, x2, y2 = rect
        color = self.renderer.bubble_color_hex(tid)
        text_color = self.renderer.bubble_text_hex(tid)
        self.preview_canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=3)
        text_id = self.preview_canvas.create_text(
            x1 + 8, y1 + 8, anchor="nw",
            text=label, fill=text_color,
            font=("Microsoft JhengHei UI", 12, "bold"),
        )
        bbox = self.preview_canvas.bbox(text_id)
        if bbox:
            pad = 4
            bg_id = self.preview_canvas.create_rectangle(
                bbox[0] - pad, bbox[1] - 2, bbox[2] + pad, bbox[3] + 2,
                fill=color, outline=color,
            )
            self.preview_canvas.tag_lower(bg_id, text_id)

    # ------------------------------------------------------------------ 座標轉換
    def _video_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        cw = self.preview_canvas.winfo_width() or 600
        ch = self.preview_canvas.winfo_height() or 400
        center_x = cw // 2 + self.canvas_offset[0]
        center_y = ch // 2 + self.canvas_offset[1]
        ow, oh = self.preview_pil_orig.size if self.preview_pil_orig else (600, 400)
        img_x = x * self.preview_scale_x
        img_y = y * self.preview_scale_y
        return (
            center_x + (img_x - ow / 2) * self.preview_zoom,
            center_y + (img_y - oh / 2) * self.preview_zoom,
        )

    def _canvas_to_video(self, x: float, y: float) -> tuple[float, float]:
        if not self.preview_pil_orig:
            return 0, 0
        cw = self.preview_canvas.winfo_width() or 600
        ch = self.preview_canvas.winfo_height() or 400
        center_x = cw // 2 + self.canvas_offset[0]
        center_y = ch // 2 + self.canvas_offset[1]
        ow, oh = self.preview_pil_orig.size
        img_x = (x - center_x) / self.preview_zoom + ow / 2
        img_y = (y - center_y) / self.preview_zoom + oh / 2
        return img_x / max(self.preview_scale_x, 1e-6), img_y / max(self.preview_scale_y, 1e-6)

    # ------------------------------------------------------------------ 事件
    def _on_canvas_scroll(self, event):
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self.preview_zoom = max(0.15, min(8.0, self.preview_zoom * factor))
        self._refresh_canvas()

    def _on_canvas_motion(self, event):
        if self._canvas_mode == "person_roi":
            self.preview_canvas.configure(cursor="crosshair")
            return
        if self._canvas_mode == "bubble":
            self.preview_canvas.configure(cursor="fleur")
            return
        if self._hit_bubble(event.x, event.y) is not None:
            self.preview_canvas.configure(cursor="hand2")
        elif self._hit_box(event.x, event.y) is not None:
            self.preview_canvas.configure(cursor="hand2")
        else:
            self.preview_canvas.configure(cursor="crosshair")

    def _on_canvas_drag_start(self, event):
        self.preview_canvas.focus_set()
        self._drag_start = (event.x, event.y)
        self._drag_offset_start = list(self.canvas_offset)
        self._drag_moved = False
        if self._canvas_mode == "person_roi":
            self._roi_start = (event.x, event.y)
            if self._roi_rect_id:
                self.preview_canvas.delete(self._roi_rect_id)
                self._roi_rect_id = None
        elif self._canvas_mode == "bubble":
            self._bubble_drag_tid = self._nearest_box_id(event.x, event.y)
            if self._bubble_drag_tid is not None:
                self.push_undo_state("移動字幕泡泡")
                self._bubble_drag_start_canvas = (event.x, event.y)
                self._bubble_drag_start_offset = self.renderer.bubble_offsets.get(self._bubble_drag_tid, (0, 0))
        else:
            bubble_tid = self._hit_bubble(event.x, event.y)
            if bubble_tid is not None:
                self._canvas_mode = "bubble"
                self.push_undo_state("移動字幕泡泡")
                self._bubble_drag_tid = bubble_tid
                self._bubble_drag_start_canvas = (event.x, event.y)
                self._bubble_drag_start_offset = self.renderer.bubble_offsets.get(bubble_tid, (0, 0))
                self.select_person(bubble_tid)
                self.preview_canvas.configure(cursor="fleur")

    def _on_canvas_drag(self, event):
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        self._drag_moved = self._drag_moved or abs(dx) > 3 or abs(dy) > 3
        if self._canvas_mode == "person_roi":
            if self._roi_rect_id:
                self.preview_canvas.delete(self._roi_rect_id)
            sx, sy = self._roi_start
            self._roi_rect_id = self.preview_canvas.create_rectangle(
                sx, sy, event.x, event.y, outline="#43E2A8", width=2, dash=(6, 3)
            )
        elif self._canvas_mode == "bubble" and self._bubble_drag_tid is not None:
            ox, oy = self._bubble_drag_start_offset
            vx = int((event.x - self._bubble_drag_start_canvas[0]) / max(self.preview_scale_x * self.preview_zoom, 1e-6))
            vy = int((event.y - self._bubble_drag_start_canvas[1]) / max(self.preview_scale_y * self.preview_zoom, 1e-6))
            self.renderer.bubble_offsets[self._bubble_drag_tid] = (ox + vx, oy + vy)
            self.renderer.bubble_cache.clear()
            if hasattr(self, "_drag_preview_after_id"):
                self.after_cancel(self._drag_preview_after_id)
            self._drag_preview_after_id = self.after(30, lambda: self.on_timeline_scrub(self.slider_timeline.get()))
        else:
            self.canvas_offset[0] = self._drag_offset_start[0] + dx
            self.canvas_offset[1] = self._drag_offset_start[1] + dy
            self._refresh_canvas()

    def _on_canvas_release(self, event):
        if self._canvas_mode == "person_roi":
            if self._drag_moved:
                vx1, vy1 = self._canvas_to_video(*self._roi_start)
                vx2, vy2 = self._canvas_to_video(event.x, event.y)
                x1, x2 = sorted((int(vx1), int(vx2)))
                y1, y2 = sorted((int(vy1), int(vy2)))
                if abs(x2 - x1) >= 20 and abs(y2 - y1) >= 20:
                    self.renderer.person_rois.append((max(0, x1), max(0, y1), max(0, x2), max(0, y2)))
                    self.mark_people_count_unconfirmed()
                    self.btn_clear_people.configure(state="normal")
                    self.log(f"已加入人物框 {len(self.renderer.person_rois)}。完成框選後即可掃描。")
            self._canvas_mode = "pan"
            self.btn_draw_people.configure(text="2  框選追踪")
            self._refresh_canvas()
        elif self._canvas_mode == "bubble":
            self._bubble_drag_tid = None
            self._canvas_mode = "pan"
            self.preview_canvas.configure(
                cursor="hand2" if self._hit_bubble(event.x, event.y) is not None else "crosshair"
            )
        elif not self._drag_moved:
            self.on_preview_click(event)

    def _on_canvas_right_click(self, event):
        self.preview_canvas.focus_set()
        tid = self._hit_bubble(event.x, event.y)
        if tid is None:
            tid = self._hit_box(event.x, event.y)
        if tid is None:
            return
        self.assign_current_dialogue_to_person(tid)

    # ------------------------------------------------------------------ 命中測試
    def _nearest_box_id(self, x: float, y: float):
        if not self.preview_boxes:
            return None
        vx, vy = self._canvas_to_video(x, y)
        best_id = None
        best_dist = 1e9
        for box in self.preview_boxes:
            x1, y1, x2, y2 = box["bbox"]
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            dist = abs(vx - cx) + abs(vy - cy)
            if dist < best_dist:
                best_dist = dist
                best_id = box["id"]
        return best_id

    def _hit_bubble(self, x: float, y: float):
        vx, vy = self._canvas_to_video(x, y)
        for tid, rect in self.renderer.bubble_rects.items():
            x1, y1, x2, y2 = rect
            pad = 8
            if x1 - pad <= vx <= x2 + pad and y1 - pad <= vy <= y2 + pad:
                return tid
        return None

    def _hit_box(self, x: float, y: float):
        vx, vy = self._canvas_to_video(x, y)
        for box in self.preview_boxes:
            x1, y1, x2, y2 = box["bbox"]
            if x1 <= vx <= x2 and y1 <= vy <= y2:
                return box["id"]
        for idx, roi in enumerate(self.renderer.person_rois, start=1):
            x1, y1, x2, y2 = roi
            if x1 <= vx <= x2 and y1 <= vy <= y2:
                return idx
        return None

    # ------------------------------------------------------------------ 點擊動作
    def on_preview_click(self, event):
        self.preview_canvas.focus_set()
        tid = self._hit_bubble(event.x, event.y)
        if tid is None:
            tid = self._hit_box(event.x, event.y)
        if tid is not None:
            self.select_person(tid)

    def assign_current_dialogue_to_person(self, tid: int):
        if not self.renderer.data_processor.has_data():
            return
        try:
            frame_idx = int(float(self.slider_timeline.get()))
        except Exception:
            frame_idx = 1
        row_idx = self.selected_dialogue_row
        if row_idx is None:
            row_idx, _ = self.renderer.data_processor.find_dialogue_at_time(frame_idx, self.renderer.fps)
        if row_idx is None:
            self.log("目前時間點沒有可改說話者的對話。")
            return
        speaker = self.renderer.yolo_id_to_speaker.get(int(tid), f"人物 {int(tid)}")
        self.push_undo_state("畫布指定說話者")
        if self.renderer.data_processor.update_dialogue_speaker(row_idx, speaker):
            self.selected_dialogue_row = row_idx
            self.renderer.bubble_cache.clear()
            self._loading_person_fields = True
            self.entry_id.delete(0, "end")
            self.entry_id.insert(0, str(int(tid)))
            self.entry_speaker.delete(0, "end")
            self.entry_speaker.insert(0, speaker)
            _, text = self.renderer.data_processor.get_dialogue_row_values(row_idx)
            self.entry_text.delete(0, "end")
            self.entry_text.insert(0, text)
            self._loading_person_fields = False
            self.log(f"已把目前這句改成 {speaker}。")
            self.refresh_current_preview()

    def select_person(self, tid, allow_time_fallback: bool = True):
        tid = int(tid)
        self._loading_person_fields = True
        self.entry_id.delete(0, "end")
        self.entry_id.insert(0, str(tid))
        speaker = self.renderer.yolo_id_to_speaker.get(tid, "")
        self.entry_speaker.delete(0, "end")
        self.entry_speaker.insert(0, speaker)
        self.selected_dialogue_row = None
        text = ""
        if self.slider_timeline.cget("state") == "normal":
            try:
                frame_idx = int(float(self.slider_timeline.get()))
                row_idx, text = self.renderer.data_processor.find_dialogue_row(frame_idx, self.renderer.fps, tid, speaker)
                if row_idx is None and allow_time_fallback:
                    row_idx, text = self.renderer.data_processor.find_dialogue_at_time(frame_idx, self.renderer.fps)
                self.selected_dialogue_row = row_idx
            except Exception:
                text = ""
        self.entry_text.delete(0, "end")
        self.entry_text.insert(0, text)
        self._loading_person_fields = False
        if self.selected_dialogue_row is None:
            self.log(f"已選取 ID {tid}，目前時間點沒有對應腳本列。")
        else:
            self.log(f"已選取 ID {tid}，正在編輯目前這一句。")

    def refresh_current_preview(self):
        try:
            frame_idx = int(float(self.slider_timeline.get()))
        except Exception:
            return
        self.update_timecode_and_waveform(frame_idx)
        self._render_scrub(frame_idx)
