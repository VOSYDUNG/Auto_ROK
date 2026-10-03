"""Farm search surface from measured current control images, never click authority."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib,json
from pathlib import Path

from harness.contracts import Evidence
from harness.mission_tool import ObservationBundle
from harness.template_anchors import TemplateAnchorError,load_anchor_spec,resolve_template
from harness.gather_job_store import GatherClientBinding,GatherJobStoreError

FARM_SEARCH_EVIDENCE='farm resource search controls'
ROOT=Path(__file__).resolve().parents[1]

class FarmSearchVisualObservationProvider:
    def __init__(self,inner,profile_path=None,*,now=None):
        self.inner=inner
        self.profile_path=Path(profile_path or ROOT/'config/farm_search_visual.json')
        self.now=now or (lambda:datetime.now(timezone.utc))

    def observe(self,context):
        bundle=self.inner.observe(context)
        facts=dict(bundle.scene.facts)
        details={'status':'unresolved','source':'calibrated_control_images','score_is_probability':False}
        def finish(reason):
            details['reason']=reason;facts['farm_search_visual']=details
            return ObservationBundle(bundle.observation,replace(bundle.scene,facts=facts))
        if bundle.scene.frame_id!=bundle.observation.frame_id:
            return finish('frame_mismatch')
        path=facts.get('image_path')
        if not isinstance(path,str) or facts.get('image_path_source')!='current_capture_artifact':
            return finish('current_image_missing')
        try:
            image=Path(path).resolve()
            if not image.is_relative_to(ROOT/'workspace'):
                return finish('image_outside_workspace')
            capture=json.loads((image.parent/'capture.json').read_text('utf-8'))
            frame=capture['frame']
            if GatherClientBinding.from_window(capture['target'])!=GatherClientBinding.from_window(facts.get('window')):
                return finish('native_process_binding_mismatch')
            if (frame['id']!=bundle.observation.frame_id
                or frame['image_sha256']!=facts.get('image_sha256')
                or [frame['width'],frame['height']]!=list(bundle.observation.window_size)
                or datetime.fromisoformat(frame['captured_at']).timestamp()!=bundle.observation.timestamp
                or any(capture['target'].get(k)!=facts.get('window',{}).get(k)
                    for k in ('hwnd','pid','title','exe'))):
                return finish('capture_scene_mismatch')
            profile=json.loads(self.profile_path.read_text('utf-8'))
            policy=profile['policy'];policy_hash=hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()
            if policy_hash!=profile['policy_sha256']:
                return finish('policy_hash_mismatch')
            matches={};scores={}
            def match(name):
                spec=load_anchor_spec(policy,name)
                calibration=dict(profile['calibrations'][name])
                calibration['template_path']=str(ROOT/calibration['template_path'])
                try:
                    status,target,score=resolve_template(image,capture,calibration,spec,policy_hash,now=self.now())
                except TemplateAnchorError as exc:
                    scores[name]={'status':'refused','reason':str(exc)};return
                scores[name]=score
                if status=='RESOLVED': matches[name]=target
            for name in ('SEARCH_COMPACT','SEARCH_WIDE'): match(name)
            buttons=[t for n,t in matches.items() if n.startswith('SEARCH_')]
            if not buttons:
                details['matches']=scores;return finish('search_control_missing')
            # Multiple search controls at distinct positions are an ambiguous UI.
            if len(buttons)>1 and abs(buttons[0].bbox.center[0]-buttons[1].bbox.center[0])>15:
                details['matches']=scores;return finish('duplicate_search_controls')
            button=buttons[0]
            if not (540<=button.bbox.center[1]<=625 and 300<=button.bbox.center[0]<=1030):
                return finish('search_control_layout_mismatch')
            aligned=[]
            for name,centre in profile['layout']['category_centres'].items():
                match(name)
                target=matches.get(name)
                if target and max(abs(a-b) for a,b in zip(target.bbox.center,centre))<=profile['layout']['maximum_category_offset_px']:
                    aligned.append(name)
            details['matches']=scores
            if len(aligned)<2:return finish('farm_categories_missing')
            details.update(status='matched',frame_id=frame['id'],image_sha256=frame['image_sha256'],
                captured_at=frame['captured_at'],client_size=list(bundle.observation.window_size),
                farm_categories=aligned,policy_sha256=policy_hash,
                calibration_ids={k:profile['calibrations'][k]['calibration_id'] for k in matches})
            facts['farm_search_visual']=details
            evidence=Evidence('farm_control_templates',FARM_SEARCH_EVIDENCE,0.0,
                value=FARM_SEARCH_EVIDENCE,metadata={'frame_id':frame['id'],
                'image_sha256':frame['image_sha256'],'score_is_probability':False,
                'policy_sha256':policy_hash,'farm_categories':tuple(aligned)})
            return ObservationBundle(replace(bundle.observation,evidence=tuple(bundle.observation.evidence)+(evidence,)),
                replace(bundle.scene,facts=facts))
        except (OSError,ValueError,KeyError,TypeError,GatherJobStoreError) as exc:
            return finish('visual_evidence_refused:'+str(exc))
