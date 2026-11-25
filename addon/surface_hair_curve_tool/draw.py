from .i18n import t as ui_t, localized_layout
import math

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils


ORANGE = (1.0, 0.46, 0.0, 1.0)
GREEN = (0.0, 0.85, 0.25, 0.85)
YELLOW = (1.0, 0.95, 0.0, 1.0)
RED = (1.0, 0.08, 0.04, 1.0)
MAGENTA = (1.0, 0.0, 0.75, 1.0)
BLUE = (0.15, 0.45, 1.0, 1.0)
CYAN = (0.0, 0.85, 1.0, 0.95)
WARN = (1.0, 0.86, 0.0, 1.0)
SNAP_CURSOR = (0.0, 0.88, 1.0, 0.95)
FREE_CURSOR = (1.0, 0.48, 0.02, 0.92)
SNAP_MISS_CURSOR = (1.0, 0.82, 0.08, 0.9)
LOCKED_POINT = (0.78, 1.0, 0.08, 0.95)
HUD_BG = (0.025, 0.055, 0.075, 0.52)
HUD_HEADER = (0.0, 0.0, 0.0, 0.0)
HUD_PANEL_LINE = (0.42, 0.82, 1.0, 0.62)
HUD_LABEL = (0.76, 0.91, 1.0, 0.88)
HUD_TEXT = (0.96, 0.99, 1.0, 1.0)
HUD_HINT = (0.72, 0.82, 0.9, 0.72)
HUD_ON = (0.34, 0.78, 1.0, 1.0)
HUD_OFF = (0.5, 0.56, 0.64, 0.95)
HUD_WARN = (1.0, 0.78, 0.22, 1.0)
HUD_SHADOW = (0.0, 0.0, 0.0, 0.18)
HUD_ROW = (0.44, 0.78, 1.0, 0.18)
HUD_BORDER = (0.0, 0.0, 0.0, 0.0)
MODE_HUD_CELL = (0.0, 0.0, 0.0, 0.52)
MODE_HUD_ACTIVE = (0.0, 0.0, 0.0, 0.66)
MODE_HUD_HOVER = (0.0, 0.0, 0.0, 0.82)
MODE_HUD_GLOW = (1.0, 1.0, 1.0, 0.16)
MODE_HUD_HOVER_GLOW = (1.0, 1.0, 1.0, 0.38)

TOOL_LABELS = {
    "DRAW": "绘制",
    "SELECT": "选择",
    "DUPLICATE": "复制",
    "CONTROL": "编辑",
    "INTERPOLATE": "插值",
}

DRAW_LABELS = {
    "CLICK": "单击点",
    "PAINT": "按住绘制",
}

SNAP_LABELS = {
    "AUTO": "自动",
    "VERTEX": "点",
    "EDGE": "边",
    "FACE": "面",
    "NONE": "未吸附",
}


def color_with_alpha(color, alpha_mul):
    return (color[0], color[1], color[2], max(0.0, min(1.0, color[3] * alpha_mul)))


def bool_label(value):
    return "开" if value else "关"


def state_color(value):
    return HUD_ON if value else HUD_OFF


