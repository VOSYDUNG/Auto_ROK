"""Run one bounded GATHER_RESOURCE mission tick on Windows.

This command is caller-driven, not a scheduler. Live input is fail-closed unless
--arm-live is supplied and the foreground/geometry guard passes immediately
before actuation. Each invocation also writes a durable evidence record so a
later validator can distinguish dispatch from verified live completion.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.action_surface import TRAINED_NATIVE_SHORTCUTS  # noqa: E402
from harness.gather_facts import GatherFactObservationProvider  # noqa: E402
from harness.gather_job_authority import compiled_gather_catalog, validate_schedule_catalog  # noqa: E402
from harness.gather_job_startup_attestation import (  # noqa: E402
    canonical_startup_attestation_path, validate_canonical_startup_attestation,
)
from harness.gather_job_store import (  # noqa: E402
    GatherClientBinding, JsonGatherJobStore, load_gather_job_authority,
)
from harness.gather_client_binding import GatherClientBindingObservationProvider  # noqa: E402
from harness.gather_job_coordinator import GatherJobCoordinator, persist_gather_job_closeout  # noqa: E402
from harness.host_input_isolation import (  # noqa: E402
    HostInputIsolationEvidence,
    HostInputIsolationEvidenceError,
    validate_gather_job_host_trace,
)
from harness.gather_replay_evidence import (  # noqa: E402
    build_gather_tick_evidence,
    save_gather_tick_evidence,
)
from harness.local_llm_selector import OpenAICompatibleDecisionProvider  # noqa: E402
from harness.main_view_detector import MainViewProfile, MainViewVisualObservationProvider  # noqa: E402
from harness.farm_search_visual import FarmSearchVisualObservationProvider  # noqa: E402
from harness.map_coordinate_provider import MapCoordinateObservationProvider  # noqa: E402
from harness.queue_indicator_provider import QueueIndicatorObservationProvider  # noqa: E402
from harness.mission_loader import compile_mission  # noqa: E402
from harness.mission_runner import MissionRunner  # noqa: E402
from harness.mission_runtime import MissionContext  # noqa: E402
from harness.mission_store import CheckpointStatus, JsonMissionStore  # noqa: E402
from harness.mission_tool import BoundedMissionTool, HumanInterfaceActionProvider, InterferenceCheck  # noqa: E402
from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec  # noqa: E402
from harness.overlay_events import OverlayEventWriter  # noqa: E402
from harness.policy_overlay import PolicyEvidenceObservationProvider  # noqa: E402
from harness.resource_level_control import (  # noqa: E402
    GatherScreenMappedActionSurface,
    ResourceLevelControlObservationProvider,
    ResourceLevelProfile,
)
from harness.r3_endurance_authorization import load_reserved_ticket  # noqa: E402
from harness.troop_policy import TroopSelectionApproval  # noqa: E402
from harness.windows_input import WindowsHumanInputActuator  # noqa: E402
from harness.windows_interference_guard import (  # noqa: E402
    GatherJobInputGuard,
    WindowsForegroundInterferenceGuard,
)
from harness.windows_live_observation import WindowsLiveObservationProvider  # noqa: E402


GATHER_JOB_MAX_FRAME_AGE_SECONDS = 10.0
GATHER_JOB_STORE_ROOT = ROOT / "workspace" / "checkpoints" / "gather-jobs"


def _candidate_specs(path: str | None) -> tuple[OcrTargetSpec, ...]:
    if path is None:
        return ()
    source = Path(path).resolve()
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("candidate file must contain a JSON list")
    result: list[OcrTargetSpec] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("candidate entries must be objects")
        target_id = item.get("target_id")
        labels = item.get("labels")
        confidence = item.get("min_confidence", 0.90)
        allow_unscored = item.get("allow_unscored_exact", False)
        require_acquisition = item.get("require_acquisition")
        if (
            not isinstance(target_id, str)
            or not target_id
            or not isinstance(labels, list)
            or not labels
            or not all(isinstance(label, str) and label for label in labels)
            or type(confidence) not in (int, float)
            or type(allow_unscored) is not bool
            or (require_acquisition is not None and not isinstance(require_acquisition, str))
        ):
            raise ValueError(f"invalid candidate entry: {item!r}")
        result.append(
            OcrTargetSpec(
                target_id,
                tuple(labels),
                float(confidence),
                allow_unscored,
                require_acquisition,
            )
        )
    return tuple(result)


def _local_llm_provider(path: str | None) -> OpenAICompatibleDecisionProvider | None:
    if path is None:
        return None
    config_path = Path(path).resolve()
    if not config_path.is_relative_to(ROOT):
        raise ValueError("local LLM config must be inside the repository")
    value = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("local LLM config must be a JSON object")
    if value.get("enabled") is False:
        return None
    return OpenAICompatibleDecisionProvider.from_mapping(value)


def _local_llm_summary(provider: OpenAICompatibleDecisionProvider | None) -> dict[str, object]:
    if provider is None:
        return {
            "configured": False,
            "model": None,
            "model_output": None,
            "last_error": None,
            "usage": None,
            "request_sha256": None,
            "request_bytes": None,
            "request_elapsed_ms": None,
        }
    return {
        "configured": True,
        "model": provider.model,
        "model_output": provider.last_model_output,
        "last_error": provider.last_error,
        "usage": provider.last_usage,
        "request_sha256": provider.last_request_sha256,
        "request_bytes": provider.last_request_bytes,
        "request_elapsed_ms": provider.last_request_elapsed_ms,
    }


def _host_input_isolation_summary(path: str | None, context: MissionContext) -> dict[str, object]:
    """Load and assess direct one-user host evidence for this occurrence."""
    if path is None:
        return {
            "provided": False,
            "ready": False,
            "trace_path": None,
            "environment": "windows_host_direct",
            "reasons": ["no direct-host input-isolation evidence supplied"],
        }
    source = Path(path).resolve()
    evidence_root = (ROOT / "workspace" / "evidence").resolve()
    if not source.is_relative_to(evidence_root):
        raise ValueError("direct-host input-isolation evidence must be under workspace/evidence")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read direct-host input-isolation evidence: {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("direct-host input-isolation evidence must be a JSON object")
    # Accept either the raw trace or the assessment output, while always
    # re-assessing the trace here.
    trace = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else raw
    try:
        evidence = HostInputIsolationEvidence.from_dict(trace)
    except HostInputIsolationEvidenceError as exc:
        raise ValueError(f"invalid direct-host input-isolation evidence: {exc}") from exc
    ready, assessment_reasons = evidence.assess()
    reasons = list(assessment_reasons)
    if evidence.run_id != context.run_id:
        reasons.append("direct-host trace run_id does not match the current mission occurrence")
    ready = not reasons
    return {
        "provided": True,
        "ready": ready,
        "trace_path": str(source),
        "evidence_id": evidence.evidence_id,
        "session_id": evidence.session_id,
        "environment": evidence.environment,
        "run_id": evidence.run_id,
        "unexpected_input_events": evidence.unexpected_input_events,
        "reasons": reasons,
    }


def _attested_job_client(job_id: str, digest: str) -> GatherClientBinding:
    path = canonical_startup_attestation_path(job_id, ROOT / "workspace")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("GATHER startup attestation changed before tick host preflight")
    record = json.loads(data)
    capture = record.get("capture") if isinstance(record, dict) else None
    if not isinstance(capture, dict):
        raise ValueError("GATHER startup attestation lacks client binding")
    return GatherClientBinding.from_window(capture.get("client_binding"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="single-occurrence ID; derived from job and slot in GATHER job mode")
    parser.add_argument("--task-id", default="one-character")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--resource-type", required=True, choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int)
    parser.add_argument(
        "--candidates",
        default=str(ROOT / "config" / "gather_ocr_targets.json"),
        help="JSON OCR target specs; defaults to the trained GATHER target set",
    )
    parser.add_argument(
        "--main-view-profile",
        default=str(ROOT / "config" / "main_view_profiles.json"),
        help="operator-trained CITY_VIEW/WORLD_MAP_VIEW visual signature profile",
    )
    parser.add_argument(
        "--resource-level-profile",
        default=str(ROOT / "config" / "resource_level_profile.json"),
        help="operator-trained resource level slider profile",
    )
    parser.add_argument("--workspace-root", default=str(ROOT / "workspace" / "runtime"))
    parser.add_argument(
        "--ocr-backend",
        choices=("windows_direct", "windows", "rapidocr_fixed_roi_experiment"),
        default="windows_direct",
        help="observation OCR backend. windows_direct calls Windows.Media.Ocr "
             "in process and reads the calibrated regions; windows is the "
             "older PowerShell path, kept for replaying stored evidence",
    )
    parser.add_argument("--checkpoint-root", default=str(ROOT / "workspace" / "checkpoints"))
    parser.add_argument(
        "--evidence-root",
        default=str(ROOT / "workspace" / "evidence" / "gather"),
        help="append-only per-tick GATHER evidence root",
    )
    parser.add_argument(
        "--troop-policy-approval",
        help="JSON operator approval bound to this mission/task/run/character occurrence",
    )
    parser.add_argument(
        "--approve-current-troop-selection",
        action="store_true",
        help="explicit one-shot operator approval for the current occurrence; prefer --troop-policy-approval for durable provenance",
    )
    parser.add_argument(
        "--gather-job",
        help="operator-created startup GATHER job JSON under workspace; separate from legacy B003 approval",
    )
    parser.add_argument(
        "--startup-attestation-sha256",
        help="driver-pinned digest of the canonical startup attestation for this job",
    )
    parser.add_argument("--arm-live", action="store_true")
    parser.add_argument(
        "--r3-repetition",
        action="store_true",
        help="require a fresh append-only R3 reservation before this live tick",
    )
    parser.add_argument(
        "--r3-reservation-ledger",
        help="append-only R3 reservation ledger required by --r3-repetition",
    )
    parser.add_argument(
        "--input-isolation-evidence",
        help="raw or assessed windows_host_direct trace JSON; required and ready before --arm-live",
    )
    parser.add_argument(
        "--local-llm-config",
        help="optional repository-local OpenAI-compatible config; used only for NEEDS_DECISION candidates",
    )
    parser.add_argument(
        "--overlay-events",
        help="optional workspace JSONL event stream for the operator shadow HUD",
    )
    parser.add_argument("--min-target-confidence", type=float, default=0.90)
    return parser


class _SessionJobInputGuard(GatherJobInputGuard):
    """Revalidate retained session inputs after any bounded decision wait."""

    def __init__(self, session, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = session

    def check(self, context, before, choice, scene, resolved):
        try:
            self.session._dispatch_preflight(context, self.job, self.catalog)
        except Exception as exc:
            return InterferenceCheck(False, "GATHER_SESSION_PREFLIGHT_FAILED",
                                     {"error": f"{type(exc).__name__}: {exc}"})
        return super().check(context, before, choice, scene, resolved)


class GatherRuntimeSession:
    """One job's canonical runtime, retained until close; no observation caching.

    Only run/resource/host-trace vary per step. Configuration and authority bytes
    are pinned on first use and rechecked before input, including after a model
    wait. Construction is lazy so denied preflight never creates an actuator.
    """

    def __init__(self, args: argparse.Namespace):
        self._args = deepcopy(args)
        self._checkpoint_store = JsonMissionStore(args.checkpoint_root)
        self._plans = {}
        self._assets = None
        self._loaded_profiles = None
        self._base_observations = None
        self._capture_provider = None
        self._runner = None
        self._resource_providers = {}
        self._resource_guards = {}
        self._host_guard = None
        self._actuator = None
        self._decision_provider = None
        self._active_args = None
        self._closed = False
        self._stepping = False

    def _assert_binding(self):
        args = self._args
        paths = [ROOT / "config" / name for name in (
            "mission_flows.yaml", "ui_states.yaml", "queue_indicator_profile.json",
        )]
        paths += [Path(value).resolve() for value in (
            args.gather_job, args.candidates, args.main_view_profile,
            args.resource_level_profile, args.local_llm_config,
            args.troop_policy_approval,
        ) if value]
        current = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        if self._assets is None:
            self._assets = current
        elif current != self._assets:
            raise ValueError("GATHER session authority or runtime assets changed")

    def _compiled_plan(self, args):
        key = (args.resource_type, args.resource_level)
        if key not in self._plans:
            self._plans[key] = compile_mission(
                ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
                "GATHER_RESOURCE",
                {"resource_type": args.resource_type, "resource_level": args.resource_level},
            )
        return self._plans[key]

    def _profiles(self):
        if self._loaded_profiles is None:
            self._loaded_profiles = (
                _candidate_specs(self._args.candidates),
                MainViewProfile.load(self._args.main_view_profile),
                ResourceLevelProfile.load(self._args.resource_level_profile),
            )
        return self._loaded_profiles

    def _base_provider(self, args, candidate_specs, main_view_profile):
        if self._base_observations is None:
            observations = WindowsLiveObservationProvider(
                args.workspace_root,
                ocr_backend=args.ocr_backend,
            )
            self._capture_provider = observations
            observations = OcrSemanticObservationProvider(observations, candidate_specs)
            # The template reader for the march queue.  Built in M3 and, until
            # now, wired into nothing: the live tick got its queue fact only
            # from whole-frame OCR, which is exactly the source this replaced.
            # Completion is evidenced by the queue count RISING, so without
            # this a successful march could never be proven and the runner
            # kept ticking - 64 wasted ticks across today's runs, the single
            # largest bucket.
            observations = QueueIndicatorObservationProvider(
                observations, ROOT / "config" / "queue_indicator_profile.json"
            )
            observations = FarmSearchVisualObservationProvider(observations)
            observations = MainViewVisualObservationProvider(observations, main_view_profile)
            # Second, independent route to WORLD_MAP_VIEW.  The visual signature
            # above cannot carry that state - open terrain looks different
            # everywhere you pan - so the coordinate readout carries it instead.
            observations = MapCoordinateObservationProvider(observations)
            self._base_observations = observations
        return self._base_observations

    def _dispatch_preflight(self, context, job, catalog):
        self._assert_binding()
        args = self._active_args
        if self._closed or args is None or context.run_id != args.run_id:
            raise ValueError("GATHER session is not bound to this active run")
        current = load_gather_job_authority(
            Path(args.gather_job), canonical_actions=catalog.actions,
            expected_catalog_digest=catalog.digest,
        )
        if current != job:
            raise ValueError("GATHER session job scope changed")
        if args.input_isolation_evidence is not None:
            host = validate_gather_job_host_trace(
                Path(args.input_isolation_evidence), expected_run_id=context.run_id,
                expected_client=_attested_job_client(job.job_id, args.startup_attestation_sha256),
                workspace_root=ROOT / "workspace",
            )
            if host.get("ready") is not True:
                raise ValueError("GATHER session host trace is not ready")

    def step(self, *, run_id=None, resource_type=None, host_trace_path=None):
        if self._closed:
            raise RuntimeError("GATHER runtime session is closed")
        if self._stepping:
            raise RuntimeError("GATHER runtime session step is already active")
        args = deepcopy(self._args)
        if run_id is not None:
            args.run_id = run_id
        if resource_type is not None:
            args.resource_type = resource_type
        if host_trace_path is not None:
            args.input_isolation_evidence = str(host_trace_path)
        self._stepping = True
        self._active_args = args
        try:
            # Preserve typed argument/preflight failures before asset binding.
            return self._step(args)
        except Exception as exc:
            return 2, {"status": "failed", "error": {
                "type": type(exc).__name__, "message": str(exc),
            }}
        finally:
            self._active_args = None
            self._stepping = False

    def close(self):
        if self._stepping:
            raise RuntimeError("cannot close an active GATHER step")
        if self._closed:
            return
        self._closed = True
        resources = (self._capture_provider, self._decision_provider, self._actuator)
        self._runner = self._base_observations = self._decision_provider = self._actuator = None
        self._checkpoint_store = self._loaded_profiles = self._active_args = self._capture_provider = None
        self._plans.clear()
        self._resource_providers.clear()
        self._resource_guards.clear()
        self._host_guard = None
        self._assets = None
        for resource in resources:
            close = getattr(resource, "close", None)
            if callable(close):
                close()

    def _step(self, args):
        if not 0.0 <= args.min_target_confidence <= 1.0:
            raise ValueError("min-target-confidence must be within [0, 1]")
        if args.troop_policy_approval and args.approve_current_troop_selection:
            raise ValueError(
                "use either --troop-policy-approval or --approve-current-troop-selection, not both"
            )
        if args.gather_job and (
            args.troop_policy_approval or args.approve_current_troop_selection
            or args.r3_repetition
        ):
            raise ValueError("GATHER_JOB_CANNOT_MIX_LEGACY_B003_OR_R3")
        if args.gather_job and args.arm_live and (
            not args.startup_attestation_sha256
            or (args.run_id is not None and not args.input_isolation_evidence)
        ):
            raise ValueError("GATHER job live arm requires pinned startup attestation, current run ID and fresh host trace")
        if args.startup_attestation_sha256 and not args.gather_job:
            raise ValueError("startup attestation digest requires --gather-job")
        if args.r3_repetition and not args.arm_live:
            raise ValueError("R3_REPETITION_REQUIRES_LIVE_ARM")
        if args.r3_repetition and not args.r3_reservation_ledger:
            raise ValueError("R3_REPETITION_REQUIRES_RESERVATION_LEDGER")
        overlay_writer: OverlayEventWriter | None = None
        if args.overlay_events:
            overlay_path = Path(args.overlay_events).resolve()
            if not overlay_path.is_relative_to((ROOT / "workspace").resolve()):
                raise ValueError("overlay events must be under workspace")
            overlay_writer = OverlayEventWriter(overlay_path)

        self._assert_binding()
        compiled = self._compiled_plan(args)
        if not args.gather_job and not args.run_id:
            raise ValueError("--run-id is required without --gather-job")
        context = MissionContext("GATHER_RESOURCE", args.task_id, args.run_id or "")
        gather_job = None
        gather_job_store = None
        gather_catalog = None
        job_coordinator = None
        checkpoint_store = self._checkpoint_store
        if args.gather_job:
            workspace_root = (ROOT / "workspace").resolve()
            job_path = Path(args.gather_job).resolve()
            if not job_path.is_relative_to(workspace_root):
                raise ValueError("GATHER job artifact must be under workspace")
            gather_catalog = compiled_gather_catalog(compiled)
            gather_job = load_gather_job_authority(
                job_path,
                canonical_actions=gather_catalog.actions,
                expected_catalog_digest=gather_catalog.digest,
            )
            if args.arm_live and gather_job.schema_version != 2:
                raise ValueError("GATHER job live arm requires a schema-v2 five-slot schedule")
            validate_schedule_catalog(gather_job, ROOT / "config" / "mission_flows.yaml",
                                      ROOT / "config" / "ui_states.yaml")
            if gather_job.task_id != context.task_id or gather_job.character_id != args.character_id:
                raise ValueError("GATHER job task or character does not match this tick")
            startup_attestation_sha256 = validate_canonical_startup_attestation(
                job_path, gather_job.job_id,
                resource_type=gather_job.resource_for_slot(1)
                    if gather_job.schema_version == 2 else args.resource_type,
                resource_level=args.resource_level,
                workspace_root=workspace_root, ledger_root=GATHER_JOB_STORE_ROOT,
                mission_flows=ROOT / "config" / "mission_flows.yaml",
                ui_states=ROOT / "config" / "ui_states.yaml",
                expected_sha256=args.startup_attestation_sha256,
            )
            gather_job_store = JsonGatherJobStore(GATHER_JOB_STORE_ROOT)
            job_coordinator = GatherJobCoordinator(gather_job, gather_job_store, checkpoint_store)
            job_plan = job_coordinator.plan()
            if gather_job.schema_version == 2:
                expected_resource = (gather_job.resource_for_slot(job_plan.sequence)
                                     if job_plan.sequence is not None else gather_job.resource_for_slot(1))
                if (args.resource_type != expected_resource
                        or args.resource_level != gather_job.resource_level
                        or gather_catalog.digest != (gather_job.catalog_for_slot(job_plan.sequence)
                            if job_plan.sequence is not None else gather_job.catalog_for_slot(1))):
                    raise ValueError("GATHER tick resource differs from durable scheduled slot")
            if args.run_id and args.run_id != job_plan.run_id:
                raise ValueError("GATHER job run_id must match the current deterministic slot")
            if job_plan.closed:
                closeout_path = persist_gather_job_closeout(gather_job, job_plan, args.evidence_root)
                return 0, {
                    "status": "complete", "gather_job_id": gather_job.job_id,
                    "startup_attestation_sha256": startup_attestation_sha256,
                    "gather_job_verified_marches": job_plan.progress.verified_marches,
                    "gather_job_closed_at_five": True,
                    "gather_job_closeout": list(job_plan.closeout),
                    "gather_job_closeout_path": str(closeout_path),
                    "gather_job_journaled_this_tick": False,
                }
            if args.arm_live and not all((args.run_id, args.input_isolation_evidence)):
                raise ValueError("GATHER job live arm requires pinned startup attestation, current run ID and fresh host trace")
            context = MissionContext("GATHER_RESOURCE", args.task_id, job_plan.run_id)
            args.run_id = context.run_id
        r3_reservation: dict[str, object] | None = None
        if args.r3_repetition:
            reservation_path = Path(args.r3_reservation_ledger).resolve()
            evidence_root = (ROOT / "workspace" / "evidence").resolve()
            if not reservation_path.is_relative_to(evidence_root):
                raise ValueError("R3 reservation ledger must be under workspace/evidence")
            r3_reservation = load_reserved_ticket(reservation_path, run_id=context.run_id)
        if gather_job is not None and args.input_isolation_evidence is not None:
            try:
                host_input_isolation = validate_gather_job_host_trace(
                    Path(args.input_isolation_evidence),
                    expected_run_id=context.run_id,
                    expected_client=_attested_job_client(
                        gather_job.job_id, startup_attestation_sha256,
                    ),
                    workspace_root=ROOT / "workspace",
                )
            except HostInputIsolationEvidenceError as exc:
                raise ValueError(f"GATHER job host trace preflight failed: {exc}") from exc
        elif gather_job is not None and args.startup_attestation_sha256 is not None:
            raise ValueError("GATHER job driver tick requires a fresh host trace")
        else:
            host_input_isolation = _host_input_isolation_summary(args.input_isolation_evidence, context)
        if args.arm_live and host_input_isolation.get("ready") is not True:
            reasons = "; ".join(str(item) for item in host_input_isolation.get("reasons", []))
            raise ValueError("LIVE_ARM_REQUIRES_READY_HOST_INPUT_ISOLATION" + (f": {reasons}" if reasons else ""))
        candidate_specs, main_view_profile, resource_level_profile = self._profiles()

        approval: TroopSelectionApproval | None = None
        if gather_job is None:
            if args.troop_policy_approval:
                approval = TroopSelectionApproval.load(args.troop_policy_approval)
            elif args.approve_current_troop_selection:
                approval = TroopSelectionApproval.explicit_cli(context, args.character_id)
        approvals = approval.approvals_for(context, args.character_id) if approval is not None else {}
        approval_summary = (
            approval.to_summary(context, args.character_id)
            if approval is not None
            else {
                "approved": False,
                "bound_to_occurrence": False,
                "source": "none",
            }
        )

        # Provenance -> OCR semantics -> trained visual/layout evidence -> trained
        # typed controls -> visible facts -> occurrence-bound operator policy.
        observations = self._base_provider(args, candidate_specs, main_view_profile)
        resource_key = (args.resource_type, args.resource_level)
        if resource_key not in self._resource_providers:
            observations = ResourceLevelControlObservationProvider(
                observations,
                resource_level_profile,
                # The search panel is centred under the SELECTED category, so
                # the trained slider geometry is only correct for the category
                # it was trained on.  Without this the level click lands on the
                # neighbouring panel's minus button.
                resource_type=args.resource_type,
            )
            observations = GatherFactObservationProvider(observations, character_id=args.character_id)
            if gather_job is None:
                observations = PolicyEvidenceObservationProvider(observations, approvals)
            else:
                observations = GatherClientBindingObservationProvider(
                    observations, gather_job, gather_job_store,
                )
                observations = PolicyEvidenceObservationProvider(
                    observations,
                    gather_job=gather_job,
                    job_progress=lambda: gather_job_store.progress(gather_job),
                    catalog_digest=gather_catalog.digest,
                    canonical_actions=gather_catalog.actions,
                    max_frame_age_seconds=GATHER_JOB_MAX_FRAME_AGE_SECONDS,
                )

            if self._host_guard is None:
                self._host_guard = WindowsForegroundInterferenceGuard(
                    armed=args.arm_live, require_process_path=gather_job is not None,
                )
            input_guard = self._host_guard
            if gather_job is not None:
                input_guard = _SessionJobInputGuard(
                    self, input_guard, gather_job, gather_job_store, gather_catalog,
                    max_frame_age_seconds=GATHER_JOB_MAX_FRAME_AGE_SECONDS,
                )
            self._resource_providers[resource_key] = observations
            self._resource_guards[resource_key] = input_guard
        observations = self._resource_providers[resource_key]
        input_guard = self._resource_guards[resource_key]
        if self._runner is None:
            surface = GatherScreenMappedActionSurface(
                TRAINED_NATIVE_SHORTCUTS,
                min_target_confidence=args.min_target_confidence,
                allow_unscored_exact_targets=any(spec.allow_unscored_exact for spec in candidate_specs),
            )
            self._actuator = WindowsHumanInputActuator()
            action_provider = HumanInterfaceActionProvider(surface, self._actuator, input_guard)
            tool = BoundedMissionTool(compiled, observations, action_provider)
            self._decision_provider = _local_llm_provider(args.local_llm_config)
            self._runner = MissionRunner(
                compiled, tool, checkpoint_store, decision_provider=self._decision_provider,
            )
        else:
            # The runner and executor remain job-owned. Only resource-specific
            # compilation/policy changes; old scene handles cannot cross steps.
            self._runner.compiled = compiled
            self._runner.tool.compiled = compiled
            self._runner.tool.observations = observations
            self._runner.tool.actions.guard = input_guard
            self._runner.tool._scenes.clear()
        runner = self._runner
        decision_provider = self._decision_provider
        if decision_provider is not None:
            # Telemetry belongs to this step even when deterministic selection
            # makes no model call. Retain the provider, not the preceding reply.
            for name in ("last_model_output", "last_error", "last_usage",
                         "last_request_sha256", "last_request_bytes", "last_request_elapsed_ms"):
                setattr(decision_provider, name, None)
        job_tick = job_coordinator.tick(runner) if job_coordinator is not None else None
        result = job_tick.result if job_tick is not None else runner.tick(context)
        assert result is not None
        job_verification_error = None
        journaled_this_tick = False
        if job_tick is not None:
            journaled_this_tick = job_tick.journaled_this_tick
            job_verification_error = job_tick.error
            job_progress = job_tick.progress
        post_job_plan = None
        if job_coordinator is not None and job_verification_error is None:
            try:
                post_job_plan = job_coordinator.plan()
            except Exception as exc:
                job_verification_error = f"{type(exc).__name__}: {exc}"
        closeout_path = None
        if post_job_plan is not None and post_job_plan.closed and job_verification_error is None:
            try:
                closeout_path = persist_gather_job_closeout(gather_job, post_job_plan, args.evidence_root)
            except Exception as exc:
                job_verification_error = f"{type(exc).__name__}: {exc}"
        job_closed_at_five = bool(
            post_job_plan is not None and post_job_plan.closed
            and job_verification_error is None and closeout_path is not None
        )

        evidence_record = build_gather_tick_evidence(
            context=context,
            character_id=args.character_id,
            result=result,
            live_armed=bool(args.arm_live),
            host_input_isolation=host_input_isolation,
            policy_approval=approval_summary,
            main_view_profile_trained=bool(main_view_profile.prototypes),
            resource_level_profile_trained=resource_level_profile.trained,
        )
        local_llm = _local_llm_summary(decision_provider)
        evidence_record["runtime"]["local_llm"] = local_llm
        if gather_job is not None:
            evidence_record["runtime"]["gather_job"] = {
                "job_id": gather_job.job_id,
                "startup_attestation_sha256": startup_attestation_sha256,
                "catalog_digest": gather_job.catalog_digest,
                "reserved_marches": gather_job_store.progress(gather_job).dispatched_marches,
                "verified_marches": job_progress.verified_marches,
                "closed_at_five": job_closed_at_five,
                "journaled_this_tick": journaled_this_tick,
                "verification_error": job_verification_error,
                "next_run_id": post_job_plan.run_id if post_job_plan is not None else None,
                "closeout": post_job_plan.closeout if job_closed_at_five else None,
                "closeout_path": str(closeout_path) if closeout_path is not None else None,
            }
            if gather_job.schema_version == 2:
                evidence_record["runtime"]["gather_job"].update({
                    "resource_type": args.resource_type,
                    "slot_catalog_digest": gather_catalog.digest,
                    "schedule_digest": gather_job.schedule_digest,
                })
        evidence_path = save_gather_tick_evidence(args.evidence_root, evidence_record)

        payload = {
            "status": result.status.value,
            "run_id": context.run_id,
            "checkpoint_revision": result.checkpoint.revision,
            "state": result.checkpoint.last_state,
            "frame_id": result.checkpoint.last_frame_id,
            "decision": result.checkpoint.last_decision,
            "reason": result.reason,
            "live_armed": bool(args.arm_live),
            "host_input_isolation": host_input_isolation,
            "policy_approved": bool(approval_summary.get("bound_to_occurrence")),
            "policy_approval_id": approval_summary.get("approval_id"),
            "policy_approval_source": approval_summary.get("source"),
            "evidence_path": str(evidence_path),
            "ocr_target_specs": len(candidate_specs),
            "unscored_exact_enabled": any(spec.allow_unscored_exact for spec in candidate_specs),
            "main_view_profile_trained": bool(main_view_profile.prototypes),
            "resource_level_profile_trained": resource_level_profile.trained,
            "local_llm_model": decision_provider.model if decision_provider is not None else None,
            "local_llm": local_llm,
            "r3_repetition": bool(args.r3_repetition),
            "r3_reservation": r3_reservation,
            "gather_job_id": gather_job.job_id if gather_job is not None else None,
        }
        if gather_job is not None:
            payload["startup_attestation_sha256"] = startup_attestation_sha256
            if gather_job.schema_version == 2:
                payload["gather_job_resource_type"] = args.resource_type
                payload["gather_job_slot_catalog_digest"] = gather_catalog.digest
            payload["gather_job_verified_marches"] = job_progress.verified_marches
            payload["gather_job_closed_at_five"] = job_closed_at_five
            payload["gather_job_journaled_this_tick"] = journaled_this_tick
            payload["gather_job_verification_error"] = job_verification_error
            payload["gather_job_next_run_id"] = post_job_plan.run_id if post_job_plan is not None else None
            payload["gather_job_resume_required"] = not job_closed_at_five
            payload["gather_job_closeout"] = list(post_job_plan.closeout) if job_closed_at_five else None
            payload["gather_job_closeout_path"] = str(closeout_path) if closeout_path is not None else None
        if result.selection is not None:
            payload["selection"] = result.selection.decision.value
            payload["candidate_count"] = len(result.selection.candidates)
            if result.selection.choice is not None:
                payload["choice"] = {
                    "action_id": result.selection.choice.action_id,
                    "target_id": result.selection.choice.target_id,
                    "arguments": dict(result.selection.choice.arguments),
                }
        if overlay_writer is not None:
            overlay_writer.emit(
                "gather_tick",
                {
                    "run_id": context.run_id,
                    "status": payload["status"],
                    "state": payload["state"],
                    "frame_id": payload["frame_id"],
                    "harness": {
                        "status": payload["status"],
                        "state": payload["state"],
                        "frame_id": payload["frame_id"],
                        "decision": payload.get("decision"),
                        "choice": payload.get("choice"),
                        "selection": payload.get("selection"),
                    },
                    "local_llm": local_llm,
                    "evidence_path": str(evidence_path),
                },
            )

        if job_verification_error is not None:
            return 4, payload
        if result.status in {CheckpointStatus.RUNNING, CheckpointStatus.COMPLETE}:
            return 0, payload
        if result.status in {
            CheckpointStatus.REOBSERVE,
            CheckpointStatus.WAITING,
            CheckpointStatus.NEEDS_DECISION,
        }:
            return 3, payload
        return 4, payload

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session = GatherRuntimeSession(args)
    try:
        code, payload = session.step()
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr if code == 2 else sys.stdout)
        return code
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
