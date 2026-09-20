"""Validated client-relative regions for CPU-only visual processing.

ROIs reduce work on the CPU without becoming action coordinates.  They are
resolved against the dimensions of each current captured client frame; a
window with an implausible aspect ratio is rejected instead of silently
distorting a trained region.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


class CpuRoiError(ValueError):
    """The CPU ROI profile or current frame geometry is invalid."""


@dataclass(frozen=True)
class RoiRect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in (self.x, self.y, self.width, self.height)):
            raise CpuRoiError("ROI coordinates and dimensions must be integers")
        if self.x < 0 or self.y < 0 or self.width < 1 or self.height < 1:
            raise CpuRoiError("ROI coordinates must be non-negative and dimensions positive")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]


@dataclass(frozen=True)
class ResolvedRoi:
    roi_id: str
    rect: RoiRect
    source_client_size: tuple[int, int]
    reference_client_size: tuple[int, int]
    #: How much to magnify this region before OCR.  Measured per region, not
    #: chosen globally: a well-framed strip reads correctly at 1 and gets
    #: WORSE at 3, while a tight region reads nothing until 4.  See
    #: harness/windows_ocr_direct.recognize_frame for the numbers.
    ocr_scale: float = 1.0


@dataclass(frozen=True)
class CpuRoiProfile:
    profile_id: str
    reference_client_size: tuple[int, int]
    aspect_ratio_tolerance: float
    regions: Mapping[str, RoiRect]
    processing_backend: Mapping[str, Any]
    #: Per-region OCR magnification, defaulting to 1.0 for regions that are
    #: visual-only or that read correctly unscaled.
    ocr_scales: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "CpuRoiProfile":
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dependency contract
            raise CpuRoiError("PyYAML is required to load the CPU ROI profile") from exc

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
            raise CpuRoiError("CPU ROI profile must use schema_version=1")
        profile_id = raw.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise CpuRoiError("CPU ROI profile_id is required")
        reference = raw.get("reference_client_size")
        if (
            not isinstance(reference, list)
            or len(reference) != 2
            or any(type(value) is not int or value < 1 for value in reference)
        ):
            raise CpuRoiError("reference_client_size must be [positive width, positive height]")
        tolerance = raw.get("aspect_ratio_tolerance", 0.02)
        if type(tolerance) not in (int, float) or not 0.0 <= float(tolerance) <= 0.25:
            raise CpuRoiError("aspect_ratio_tolerance must be within [0, 0.25]")
        coordinate_space = raw.get("coordinate_space")
        if coordinate_space != "client_pixels_reference":
            raise CpuRoiError("CPU ROI profile must use client_pixels_reference coordinates")
        backend = raw.get("processing_backend")
        if not isinstance(backend, Mapping):
            raise CpuRoiError("processing_backend is required")
        if backend.get("device") != "cpu" or backend.get("allow_opencl") is not False or backend.get("allow_cuda") is not False:
            raise CpuRoiError("CPU ROI profile must explicitly disable OpenCL and CUDA")
        raw_regions = raw.get("regions")
        if not isinstance(raw_regions, Mapping) or not raw_regions:
            raise CpuRoiError("CPU ROI profile needs at least one region")
        regions: dict[str, RoiRect] = {}
        ocr_scales: dict[str, float] = {}
        ref_width, ref_height = reference
        for roi_id, item in raw_regions.items():
            if not isinstance(roi_id, str) or not roi_id.strip() or not isinstance(item, Mapping):
                raise CpuRoiError("ROI entries must have a non-empty id and object value")
            rect = item.get("rect")
            if (
                not isinstance(rect, list)
                or len(rect) != 4
                or any(type(value) is not int for value in rect)
            ):
                raise CpuRoiError(f"ROI {roi_id!r} rect must contain four integers")
            parsed = RoiRect(*rect)
            if parsed.right > ref_width or parsed.bottom > ref_height:
                raise CpuRoiError(f"ROI {roi_id!r} exceeds reference client bounds")
            regions[roi_id] = parsed
            scale = item.get("ocr_scale", 1.0)
            if type(scale) not in (int, float) or not 1.0 <= float(scale) <= 8.0:
                raise CpuRoiError(
                    f"ROI {roi_id!r} ocr_scale must be a number within 1..8"
                )
            ocr_scales[roi_id] = float(scale)
        return cls(
            profile_id.strip(),
            (ref_width, ref_height),
            float(tolerance),
            regions,
            dict(backend),
            ocr_scales,
        )

    def resolve(self, roi_id: str, client_size: tuple[int, int]) -> ResolvedRoi:
        if roi_id not in self.regions:
            raise CpuRoiError(f"unknown CPU ROI: {roi_id!r}")
        if (
            not isinstance(client_size, tuple)
            or len(client_size) != 2
            or any(type(value) is not int or value < 1 for value in client_size)
        ):
            raise CpuRoiError("client_size must be a positive (width, height) tuple")
        width, height = client_size
        ref_width, ref_height = self.reference_client_size
        actual_ratio = width / height
        reference_ratio = ref_width / ref_height
        if abs(actual_ratio / reference_ratio - 1.0) > self.aspect_ratio_tolerance:
            raise CpuRoiError(
                f"client aspect ratio {actual_ratio:.6f} does not match ROI profile "
                f"{reference_ratio:.6f}"
            )
        source = self.regions[roi_id]
        scale_x, scale_y = width / ref_width, height / ref_height
        x = round(source.x * scale_x)
        y = round(source.y * scale_y)
        right = round(source.right * scale_x)
        bottom = round(source.bottom * scale_y)
        resolved = RoiRect(x, y, right - x, bottom - y)
        if resolved.right > width or resolved.bottom > height:
            raise CpuRoiError(f"resolved ROI {roi_id!r} exceeds current client bounds")
        return ResolvedRoi(
            roi_id,
            resolved,
            client_size,
            self.reference_client_size,
            self.ocr_scales.get(roi_id, 1.0),
        )

    def crop(self, image: Any, roi_id: str) -> tuple[Any, ResolvedRoi]:
        shape = getattr(image, "shape", ())
        if len(shape) < 2:
            raise CpuRoiError("image must have at least two dimensions")
        height, width = int(shape[0]), int(shape[1])
        resolved = self.resolve(roi_id, (width, height))
        rect = resolved.rect
        return image[rect.y:rect.bottom, rect.x:rect.right].copy(), resolved

    def describe(self, roi_id: str, client_size: tuple[int, int]) -> dict[str, Any]:
        resolved = self.resolve(roi_id, client_size)
        return {
            "profile_id": self.profile_id,
            "roi_id": roi_id,
            "coordinate_space": "client_pixels",
            "reference_client_size": list(self.reference_client_size),
            "client_size": list(client_size),
            "rect": resolved.rect.as_list(),
            "processing_device": "cpu",
            "opencl_enabled": False,
            "cuda_enabled": False,
        }


@lru_cache(maxsize=1)
def load_default_cpu_roi_profile() -> CpuRoiProfile:
    path = Path(__file__).resolve().parents[1] / "config" / "cpu_rois.yaml"
    return CpuRoiProfile.load(path)

