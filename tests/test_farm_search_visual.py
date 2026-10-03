from dataclasses import replace
from datetime import datetime,timedelta
import hashlib,json,shutil
from pathlib import Path

import pytest

from harness.contracts import Observation
from harness.farm_search_visual import FarmSearchVisualObservationProvider,FARM_SEARCH_EVIDENCE
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.scene_graph import SceneGraph
from harness.state_classifier import StateClassifier

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'workspace/runtime/gather_resource-87d063bc35de06f9/observation-e636a495623843cfaae8259305ce23a4'
CTX=MissionContext('GATHER_RESOURCE','f6w-offline','image-test')

def test_published_profile_contains_hash_bound_templates():
    profile=json.loads((ROOT/'config/farm_search_visual.json').read_text('utf-8'))
    asset_root=(ROOT/'config/assets/farm_search').resolve()
    assert set(profile['calibrations'])=={'SEARCH_COMPACT','SEARCH_WIDE','FOOD','WOOD','STONE','GOLD'}
    for calibration in profile['calibrations'].values():
        path=(ROOT/calibration['template_path']).resolve()
        assert path.is_relative_to(asset_root)
        assert hashlib.sha256(path.read_bytes()).hexdigest()==calibration['template_sha256']


def test_published_templates_recognize_synthetic_panel_without_capture_history(tmp_path):
    """Portable wiring proof, not native/live gameplay evidence."""
    import cv2
    import numpy as np
    from datetime import timezone
    from harness.template_anchors import resolve_template, load_anchor_spec
    profile=json.loads((ROOT/'config/farm_search_visual.json').read_text('utf-8'))
    image=np.zeros((768,1366,3),dtype=np.uint8)
    placements={'SEARCH_COMPACT':(776,578),'FOOD':(507,667),'WOOD':(650,671)}
    for name,(x,y) in placements.items():
        crop=cv2.imread(str(ROOT/profile['calibrations'][name]['template_path']))
        height,width=crop.shape[:2]
        # Preserve the matcher's reflected Laplacian boundary; black padding
        # introduces an artificial edge absent from a standalone crop.
        padded=cv2.copyMakeBorder(crop,2,2,2,2,cv2.BORDER_REFLECT_101)
        image[y-2:y+height+2,x-2:x+width+2]=padded
    current=tmp_path/'current.png'
    assert cv2.imwrite(str(current),image)
    now=datetime.now(timezone.utc)
    capture={'status':'captured','target':{'title':'Rise of Kingdoms','exe':'MASS.exe'},
        'frame':{'id':'synthetic-publication','captured_at':now.isoformat(),
            'width':1366,'height':768,'dpi_scale':1.0,
            'image_sha256':hashlib.sha256(current.read_bytes()).hexdigest()}}
    for name in placements:
        calibration=dict(profile['calibrations'][name])
        calibration['template_path']=str(ROOT/calibration['template_path'])
        status,target,_=resolve_template(current,capture,calibration,
            load_anchor_spec(profile['policy'],name),profile['policy_sha256'],now=now)
        assert status=='RESOLVED' and target is not None
        assert target.metadata['score_is_probability'] is False

@pytest.fixture
def native(tmp_path):
    if not (NATIVE/'current.png').exists():pytest.skip('native evidence is local workspace data')
    # Current image paths must remain under the canonical workspace.
    if not tmp_path.resolve().is_relative_to(ROOT/'workspace'):
        pytest.skip('run native tests with a workspace --basetemp')
    shutil.copyfile(NATIVE/'current.png',tmp_path/'current.png')
    shutil.copyfile(NATIVE/'capture.json',tmp_path/'capture.json')
    return tmp_path

def observed(directory):
    capture=json.loads((directory/'capture.json').read_text('utf-8'));frame=capture['frame']
    now=datetime.fromisoformat(frame['captured_at'])
    observation=Observation(now.timestamp(),frame['id'],(frame['width'],frame['height']),())
    scene=SceneGraph(frame['id'],None,facts={'image_path':str(directory/'current.png'),
        'image_path_source':'current_capture_artifact','image_sha256':frame['image_sha256'],
        'window':capture['target']})
    return ObservationBundle(observation,scene),now

def enrich(bundle,now,profile=None):
    class Stored:
        def observe(self,context):return bundle
    return FarmSearchVisualObservationProvider(Stored(),profile,now=lambda:now).observe(CTX)

