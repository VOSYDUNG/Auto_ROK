"""Fail-closed foreground/geometry guard for optional live Windows actuation."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import math
import ntpath
import os
from typing import Callable, Mapping, Protocol

from harness.action_surface import InputKind, ResolvedInput
from harness.gather_job_authority import GatherCatalogIdentity, GatherJobAuthority, GatherJobProgress
from harness.gather_job_store import GatherJobRevokedError
from harness.mission_runtime import ActionChoice, MissionContext, ToolSnapshot
from harness.mission_tool import InterferenceCheck, InterferenceGuard
from harness.scene_graph import SceneGraph
from harness.troop_policy import TROOP_SELECTION_PRECONDITION


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_INFORMATION_CLASS_INTEGRITY = 25


def _process_integrity_rid(pid: int) -> int | None:
    """Return the process token's mandatory-integrity RID, if readable."""
    if type(pid) is not int or pid <= 0:
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL

    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return None
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token,
            TOKEN_INFORMATION_CLASS_INTEGRITY,
            None,
            0,
            ctypes.byref(size),
        )
        if size.value <= 0:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token,
            TOKEN_INFORMATION_CLASS_INTEGRITY,
            buffer,
            size.value,
            ctypes.byref(size),
        ):
            return None
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        if not sid_pointer:
            return None
        subauthority_count = ctypes.cast(
            sid_pointer + 1,
            ctypes.POINTER(ctypes.c_ubyte),
        ).contents.value
        if subauthority_count <= 0:
            return None
        rid_pointer = sid_pointer + 8 + (subauthority_count - 1) * ctypes.sizeof(ctypes.c_ulong)
        return int(ctypes.cast(rid_pointer, ctypes.POINTER(ctypes.c_ulong)).contents.value)
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(process)


class WindowsForegroundInterferenceGuard:
    """Authorize input only for the still-current foreground ROK client.

    Live actuation is disabled unless ``armed=True`` is supplied explicitly.
    The guard verifies captured HWND/PID identity and client-screen geometry
    immediately before input. It never activates or focuses the game window.
    """

    def __init__(
        self,
        *,
        armed: bool = False,
        require_process_path: bool = False,
        expected_title: str = "Rise of Kingdoms",
        expected_exe: str = "MASS.exe",
    ) -> None:
        self.armed = armed
        self.require_process_path = require_process_path
        self.expected_title = expected_title
        self.expected_exe = expected_exe

    def check(
        self,
        context: MissionContext,
        before: ToolSnapshot,
        choice: ActionChoice,
        scene: SceneGraph,
        resolved: ResolvedInput,
    ) -> InterferenceCheck:
        if not self.armed:
            return InterferenceCheck(False, "LIVE_ACTUATION_NOT_ARMED")

        window = scene.facts.get("window")
        if not isinstance(window, Mapping):
            return InterferenceCheck(False, "WINDOW_IDENTITY_MISSING")
        if window.get("title") != self.expected_title or str(window.get("exe", "")).casefold() != self.expected_exe.casefold():
            return InterferenceCheck(False, "WINDOW_IDENTITY_MISMATCH")
        hwnd, pid = window.get("hwnd"), window.get("pid")
        if type(hwnd) is not int or hwnd <= 0 or type(pid) is not int or pid <= 0:
            return InterferenceCheck(False, "WINDOW_IDENTITY_INVALID")

        rect = scene.facts.get("client_screen_rect")
        if not (
            isinstance(rect, (list, tuple))
            and len(rect) == 4
            and all(type(item) is int for item in rect)
        ):
            return InterferenceCheck(False, "CLIENT_SCREEN_RECT_MISSING")

        if os.name != "nt":
            return InterferenceCheck(False, "WINDOWS_GUARD_UNAVAILABLE")

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        try:
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass
        foreground = int(user32.GetForegroundWindow())
        if foreground != hwnd:
            return InterferenceCheck(
                False,
                "TARGET_NOT_FOREGROUND",
                {"expected_hwnd": hwnd, "foreground_hwnd": foreground},
            )

        current_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(current_pid))
        if int(current_pid.value) != pid:
            return InterferenceCheck(False, "TARGET_PID_CHANGED")
        if self.require_process_path:
            captured_path = window.get("process_path")
            if not isinstance(captured_path, str) or not ntpath.isabs(captured_path):
                return InterferenceCheck(False, "PROCESS_PATH_MISSING")
            try:
                from harness.windows_capture_backend import _process_path
                current_path = _process_path(pid)
            except Exception:
                current_path = None
            if (not current_path or ntpath.normcase(ntpath.normpath(current_path))
                    != ntpath.normcase(ntpath.normpath(captured_path))):
                return InterferenceCheck(False, "TARGET_PROCESS_PATH_CHANGED")

        current_integrity = _process_integrity_rid(os.getpid())
        target_integrity = _process_integrity_rid(pid)
        if current_integrity is None or target_integrity is None:
            return InterferenceCheck(
                False,
                "PROCESS_INTEGRITY_UNAVAILABLE",
                {
                    "current_integrity_rid": current_integrity,
                    "target_integrity_rid": target_integrity,
                },
            )
        if current_integrity < target_integrity:
            return InterferenceCheck(
                False,
                "INPUT_INTEGRITY_MISMATCH",
                {
                    "current_integrity_rid": current_integrity,
                    "target_integrity_rid": target_integrity,
                    "reason": "Windows UIPI can block lower-integrity SendInput to the target",
                },
            )

        client = wintypes.RECT()
        if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client)):
            return InterferenceCheck(False, "CLIENT_RECT_UNAVAILABLE")
        origin = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin)):
            return InterferenceCheck(False, "CLIENT_ORIGIN_UNAVAILABLE")
        current_rect = [
            int(origin.x),
            int(origin.y),
            int(origin.x + client.right - client.left),
            int(origin.y + client.bottom - client.top),
        ]
        if list(rect) != current_rect:
            return InterferenceCheck(
                False,
                "CLIENT_GEOMETRY_CHANGED",
                {"captured_client_screen_rect": list(rect), "current_client_screen_rect": current_rect},
            )

        return InterferenceCheck(
            True,
            "FOREGROUND_TARGET_STABLE",
            {
                "guard_scope": "foreground_hwnd_pid_geometry",
                "target_hwnd": hwnd,
                "target_pid": pid,
                "client_screen_rect": current_rect,
            },
        )