class OverlayDrawManager:
    def __init__(self, operator):
        self.operator = operator
        self.shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    def draw_3d(self):
        op = self.operator
        state = getattr(op, "overlay_state", None) or {}
        if not getattr(op, "running", False):
            return
        try:
            gpu.state.blend_set("ALPHA")
            gpu.state.depth_test_set("NONE" if state.get("xray", True) else "LESS_EQUAL")
            gpu.state.depth_mask_set(False)
            self._draw_registered_curves()
            self._draw_current_stroke()
            self._draw_snap_marker()
            self._draw_warning_points()
        finally:
            self._restore_gpu()

    def draw_2d(self, context):
        op = self.operator
        if not getattr(op, "running", False):
            return
        try:
            gpu.state.blend_set("ALPHA")
            self._draw_brush_ring()
            self._draw_guide_selection_overlay()
            self._draw_mouse_target_marker()
            self._draw_point_markers_2d(context)
            self._draw_status_text(context)
        finally:
            self._restore_gpu()

    def _restore_gpu(self):
        gpu.state.depth_test_set("NONE")
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set("NONE")
        gpu.state.line_width_set(1.0)
        gpu.state.point_size_set(1.0)

    def _draw_line_strip(self, points, color, width):
        if len(points) < 2:
            return
        gpu.state.line_width_set(width)
        batch = batch_for_shader(self.shader, "LINE_STRIP", {"pos": points})
        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def _draw_lines(self, points, color, width):
        if len(points) < 2:
            return
        gpu.state.line_width_set(width)
        batch = batch_for_shader(self.shader, "LINES", {"pos": points})
        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def _fit_text(self, text, max_width, font_id=0):
        text = str(text or "")
        if max_width <= 0:
            return ""
        if blf.dimensions(font_id, text)[0] <= max_width:
            return text
        ellipsis = "..."
        if blf.dimensions(font_id, ellipsis)[0] > max_width:
            return ""
        clipped = text
        while clipped and blf.dimensions(font_id, clipped + ellipsis)[0] > max_width:
            clipped = clipped[:-1]
        return clipped + ellipsis if clipped else ellipsis

    def _draw_fit_text(self, text, x, y, max_width, color, font_id=0):
        blf.color(font_id, *color)
        blf.position(font_id, x, y, 0)
        blf.draw(font_id, ui_t(self._fit_text(text, max_width, font_id)))

    def _draw_rect_2d(self, x, y, width, height, color):
        points = [
            (x, y, 0.0),
            (x + width, y, 0.0),
            (x + width, y + height, 0.0),
            (x, y, 0.0),
            (x + width, y + height, 0.0),
            (x, y + height, 0.0),
        ]
        batch = batch_for_shader(self.shader, "TRIS", {"pos": points})
        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def _draw_disc_2d(self, x, y, radius, color, segments=32):
        radius = max(0.5, float(radius))
        segments = max(12, int(segments))
        points = []
        for index in range(segments):
            angle_a = math.tau * index / segments
            angle_b = math.tau * (index + 1) / segments
            points.extend(
                [
                    (x, y, 0.0),
                    (x + math.cos(angle_a) * radius, y + math.sin(angle_a) * radius, 0.0),
                    (x + math.cos(angle_b) * radius, y + math.sin(angle_b) * radius, 0.0),
                ]
            )
        batch = batch_for_shader(self.shader, "TRIS", {"pos": points})
        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def _rounded_rect_points(self, x, y, width, height, radius, segments=8):
        radius = max(0.0, min(float(radius), width * 0.5, height * 0.5))
        segments = max(2, int(segments))
        if radius <= 0.0:
            return [
                (x, y),
                (x + width, y),
                (x + width, y + height),
                (x, y + height),
            ]
        corners = [
            (x + width - radius, y + height - radius, 0.0),
            (x + radius, y + height - radius, math.pi * 0.5),
            (x + radius, y + radius, math.pi),
            (x + width - radius, y + radius, math.pi * 1.5),
        ]
        points = []
        for cx, cy, start_angle in corners:
            for step in range(segments + 1):
                angle = start_angle + (math.pi * 0.5) * step / segments
                points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
        return points

    def _draw_round_rect_2d(self, x, y, width, height, radius, color, segments=8):
        outline = self._rounded_rect_points(x, y, width, height, radius, segments)
        if len(outline) < 3:
            return
        center = (x + width * 0.5, y + height * 0.5, 0.0)
        points = []
        for index, point in enumerate(outline):
            next_point = outline[(index + 1) % len(outline)]
            points.extend(
                [
                    center,
                    (point[0], point[1], 0.0),
                    (next_point[0], next_point[1], 0.0),
                ]
            )
        batch = batch_for_shader(self.shader, "TRIS", {"pos": points})
        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def _draw_points(self, points, color, size):
        if not points:
            return
        gpu.state.point_size_set(size)
        batch = batch_for_shader(self.shader, "POINTS", {"pos": points})
        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def _draw_batched_lines(self, groups):
        for key, points in groups.items():
            if len(points) < 2:
                continue
            color, width = key
            self._draw_lines(points, color, width)

    def _draw_batched_points(self, groups):
        for key, points in groups.items():
            if not points:
                continue
            color, size = key
            self._draw_points(points, color, size)

    def _add_points_to_group(self, groups, color, size, points):
        if not points:
            return
        key = (tuple(color), round(float(size), 3))
        groups.setdefault(key, []).extend(points)

    def _add_line_segments_to_group(self, groups, color, width, points):
        if len(points) < 2:
            return
        key = (tuple(color), round(float(width), 3))
        target = groups.setdefault(key, [])
        for index in range(len(points) - 1):
            target.append(points[index])
            target.append(points[index + 1])

    def _point_to_vector(self, point):
        try:
            return Vector((float(point.x), float(point.y), float(point.z)))
        except Exception:
            try:
                return Vector((float(point[0]), float(point[1]), float(point[2])))
            except Exception:
                return None

    def _draw_point_marker_2d(self, context, point, color, size):
        region = getattr(context, "region", None)
        region_data = getattr(context, "region_data", None)
        if not region or not region_data:
            return
        vector = self._point_to_vector(point)
        if vector is None:
            return
        screen = view3d_utils.location_3d_to_region_2d(region, region_data, vector)
        if not screen:
            return
        radius = max(3.0, float(size) * 0.5)
        shadow_alpha = min(0.58, color[3] * 0.7)
        self._draw_disc_2d(screen.x + 1.0, screen.y - 1.0, radius + 2.0, (0.0, 0.0, 0.0, shadow_alpha), 32)
        self._draw_disc_2d(screen.x, screen.y, radius + 1.0, (0.95, 0.98, 1.0, min(0.95, color[3] * 0.92)), 32)
        self._draw_disc_2d(screen.x, screen.y, radius - 1.0, color, 32)

    def _draw_control_points_2d(self, context, points, selected_curve=False, hovered=False, point_size=None, locked_indices=None):
        if not points:
            return
        op = self.operator
        locked_indices = set(locked_indices or [])
        if point_size is None:
            point_size = (getattr(op, "overlay_state", None) or {}).get("point_size", 12.0)
        point_size = point_size + (3.0 if selected_curve else 0.0)
        if len(points) == 1:
            self._draw_point_marker_2d(context, points[0], RED, point_size)
            if 0 in locked_indices:
                self._draw_point_marker_2d(context, points[0], LOCKED_POINT, point_size + 5.0)
            if hovered and getattr(op, "hover_kind", "") == "POINT" and int(getattr(op, "hover_point_index", -1)) == 0:
                self._draw_point_marker_2d(context, points[0], YELLOW, point_size + 7.0)
            return
        self._draw_point_marker_2d(context, points[0], RED, point_size + 1.0)
        if len(points) > 2:
            middle_color = CYAN if hovered else BLUE
            for point in points[1:-1]:
                self._draw_point_marker_2d(context, point, middle_color, point_size)
        self._draw_point_marker_2d(context, points[-1], MAGENTA, point_size + 1.0)
        locked_points = [point for idx, point in enumerate(points) if idx in locked_indices]
        for point in locked_points:
            self._draw_point_marker_2d(context, point, LOCKED_POINT, point_size + 5.0)
        hover_index = int(getattr(op, "hover_point_index", -1))
        if hovered and getattr(op, "hover_kind", "") == "POINT" and 0 <= hover_index < len(points):
            self._draw_point_marker_2d(context, points[hover_index], YELLOW, point_size + 7.0)

    def _draw_point_markers_2d(self, context):
        op = self.operator
        state = getattr(op, "overlay_state", None) or {}
        point_size = state.get("point_size", 12.0)
        show_control_points = state.get("show_control_points", True)
        fast_mode = bool(state.get("overlay_fast_mode", True))
        if show_control_points:
            for item in getattr(op, "overlay_curves", []) or []:
                if item.get("show_control_points", False):
                    if fast_mode and not (item.get("selected", False) or item.get("hovered", False)):
                        continue
                    self._draw_control_points_2d(
                        context,
                        item.get("display_control_points") or item.get("control_points") or [],
                        item.get("selected", False),
                        item.get("hovered", False),
                        item.get("point_size"),
                        item.get("locked_point_indices"),
                    )
            for controls in getattr(op, "interpolate_preview_controls", []) or []:
                for point in controls:
                    self._draw_point_marker_2d(context, point, (0.0, 0.86, 1.0, 0.78), max(5.0, point_size * 0.5))
            for controls in getattr(op, "duplicate_preview_controls", []) or []:
                for point in controls:
                    self._draw_point_marker_2d(context, point, (1.0, 0.84, 0.12, 0.72), max(5.0, point_size * 0.55))
            self._draw_hover_handle_marker_2d(context)
        pts = op.preview_points if op.preview_points else op.current_points
        if pts:
            locked_indices = []
            if len(pts) >= 2:
                locked_indices = getattr(op, "locked_point_indices_for_count", lambda _count: [])(len(pts))
            self._draw_control_points_2d(context, pts, True, False, point_size, locked_indices)
        if op.drag_point is not None:
            self._draw_point_marker_2d(context, op.drag_point, YELLOW, point_size + 8.0)
        if op.ik_mode:
            for data in op.ik_influence_points:
                if len(data) >= 1:
                    self._draw_point_marker_2d(context, data[0], (0.7, 1.0, 0.05, 0.85), point_size + 2.0)
        for point in op.warning_points or []:
            self._draw_point_marker_2d(context, point, WARN, point_size + 6.0)
        if op.snap_result and op.snap_result.hit and op.snap_result.location:
            color = CYAN if op.snap_result.element != "NONE" else WARN
            self._draw_point_marker_2d(context, op.snap_result.location, color, point_size + 4.0)

    def _draw_hover_handle_marker_2d(self, context):
        op = self.operator
        if getattr(op, "hover_kind", "") != "HANDLE":
            return
        hover_curve_id = str(getattr(op, "hover_curve_id", ""))
        hover_index = int(getattr(op, "hover_point_index", -1))
        hover_side = str(getattr(op, "hover_handle_side", ""))
        if not hover_curve_id or hover_index < 0 or not hover_side:
            return
        state = getattr(op, "overlay_state", None) or {}
        point_size = state.get("point_size", 12.0)
        for item in getattr(op, "overlay_curves", []) or []:
            if str(item.get("curve_id", "")) != hover_curve_id:
                continue
            for handle in item.get("handle_data") or []:
                if int(handle.get("index", -1)) == hover_index and str(handle.get("side", "")) == hover_side:
                    self._draw_point_marker_2d(context, handle.get("point"), YELLOW, point_size + 6.0)
                    return

    def _draw_registered_curves(self):
        op = self.operator
        line_groups = {}
        point_groups = {}
        handle_line_groups = {}
        handle_point_groups = {}
        for item in getattr(op, "overlay_curves", []) or []:
            points = item.get("points") or []
            if len(points) < 2:
                continue
            self._add_line_segments_to_group(line_groups, item.get("color", GREEN), item.get("width", 4.0), points)
            if item.get("show_control_points", False):
                self._add_control_points_to_groups(
                    point_groups,
                    item.get("display_control_points") or item.get("control_points") or [],
                    item.get("selected", False),
                    item.get("hovered", False),
                    item.get("point_size"),
                    item.get("locked_point_indices"),
                )
            if item.get("show_handles", False):
                handle_lines = item.get("handle_lines") or []
                handle_points = item.get("handle_points") or []
                if handle_lines:
                    self._add_line_segments_to_group(handle_line_groups, (1.0, 0.82, 0.15, 0.42), 1.25, handle_lines)
                if handle_points:
                    self._add_points_to_group(
                        handle_point_groups,
                        (1.0, 0.86, 0.0, 0.8),
                        max(3.0, item.get("point_size", 8.0) * 0.72),
                        handle_points,
                    )
        self._draw_batched_lines(line_groups)
        self._draw_batched_lines(handle_line_groups)
        self._draw_batched_points(point_groups)
        self._draw_batched_points(handle_point_groups)

    def _add_control_points_to_groups(self, groups, points, selected_curve=False, hovered=False, point_size=None, locked_indices=None):
        if not points:
            return
        locked_indices = set(locked_indices or [])
        if point_size is None:
            point_size = (getattr(self.operator, "overlay_state", None) or {}).get("point_size", 12.0)
        point_size = point_size + (3.0 if selected_curve else 0.0)
        if len(points) == 1:
            self._add_points_to_group(groups, RED, point_size, points)
            if 0 in locked_indices:
                self._add_points_to_group(groups, LOCKED_POINT, point_size + 4.0, points)
            return
        self._add_points_to_group(groups, RED, point_size + 1.0, [points[0]])
        if len(points) > 2:
            self._add_points_to_group(groups, BLUE if not hovered else CYAN, point_size, points[1:-1])
        self._add_points_to_group(groups, MAGENTA, point_size + 1.0, [points[-1]])
        locked_points = [point for idx, point in enumerate(points) if idx in locked_indices]
        if locked_points:
            self._add_points_to_group(groups, LOCKED_POINT, point_size + 4.0, locked_points)

    def _draw_control_points(self, points, selected_curve=False, hovered=False, point_size=None, locked_indices=None):
        if not points:
            return
        locked_indices = set(locked_indices or [])
        if point_size is None:
            point_size = (getattr(self.operator, "overlay_state", None) or {}).get("point_size", 12.0)
        point_size = point_size + (3.0 if selected_curve else 0.0)
        if len(points) == 1:
            self._draw_points(points, RED, point_size)
            if 0 in locked_indices:
                self._draw_points(points, LOCKED_POINT, point_size + 4.0)
            return
        self._draw_points([points[0]], RED, point_size + 1.0)
        if len(points) > 2:
            self._draw_points(points[1:-1], BLUE if not hovered else CYAN, point_size)
        self._draw_points([points[-1]], MAGENTA, point_size + 1.0)
        locked_points = [point for idx, point in enumerate(points) if idx in locked_indices]
        if locked_points:
            self._draw_points(locked_points, LOCKED_POINT, point_size + 4.0)

    def _draw_current_stroke(self):
        op = self.operator
        state = getattr(op, "overlay_state", None) or {}
        line_width = state.get("line_width", 6.0)
        point_size = state.get("point_size", 12.0)
        show_control_points = state.get("show_control_points", True)
        show_handles = state.get("show_handles", False)
        if op.interpolate_preview:
            control_sets = getattr(op, "interpolate_preview_controls", []) or []
            for idx, points in enumerate(op.interpolate_preview):
                factor = 0.55 + 0.35 * ((idx % 3) / 2.0)
                self._draw_line_strip(points, (0.0, 0.95, factor, 0.86), line_width + 1.0)
                if show_control_points:
                    controls = control_sets[idx] if idx < len(control_sets) else points
                    self._draw_points(controls, (0.0, 0.8, 1.0, 0.62), max(4.0, point_size * 0.55))
        if getattr(op, "duplicate_preview", None):
            control_sets = getattr(op, "duplicate_preview_controls", []) or []
            for idx, points in enumerate(op.duplicate_preview):
                self._draw_line_strip(points, (1.0, 0.78, 0.08, 0.82), line_width + 1.0)
                if show_control_points:
                    controls = control_sets[idx] if idx < len(control_sets) else points
                    self._draw_points(controls, (1.0, 0.84, 0.12, 0.68), max(4.0, point_size * 0.58))
        pts = op.preview_points if op.preview_points else op.current_points
        if len(pts) >= 2:
            self._draw_line_strip(pts, ORANGE, line_width + 2.0)
            if show_control_points:
                locked_indices = getattr(op, "locked_point_indices_for_count", lambda _count: [])(len(pts))
                self._draw_control_points(pts, True, False, point_size, locked_indices)
        if op.drag_preview:
            self._draw_line_strip(op.drag_preview, ORANGE, line_width + 2.0)
            if show_handles and op.drag_handle_lines:
                self._draw_lines(op.drag_handle_lines, (1.0, 0.92, 0.18, 0.55), 1.5)
            if op.ik_mode:
                influenced = [data[0] for data in op.ik_influence_points if len(data) >= 1]
                if influenced:
                    self._draw_points(influenced, (0.7, 1.0, 0.05, 0.85), point_size + 2.0)
                if op.drag_point is not None:
                    self._draw_points([op.drag_point], YELLOW, point_size + 8.0)
            elif op.drag_point is not None:
                self._draw_points([op.drag_point], YELLOW, point_size + 7.0)

    def _draw_snap_marker(self):
        op = self.operator
        if op.snap_result and op.snap_result.hit and op.snap_result.location:
            loc = op.snap_result.location
            state = getattr(op, "overlay_state", None) or {}
            size = state.get("point_size", 12.0) + 4.0
            color = CYAN if op.snap_result.element != "NONE" else WARN
            self._draw_points([loc], color, size)
            normal = op.snap_result.normal or Vector((0, 0, 1))
            self._draw_lines([loc, loc + normal * 0.035], color_with_alpha(color, 0.65), 1.5)

    def _draw_warning_points(self):
        op = self.operator
        if op.warning_points:
            state = getattr(op, "overlay_state", None) or {}
            self._draw_points(op.warning_points, WARN, state.get("point_size", 12.0) + 6.0)

    def _draw_brush_ring(self):
        op = self.operator
        state = getattr(op, "overlay_state", None) or {}
        if not op.mouse_region_pos:
            return
        x, y = op.mouse_region_pos
        radius = state.get("brush_radius", 28.0)
        segments = 64
        points = []
        for i in range(segments + 1):
            angle = (math.tau * i) / segments
            points.append((x + math.cos(angle) * radius, y + math.sin(angle) * radius, 0.0))
        gpu.state.line_width_set(2.0)
        batch = batch_for_shader(self.shader, "LINE_STRIP", {"pos": points})
        self.shader.bind()
        tool = state.get("tool", "DRAW")
        snap_enabled = bool(state.get("snap_enabled", True))
        snap_hit = bool(op.snap_result and op.snap_result.hit)
        color = (1.0, 0.55, 0.0, 0.78) if tool == "DRAW" else (1.0, 1.0, 0.0, 0.62)
        if tool == "DRAW":
            color = color_with_alpha(SNAP_CURSOR, 0.74) if snap_enabled else color_with_alpha(FREE_CURSOR, 0.74)
            if snap_enabled and not snap_hit:
                color = color_with_alpha(SNAP_MISS_CURSOR, 0.68)
        if tool == "INTERPOLATE":
            color = (0.0, 0.9, 1.0, 0.52)
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def _draw_mouse_target_marker(self):
        op = self.operator
        state = getattr(op, "overlay_state", None) or {}
        if getattr(op, "guide_select_mode", ""):
            return
        if state.get("tool", "DRAW") != "DRAW" or not op.mouse_region_pos:
            return
        x, y = op.mouse_region_pos
        snap_enabled = bool(state.get("snap_enabled", True))
        snap_hit = bool(op.snap_result and op.snap_result.hit)
        if snap_enabled:
            color = SNAP_CURSOR if snap_hit else SNAP_MISS_CURSOR
            radius = 4.4 if snap_hit else 3.8
        else:
            color = FREE_CURSOR
            radius = 4.6
        self._draw_disc_2d(x + 1.0, y - 1.0, radius + 2.2, (0.0, 0.0, 0.0, 0.36), 24)
        self._draw_disc_2d(x, y, radius + 1.0, (0.96, 0.99, 1.0, 0.68), 24)
        self._draw_disc_2d(x, y, radius, color, 24)
        if snap_enabled:
            tick = 7.0 if snap_hit else 6.0
            gap = 3.0
            self._draw_lines(
                [
                    (x - tick, y, 0.0),
                    (x - gap, y, 0.0),
                    (x + gap, y, 0.0),
                    (x + tick, y, 0.0),
                    (x, y - tick, 0.0),
                    (x, y - gap, 0.0),
                    (x, y + gap, 0.0),
                    (x, y + tick, 0.0),
                ],
                color_with_alpha(color, 0.86),
                1.2,
            )
        else:
            self._draw_lines(
                [
                    (x - 5.5, y - 5.5, 0.0),
                    (x + 5.5, y + 5.5, 0.0),
                    (x - 5.5, y + 5.5, 0.0),
                    (x + 5.5, y - 5.5, 0.0),
                ],
                color_with_alpha(color, 0.75),
                1.15,
            )

    def _draw_guide_selection_overlay(self):
        op = self.operator
        mode = getattr(op, "guide_select_mode", "")
        if not mode:
            return
        current = getattr(op, "guide_select_current", None) or getattr(op, "mouse_region_pos", None)
        if not current:
            return
        x, y = current
        if mode == "BRUSH":
            radius = (getattr(op, "overlay_state", None) or {}).get("brush_radius", 28.0)
            self._draw_disc_2d(x, y, radius, (0.16, 0.72, 1.0, 0.12), 48)
            segments = 64
            points = []
            for index in range(segments + 1):
                angle = math.tau * index / segments
                points.append((x + math.cos(angle) * radius, y + math.sin(angle) * radius, 0.0))
            self._draw_lines(points, (0.36, 0.9, 1.0, 0.9), 1.5)
            return
        if mode == "BOX":
            anchor = getattr(op, "guide_select_anchor", current)
            ax, ay = anchor
            xmin, xmax = sorted((float(ax), float(x)))
            ymin, ymax = sorted((float(ay), float(y)))
            width = max(1.0, xmax - xmin)
            height = max(1.0, ymax - ymin)
            self._draw_rect_2d(xmin, ymin, width, height, (0.14, 0.68, 1.0, 0.14))
            points = [
                (xmin, ymin, 0.0),
                (xmax, ymin, 0.0),
                (xmax, ymin, 0.0),
                (xmax, ymax, 0.0),
                (xmax, ymax, 0.0),
                (xmin, ymax, 0.0),
                (xmin, ymax, 0.0),
                (xmin, ymin, 0.0),
            ]
            self._draw_lines(points, (0.36, 0.9, 1.0, 0.92), 1.5)

    def _draw_status_text(self, context):
        if getattr(self.operator, "mode_hud_active", False):
            self._draw_mode_switch_hud(context)
            return
        state = getattr(self.operator, "overlay_state", None) or {}
        if not state.get("show_hud", True):
            return
        self._draw_modal_hud(context)

    def _mode_hud_items(self, center_x, center_y, cell, gap):
        offset = cell + gap
        return [
            ("DRAW", "绘制", center_x - cell * 0.5, center_y + offset - cell * 0.5),
            ("CONTROL", "编辑", center_x + offset - cell * 0.5, center_y - cell * 0.5),
            ("INTERPOLATE", "插值", center_x - offset - cell * 0.5, center_y - cell * 0.5),
            ("SELECT", "选择", center_x - cell * 0.5, center_y - offset - cell * 0.5),
        ]

    def _draw_mode_switch_hud(self, context):
        op = self.operator
        if not getattr(op, "mode_hud_anchor", None):
            return
        ax, ay = op.mode_hud_anchor
        center_x = max(110.0, min(float(ax), context.region.width - 110.0))
        center_y = max(110.0, min(float(ay), context.region.height - 110.0))
        cell = 68.0
        gap = 16.0
        active_tool = (getattr(op, "overlay_state", None) or {}).get("tool", "DRAW")
        hover_tool = getattr(op, "mode_hud_hover", "") or active_tool

        font_id = 0
        for tool, label, x, y in self._mode_hud_items(center_x, center_y, cell, gap):
            is_hover = tool == hover_tool
            is_active = tool == active_tool
            bg = MODE_HUD_HOVER if is_hover else MODE_HUD_ACTIVE if is_active else MODE_HUD_CELL
            glow = MODE_HUD_HOVER_GLOW if is_hover else MODE_HUD_GLOW if is_active else (1.0, 1.0, 1.0, 0.08)
            if is_hover:
                self._draw_round_rect_2d(x - 7, y - 7, cell + 14, cell + 14, 16, (1.0, 1.0, 1.0, 0.08), 10)
                self._draw_round_rect_2d(x - 4, y - 4, cell + 8, cell + 8, 14, glow, 10)
            elif is_active:
                self._draw_round_rect_2d(x - 3, y - 3, cell + 6, cell + 6, 13, glow, 10)
            self._draw_round_rect_2d(x + 2, y - 2, cell, cell, 12, HUD_SHADOW, 10)
            self._draw_round_rect_2d(x, y, cell, cell, 12, bg, 10)
            blf.size(font_id, 15 if not is_hover else 16)
            blf.color(font_id, 1.0, 1.0, 1.0, 1.0 if is_hover else 0.82)
            text_width, _text_height = blf.dimensions(font_id, label)
            blf.position(font_id, x + (cell - text_width) * 0.5, y + 27, 0)
            blf.draw(font_id, ui_t(label))

    def _hud_rows(self):
        op = self.operator
        state = getattr(op, "overlay_state", None) or {}
        shortcuts = state.get("shortcuts", {}) or {}
        tool_key = state.get("tool", "DRAW")
        draw_mode_key = state.get("draw_mode", "CLICK")
        snap_element = state.get("snap_element", "AUTO")
        snap_enabled = state.get("snap_enabled", True)
        scalp_enabled = state.get("scalp_root_snap", False)
        scalp_name = state.get("scalp_name", "未选")
        shrink_strength = state.get("shrink_strength", 0.18)
        shrink_tail = max(1, int(state.get("shrink_tail_fixed_points", 1)))
        smooth_strength = state.get("smooth_strength", 0.55)
        smooth_surface_lock = state.get("smooth_surface_lock", True)
        tool = TOOL_LABELS.get(tool_key, tool_key)
        draw_mode = DRAW_LABELS.get(draw_mode_key, draw_mode_key)
        snap = f"{bool_label(snap_enabled)} / {SNAP_LABELS.get(snap_element, snap_element)}"
        count = f"已点 {len(op.current_points)}，右键完成"
        if tool_key == "INTERPOLATE":
            preview_count = len(op.interpolate_preview) if op.interpolate_preview else 0
            count = f"预览 {preview_count} 条"
        group_name = state.get("group_name", "无")
        group_state = state.get("group_state", "")
        status = state.get("live_status", "就绪") or "就绪"
        ik_enabled = state.get("ik_enabled", True)
        ik_snap_enabled = state.get("ik_snap", True)
        ik_mode = bool_label(ik_enabled)
        ik_snap = bool_label(ik_snap_enabled)
        draw_hint = f"左键加点  右键完成  {shortcuts.get('toggle_paint', 'P')}"
        if tool_key == "INTERPOLATE":
            draw_hint = f"{shortcuts.get('increase', '+')}/{shortcuts.get('decrease', '-')} 点数  Ctrl+同键条数"
        mode_hint = " ".join(
            label
            for label in (
                shortcuts.get("draw_tool", "D"),
                shortcuts.get("control_tool", "E"),
                shortcuts.get("control_tool_alt", "G"),
                shortcuts.get("interpolate_tool", "L"),
                shortcuts.get("select_tool", "A"),
                shortcuts.get("cycle_tool", "Tab"),
            )
            if label and label != "未绑定"
        )
        return [
            ("模式", f"{tool}/{draw_mode}", mode_hint, HUD_TEXT),
            ("绘制", count, draw_hint, HUD_TEXT),
            ("吸附", snap, f"{shortcuts.get('toggle_snap', 'S')}  {shortcuts.get('snap_cycle', 'Ctrl+滚轮')}", state_color(snap_enabled)),
            ("头皮", f"根吸{bool_label(scalp_enabled)}  收缩{shrink_strength:.2f} 尾固{shrink_tail}", f"{shortcuts.get('shrink_strength', 'Ctrl+Shift+滚轮')} / {shortcuts.get('shrink_tail', 'Alt+Shift+滚轮')}", state_color(scalp_enabled)),
            ("IK", f"模式{ik_mode} 吸附{ik_snap} 点数{state.get('ik_falloff_points', 3)}", f"{shortcuts.get('toggle_ik', 'I')} {shortcuts.get('toggle_ik_snap', 'Ctrl+I')} PgUp/Dn", state_color(ik_enabled and ik_snap_enabled)),
            ("贴面", f"贴面{bool_label(state.get('surface_lock', True))} 发根{bool_label(state.get('root_lock', True))}", f"{shortcuts.get('toggle_surface_lock', 'K')} {shortcuts.get('toggle_root_lock', 'R')}", state_color(state.get("surface_lock", True))),
            ("编辑", f"平滑{smooth_strength:.2f} 贴面{bool_label(smooth_surface_lock)}", f"{shortcuts.get('smooth_strength', 'Shift+滚轮')}  Shift尾 Ctrl+Shift尾", state_color(smooth_surface_lock)),
            ("插值", f"{state.get('interpolate_count', 3)} 条  {state.get('interpolate_point_count', 8)} 点", "左键选导引 右键确认", HUD_ON if tool_key == "INTERPOLATE" else HUD_TEXT),
            ("组", f"{group_name}{group_state}", f"{shortcuts.get('group_cycle', 'Alt+滚轮')} {shortcuts.get('add_group', 'Ctrl+G')} 合并/发丝", HUD_WARN if group_state else HUD_TEXT),
            ("显示", f"X-Ray {bool_label(state.get('xray', True))}  {status}", f"{shortcuts.get('toggle_xray', 'Alt+Z')} Enter H", state_color(state.get("xray", True))),
        ]

    def _draw_modal_hud(self, context):
        op = self.operator
        font_id = 0
        available_width = max(220, context.region.width - 36)
        width = max(220, min(390, available_width))
        row_height = 19
        rows = self._hud_rows()
        height = row_height * len(rows) + 38
        if op.mouse_region_pos:
            mx, my = op.mouse_region_pos
        else:
            mx, my = (24, context.region.height * 0.5)
        x = mx + 18
        y_top = my + height + 14
        if x + width > context.region.width - 16:
            x = mx - width - 18
        if y_top > context.region.height - 18:
            y_top = my - 18
        x = max(12, min(x, context.region.width - width - 12))
        y_top = max(height + 16, min(y_top, context.region.height - 18))
        y_bottom = y_top - height
        panel_x = x - 10
        panel_y = y_bottom - 7
        panel_width = width + 20
        panel_height = height + 12
        panel_radius = 8
        self._draw_round_rect_2d(panel_x + 3, panel_y - 3, panel_width, panel_height, panel_radius, HUD_SHADOW, 10)
        self._draw_round_rect_2d(panel_x, panel_y, panel_width, panel_height, panel_radius, HUD_BG, 10)
        self._draw_disc_2d(x + 6, y_top - 19, 3.2, HUD_PANEL_LINE, 18)
        self._draw_lines([(x + 16, y_top - 17, 0.0), (x + width * 0.52, y_top - 17, 0.0)], HUD_PANEL_LINE, 1.2)
        blf.size(font_id, 13)
        self._draw_fit_text("表面头发曲线", x + 18, y_top - 23, width - 28, (0.92, 0.98, 1.0, 0.95), font_id)
        blf.size(font_id, 11)
        label_x = x + 10
        value_x = x + 58
        hint_x = x + 238
        label_width = 40
        value_width = max(110, hint_x - value_x - 12)
        hint_width = max(64, x + width - hint_x)
        line_start = value_x
        line_end = min(x + width * 0.58, hint_x - 12)
        y = y_top - 45
        for row_index, row_data in enumerate(rows):
            label, value, hint = row_data[:3]
            value_color = row_data[3] if len(row_data) > 3 else HUD_TEXT
            dot_color = value_color if row_index % 2 == 0 else HUD_PANEL_LINE
            self._draw_disc_2d(x - 1, y + 4, 2.5, dot_color, 14)
            self._draw_lines([(line_start, y - 4, 0.0), (line_end, y - 4, 0.0)], HUD_ROW, 1.0)
            self._draw_fit_text(label, label_x, y, label_width, HUD_LABEL, font_id)
            self._draw_fit_text(value, value_x, y, value_width, value_color, font_id)
            self._draw_fit_text(hint, hint_x, y, hint_width, HUD_HINT, font_id)
            y -= row_height
        if op.ik_mode and op.drag_point is not None:
            screen = view3d_utils.location_3d_to_region_2d(
                context.region,
                context.region_data,
                op.drag_point,
            )
            if screen:
                blf.size(font_id, 16)
                blf.color(font_id, 1.0, 0.95, 0.0, 1.0)
                blf.position(font_id, screen.x + 12, screen.y + 12, 0)
                blf.draw(font_id, ui_t("IK 链式吸附"))


def draw_callback_3d(operator):
    try:
        if operator and operator.draw_manager:
            operator.draw_manager.draw_3d()
    except Exception:
        return


def draw_callback_2d(operator):
    try:
        if operator and operator.draw_manager:
            operator.draw_manager.draw_2d(bpy.context)
    except Exception:
        return