def edit_image(directory,edit):
    import cv2
    image=cv2.imread(str(directory/'current.png'));edit(image)
    cv2.imwrite(str(directory/'current.png'),image)
    capture=json.loads((directory/'capture.json').read_text('utf-8'))
    capture['frame']['image_sha256']=hashlib.sha256((directory/'current.png').read_bytes()).hexdigest()
    (directory/'capture.json').write_text(json.dumps(capture),encoding='utf-8')

def test_actual_blocked_search_is_identified_without_any_ocr(native):
    bundle,now=observed(native);result=enrich(bundle,now)
    assert StateClassifier().classify(result.observation,result.scene).state_id=='RESOURCE_SEARCH_PANEL'
    assert len(result.observation.evidence)==1
    item=result.observation.evidence[0]
    assert item.label==FARM_SEARCH_EVIDENCE and item.confidence==0.0
    assert not result.scene.targets
    assert result.scene.facts['farm_search_visual']['score_is_probability'] is False

@pytest.mark.parametrize('fault',['frame','hash','client','process_path','size','timestamp','path_source'])
def test_mismatched_provenance_never_establishes_panel(native,fault):
    bundle,now=observed(native);facts=dict(bundle.scene.facts)
    if fault=='frame':bundle=replace(bundle,scene=replace(bundle.scene,frame_id='other'))
    elif fault=='hash':facts['image_sha256']='0'*64
    elif fault=='client':facts['window']={**facts['window'],'hwnd':1}
    elif fault=='process_path':facts['window']={**facts['window'],'process_path':'C:/other/MASS.exe'}
    elif fault=='size':bundle=replace(bundle,observation=replace(bundle.observation,window_size=(1280,720)))
    elif fault=='timestamp':bundle=replace(bundle,observation=replace(bundle.observation,timestamp=bundle.observation.timestamp-1))
    elif fault=='path_source':facts['image_path_source']='historical_guess'
    bundle=replace(bundle,scene=replace(bundle.scene,facts=facts))
    assert enrich(bundle,now).scene.facts['farm_search_visual']['status']!='matched'

def test_stale_and_wrong_dpi_are_refused(native):
    bundle,now=observed(native)
    assert enrich(bundle,now+timedelta(seconds=31)).scene.facts['farm_search_visual']['status']!='matched'
    capture=json.loads((native/'capture.json').read_text('utf-8'));capture['frame']['dpi_scale']=2.0
    (native/'capture.json').write_text(json.dumps(capture),encoding='utf-8')
    assert enrich(bundle,now).scene.facts['farm_search_visual']['status']!='matched'

def test_button_without_two_farm_icons_is_not_the_panel(native):
    edit_image(native,lambda image:image.__setitem__((slice(650,768),slice(490,1030)),0))
    bundle,now=observed(native)
    assert enrich(bundle,now).scene.facts['farm_search_visual']['status']!='matched'

def test_duplicate_identical_search_buttons_are_ambiguous(native):
    def duplicate(image):image[578:617,450:549]=image[578:617,776:875].copy()
    edit_image(native,duplicate);bundle,now=observed(native)
    assert enrich(bundle,now).scene.facts['farm_search_visual']['status']!='matched'

def test_missing_and_policy_changed_profile_fail_closed(native):
    bundle,now=observed(native)
    assert enrich(bundle,now,native/'absent.json').scene.facts['farm_search_visual']['status']!='matched'
    raw=json.loads((ROOT/'config/farm_search_visual.json').read_text('utf-8'))
    raw['policy']['anchors'][0]['match_threshold']=0.0
    path=native/'changed.json';path.write_text(json.dumps(raw),encoding='utf-8')
    assert enrich(bundle,now,path).scene.facts['farm_search_visual']['status']!='matched'

def test_visual_foreground_suppresses_background_sensors(native):
    from harness.main_view_detector import MainViewProfile,MainViewVisualObservationProvider
    from harness.map_coordinate_provider import MapCoordinateObservationProvider
    bundle,now=observed(native);result=enrich(bundle,now)
    class Stored:
        def observe(self,context):return result
    provider=MapCoordinateObservationProvider(MainViewVisualObservationProvider(Stored(),MainViewProfile(())))
    output=provider.observe(CTX)
    assert output.scene.facts['main_view_detector']['status']=='suppressed'
    assert output.scene.facts['map_coordinate_readout']['status']=='suppressed'
    assert StateClassifier().classify(output.observation,output.scene).state_id=='RESOURCE_SEARCH_PANEL'