class GatherJobLedger(Protocol):
    def progress(self, job: GatherJobAuthority) -> GatherJobProgress: ...

    def require_client(self, job: GatherJobAuthority, window: object) -> object: ...

    def reserve_dispatch(
        self, job: GatherJobAuthority, *, run_id: str, frame_id: str,
        action: str, now: datetime | None = None,
    ) -> object: ...


class GatherJobInputGuard:
    """Recheck a delegated GATHER job at the canonical pre-input boundary.

    The existing foreground guard runs first. Only a grounded March consumes
    one durable slot; a denied or uncertain March is never silently retried.
    The store's reservation is a dispatch attempt, not a queue verification.
    """

    def __init__(
        self,
        host_guard: InterferenceGuard,
        job: GatherJobAuthority,
        ledger: GatherJobLedger,
        catalog: GatherCatalogIdentity,
        *,
        max_frame_age_seconds: float = 10.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not math.isfinite(max_frame_age_seconds) or max_frame_age_seconds <= 0:
            raise ValueError("GATHER job frame-age bound must be positive")
        self.host_guard = host_guard
        self.job = job
        self.ledger = ledger
        self.catalog = catalog
        self.max_frame_age_seconds = max_frame_age_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def check(
        self,
        context: MissionContext,
        before: ToolSnapshot,
        choice: ActionChoice,
        scene: SceneGraph,
        resolved: ResolvedInput,
    ) -> InterferenceCheck:
        if (before.facts.get("window") != scene.facts.get("window")
                or before.facts.get("gather_client_binding_source")
                != "same_frame_capture_target_and_post_capture"
                or scene.facts.get("gather_client_binding_source")
                != "same_frame_capture_target_and_post_capture"):
            return InterferenceCheck(False, "GATHER_JOB_CLIENT_BINDING_MISSING")
        try:
            self.ledger.require_client(self.job, scene.facts.get("window"))
        except GatherJobRevokedError:
            return InterferenceCheck(False, "GATHER_JOB_STOPPED_OR_FULL")
        except Exception:
            return InterferenceCheck(False, "GATHER_JOB_CLIENT_BINDING_CHANGED")
        host = self.host_guard.check(context, before, choice, scene, resolved)
        if not host.allowed:
            return host

        now = self.clock()
        if (not isinstance(now, datetime) or now.tzinfo is None
                or now.utcoffset() is None):
            return InterferenceCheck(False, "GATHER_JOB_CLOCK_INVALID")
        observed_at = before.observed_at
        if (not isinstance(observed_at, (int, float)) or isinstance(observed_at, bool)
                or not math.isfinite(observed_at)
                or not 0 <= now.timestamp() - observed_at <= self.max_frame_age_seconds
                or not before.frame_id or before.frame_id != scene.frame_id
                or context.mission_id != self.job.mission_id
                or context.task_id != self.job.task_id
                or before.mission_id != context.mission_id
                or before.task_id != context.task_id
                or before.facts.get("character_id") != self.job.character_id
                or scene.facts.get("character_id") != self.job.character_id):
            return InterferenceCheck(False, "GATHER_JOB_SCOPE_OR_FRAME_MISMATCH")
        if (not self.job.starts_at <= now < self.job.expires_at
                or self.job.catalog_digest != self.catalog.digest
                or not self.job.allowed_actions.issubset(self.catalog.actions)
                or choice.action_id not in self.job.allowed_actions
                or choice.action_id not in self.catalog.actions
                or choice.action_id != resolved.action_id):
            return InterferenceCheck(False, "GATHER_JOB_ACTION_NOT_AUTHORIZED")
        allowed = next(
            (item for item in before.allowed_actions if item.action_id == choice.action_id),
            None,
        )
        if (allowed is None
                or allowed.requires_target and (
                    choice.target_id is None
                    or choice.target_id not in allowed.target_ids
                    or choice.target_id not in before.target_ids
                )):
            return InterferenceCheck(False, "GATHER_JOB_ACTION_NOT_EXPOSED")
        if resolved.kind is InputKind.CLICK_TARGET:
            if (resolved.frame_id != scene.frame_id
                    or resolved.target_id != choice.target_id
                    or choice.target_id not in {
                        target.target_id for target in scene.targets
                        if target.frame_id == scene.frame_id
                    }
                    or resolved.point is None):
                return InterferenceCheck(False, "GATHER_JOB_TARGET_NOT_CURRENT")
        elif resolved.kind is InputKind.HOTKEY:
            if not resolved.key or choice.target_id is not None:
                return InterferenceCheck(False, "GATHER_JOB_INPUT_NOT_RESOLVED")
        else:
            return InterferenceCheck(False, "GATHER_JOB_INPUT_NOT_RESOLVED")

        try:
            progress = self.ledger.progress(self.job)
        except Exception:
            return InterferenceCheck(False, "GATHER_JOB_PROGRESS_UNAVAILABLE")
        if (progress.job_id != self.job.job_id or progress.revoked
                or progress.dispatched_marches >= self.job.max_marches):
            return InterferenceCheck(False, "GATHER_JOB_STOPPED_OR_FULL")

        facts = dict(host.facts)
        facts.update({"gather_job_id": self.job.job_id,
                      "gather_job_reserved_marches_before": progress.dispatched_marches})
        if choice.action_id != "MARCH_WITH_CURRENT_SELECTION":
            return self._final_host_and_time_check(
                context, before, choice, scene, resolved, facts,
                success_code="GATHER_JOB_SCOPED_ACTION",
            )

        baseline = before.facts.get("completion_baseline")
        if progress.dispatched_marches != progress.verified_marches:
            return InterferenceCheck(False, "GATHER_JOB_PREVIOUS_MARCH_UNVERIFIED")
        if (not isinstance(baseline, Mapping)
                or baseline.get("counter_fact") != "march_queue_used"
                or type(baseline.get("capacity")) is not int
                or baseline["capacity"] != self.job.max_marches
                or baseline.get("character_id") != self.job.character_id
                or not isinstance(baseline.get("source_frame_id"), str)
                or not baseline["source_frame_id"]
                or not self._baseline_fresh(baseline, now, observed_at)):
            return InterferenceCheck(False, "GATHER_JOB_QUEUE_BASELINE_INVALID")
        if progress.verified_marches == 0:
            # The right-side queue UI first appears after this March. A job
            # ordinal of zero is not a sourced observation of queue 0/5.
            if (baseline.get("predicate_id") != "first_march_queue_appeared_at_one"
                    or baseline.get("source") != "job_initial_slot_ordinal"
                    or baseline.get("job_id") != self.job.job_id
                    or "counter_value" in baseline
                    or baseline["source_frame_id"] != before.frame_id
                    or baseline.get("source_timestamp") != observed_at
                    or type(before.facts.get("march_queue_used")) is int):
                return InterferenceCheck(False, "GATHER_JOB_QUEUE_BASELINE_INVALID")
        elif (baseline.get("predicate_id") != "march_queue_used_increased"
              or type(baseline.get("counter_value")) is not int
              or baseline["counter_value"] != progress.verified_marches
              or baseline.get("source") not in {"visible_ocr_queue_anchor", "visible_ocr_march_queue_region"}):
            return InterferenceCheck(False, "GATHER_JOB_QUEUE_BASELINE_INVALID")

        if (before.state != "NEW_TROOP_SETUP"
                or choice.target_id != "TROOP_MARCH"
                or resolved.kind is not InputKind.CLICK_TARGET
                or before.facts.get("gather_job_id") != self.job.job_id
                or before.facts.get("precondition_evidence_source") != "bounded_gather_job"
                or not isinstance(before.facts.get("precondition_evidence"), Mapping)
                or before.facts["precondition_evidence"].get(TROOP_SELECTION_PRECONDITION) is not True
                or before.facts.get("new_troop_formation_ready") is not True):
            return InterferenceCheck(False, "GATHER_JOB_NEW_TROOP_NOT_READY")
        if not self.job.march_precondition(
            context,
            current_character_id=scene.facts.get("character_id"),
            current_catalog_digest=self.catalog.digest,
            canonical_actions=self.catalog.actions,
            frame_id=scene.frame_id,
            frame_timestamp=observed_at,
            max_frame_age_seconds=self.max_frame_age_seconds,
            target_ids=frozenset(target.target_id for target in scene.targets),
            progress=progress,
            now=now,
        ):
            return InterferenceCheck(False, "GATHER_JOB_MARCH_PRECONDITION_DENIED")
        try:
            reservation = self.ledger.reserve_dispatch(
                self.job, run_id=context.run_id, frame_id=scene.frame_id,
                action=choice.action_id, now=self.clock(),
            )
        except Exception:
            return InterferenceCheck(False, "GATHER_JOB_RESERVATION_DENIED")
        facts["gather_job_dispatch_sequence"] = reservation.sequence
        return self._final_host_and_time_check(
            context, before, choice, scene, resolved, facts,
            success_code="GATHER_JOB_MARCH_RESERVED",
        )

    def _final_host_and_time_check(
        self,
        context: MissionContext,
        before: ToolSnapshot,
        choice: ActionChoice,
        scene: SceneGraph,
        resolved: ResolvedInput,
        facts: Mapping[str, object],
        *,
        success_code: str,
    ) -> InterferenceCheck:
        # Ledger and host work can take time. Recheck revocation after host
        # verification, then read the clock last, immediately before perform(). A
        # failed check after March reservation keeps the slot consumed so an
        # uncertain attempt cannot be clicked again automatically.
        final_host = self.host_guard.check(context, before, choice, scene, resolved)
        if not final_host.allowed:
            denied_facts = dict(facts)
            denied_facts.update(final_host.facts)
            return InterferenceCheck(False, "GATHER_JOB_HOST_CHANGED_AFTER_LEDGER", denied_facts)
        accepted_facts = dict(facts)
        accepted_facts.update(final_host.facts)
        try:
            self.ledger.require_client(self.job, scene.facts.get("window"))
        except GatherJobRevokedError:
            return InterferenceCheck(False, "GATHER_JOB_STOPPED_OR_FULL", accepted_facts)
        except Exception:
            return InterferenceCheck(False, "GATHER_JOB_CLIENT_BINDING_CHANGED_AFTER_LEDGER", accepted_facts)
        instant = self.clock()
        observed_at = before.observed_at
        if (not isinstance(instant, datetime) or instant.tzinfo is None
                or instant.utcoffset() is None
                or not isinstance(observed_at, (int, float))
                or isinstance(observed_at, bool) or not math.isfinite(observed_at)
                or not 0 <= instant.timestamp() - observed_at <= self.max_frame_age_seconds
                or not self.job.starts_at <= instant < self.job.expires_at):
            return InterferenceCheck(False, "GATHER_JOB_STALE_AFTER_LEDGER", accepted_facts)
        if (choice.action_id == "MARCH_WITH_CURRENT_SELECTION"
                and not self._baseline_fresh(before.facts.get("completion_baseline"),
                                             instant, observed_at)):
            return InterferenceCheck(False, "GATHER_JOB_QUEUE_BASELINE_STALE_AFTER_LEDGER",
                                     accepted_facts)
        return InterferenceCheck(True, success_code, accepted_facts)

    def _baseline_fresh(self, baseline: object, instant: datetime, observed_at: object) -> bool:
        if not isinstance(baseline, Mapping):
            return False
        source_at = baseline.get("source_timestamp")
        return (isinstance(source_at, (int, float)) and not isinstance(source_at, bool)
                and math.isfinite(source_at)
                and isinstance(observed_at, (int, float)) and not isinstance(observed_at, bool)
                and math.isfinite(observed_at) and source_at <= observed_at
                and 0 <= instant.timestamp() - source_at <= self.max_frame_age_seconds)
