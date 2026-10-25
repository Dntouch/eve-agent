import ctypes
import ctypes.util
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RENDERER_PATH = PROJECT_ROOT / "web" / "vendor" / "neurocloud-webgl-v1.js"


class NeuroCloudPureRendererTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        library_path = ctypes.util.find_library("javascriptcoregtk-4.1")
        if not library_path:
            raise unittest.SkipTest("JavaScriptCore ist für reine Renderer-Vertragstests nicht verfügbar")
        cls.library = ctypes.CDLL(library_path)
        signatures = {
            "JSGlobalContextCreate": (ctypes.c_void_p, [ctypes.c_void_p]),
            "JSGlobalContextRelease": (None, [ctypes.c_void_p]),
            "JSStringCreateWithUTF8CString": (ctypes.c_void_p, [ctypes.c_char_p]),
            "JSStringRelease": (None, [ctypes.c_void_p]),
            "JSEvaluateScript": (
                ctypes.c_void_p,
                [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                 ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
            ),
            "JSValueToStringCopy": (
                ctypes.c_void_p,
                [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
            ),
            "JSStringGetMaximumUTF8CStringSize": (ctypes.c_size_t, [ctypes.c_void_p]),
            "JSStringGetUTF8CString": (
                ctypes.c_size_t, [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t],
            ),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(cls.library, name)
            function.restype = result
            function.argtypes = arguments
        cls.source = RENDERER_PATH.read_text(encoding="utf-8")

    def evaluate(self, expression):
        library = self.library
        context = library.JSGlobalContextCreate(None)
        script = library.JSStringCreateWithUTF8CString(
            ("var window={};" + self.source + "\nJSON.stringify(" + expression + ");").encode(),
        )
        exception = ctypes.c_void_p()
        try:
            value = library.JSEvaluateScript(
                context, script, None, None, 1, ctypes.byref(exception),
            )
            if exception.value:
                value = exception.value
            text = library.JSValueToStringCopy(context, value, None)
            try:
                size = library.JSStringGetMaximumUTF8CStringSize(text)
                buffer = ctypes.create_string_buffer(size)
                library.JSStringGetUTF8CString(text, buffer, size)
                decoded = buffer.value.decode()
            finally:
                library.JSStringRelease(text)
        finally:
            library.JSStringRelease(script)
            library.JSGlobalContextRelease(context)
        try:
            return json.loads(decoded)
        except json.JSONDecodeError as error:
            self.fail(f"JavaScriptCore-Auswertung fehlgeschlagen: {decoded} ({error})")

    @staticmethod
    def fixture_expression(body):
        nodes = [
            {"id": "claim:a", "scope": "scope:one", "created_at": "2026-01-01"},
            {"id": "claim:b", "scope": "scope:one", "created_at": "2026-01-02"},
            {"id": "claim:c", "scope": "scope:two", "created_at": "2026-01-03"},
        ]
        edges = [{
            "id": "memory-relation:relation-a", "relation_id": "relation-a",
            "from_claim_id": "claim:a", "to_claim_id": "claim:b",
        }]
        return f"(()=>{{const nodes={json.dumps(nodes)},edges={json.dumps(edges)};{body}}})()"

    def test_desktop_render_entry_uses_canvas_viewport_without_an_xr_session(self):
        result = self.evaluate("""(()=>{
          globalThis.devicePixelRatio=2;globalThis.performance={now:()=>0};
          const calls=[],gl=new Proxy({}, {get:()=>()=>{}});
          const renderer=Object.create(window.EveNeuroCloud.NeuroCloudRenderer.prototype);
          Object.assign(renderer,{visible:true,supported:true,gl,canvas:{clientWidth:640,clientHeight:360},
            camera:{fieldOfView:.82,target:[0,0,0]},quality:()=>({pixelRatio:1.5}),
            pruneActivityImpulses:()=>{},blend:()=>{},cameraBasis:()=>({eye:[0,0,20],right:[1,0,0],up:[0,1,0]}),
            renderView:(time,view)=>calls.push({time,...view})});
          renderer.render(10);renderer.xrSession={};renderer.render(20);
          return {calls,canvas:renderer.canvas};
        })()""")
        self.assertEqual(1, len(result['calls']))
        self.assertEqual({'x': 0, 'y': 0, 'width': 960, 'height': 540}, result['calls'][0]['viewport'])
        self.assertEqual(16, len(result['calls'][0]['matrix']))
        self.assertEqual(960, result['canvas']['width'])
        self.assertEqual(540, result['canvas']['height'])

    def test_layout_and_neuron_variation_are_deterministic_without_extra_nodes(self):
        result = self.evaluate(self.fixture_expression(
            "const first=window.EveNeuroCloud.layoutGraph(nodes,edges);"
            "const second=window.EveNeuroCloud.layoutGraph(nodes,edges);"
            "const lookA=window.EveNeuroCloud.neuronAppearance('claim:a');"
            "const lookB=window.EveNeuroCloud.neuronAppearance('claim:b');"
            "return {same:JSON.stringify(Array.from(first.positions))===JSON.stringify(Array.from(second.positions)),"
            "ids:Array.from(first.positions.keys()),lookStable:JSON.stringify(lookA)===JSON.stringify(window.EveNeuroCloud.neuronAppearance('claim:a')),lookDifferent:JSON.stringify(lookA)!==JSON.stringify(lookB)};",
        ))
        self.assertTrue(result["same"])
        self.assertEqual(["claim:a", "claim:b", "claim:c"], result["ids"])
        self.assertTrue(result["lookStable"])
        self.assertTrue(result["lookDifferent"])

    def test_brain_shape_is_deterministic_and_only_deforms_real_positions(self):
        result = self.evaluate("""(()=>{const positions=new Map([
          ['left',[-1,0,0]],['right',[1,0,0]],
          ['upper-left',[-.8,1,0]],['lower-left',[-.8,-1,0]],
          ['middle-left',[-.05,0,.2]],['middle-right',[.05,0,-.2]]
        ]),before=JSON.stringify(Array.from(positions)),first=window.EveNeuroCloud.shapePositions(positions,'brain'),second=window.EveNeuroCloud.shapePositions(positions,'brain'),organic=window.EveNeuroCloud.shapePositions(positions,'organic');return{
          stable:JSON.stringify(Array.from(first))===JSON.stringify(Array.from(second)),
          sourceUntouched:before===JSON.stringify(Array.from(positions)),
          ids:Array.from(first.keys()),organic:Array.from(organic),
          left:first.get('left')[0],right:first.get('right')[0],
          centerGap:first.get('middle-right')[0]-first.get('middle-left')[0],
          upperWidth:Math.abs(first.get('upper-left')[0]),lowerWidth:Math.abs(first.get('lower-left')[0])
        };})()""")
        self.assertTrue(result["stable"])
        self.assertTrue(result["sourceUntouched"])
        self.assertEqual(
            ["left", "right", "upper-left", "lower-left", "middle-left", "middle-right"],
            result["ids"],
        )
        self.assertEqual(6, len(result["organic"]))
        self.assertLess(result["left"], 0)
        self.assertGreater(result["right"], 0)
        self.assertGreater(result["centerGap"], 0)
        self.assertLess(result["centerGap"], 1.2)
        self.assertGreater(result["upperWidth"], result["lowerWidth"])
        self.assertNotIn("brain-hemisphere", self.source)
        self.assertNotIn("const cleft", self.source)

    def test_relation_curve_is_deterministic_curved_and_keeps_real_endpoints(self):
        result = self.evaluate(self.fixture_expression(
            "const layout=window.EveNeuroCloud.layoutGraph(nodes,edges);"
            "const first=window.EveNeuroCloud.relationCurve(edges[0],layout.positions,10);"
            "const second=window.EveNeuroCloud.relationCurve(edges[0],layout.positions,10);"
            "const start=layout.positions.get(edges[0].from_claim_id),end=layout.positions.get(edges[0].to_claim_id),mid=first[5],linear=start.map((value,index)=>(value+end[index])/2);"
            "return {same:JSON.stringify(first)===JSON.stringify(second),count:first.length,start:first[0],end:first[first.length-1],expectedStart:start,expectedEnd:end,curvature:Math.hypot(...mid.map((value,index)=>value-linear[index]))};",
        ))
        self.assertTrue(result["same"])
        self.assertEqual(11, result["count"])
        self.assertEqual(result["expectedStart"], result["start"])
        self.assertEqual(result["expectedEnd"], result["end"])
        self.assertGreater(result["curvature"], 0.01)

    def test_fog_layers_require_and_reference_real_claims(self):
        result = self.evaluate(self.fixture_expression(
            "const layout=window.EveNeuroCloud.layoutGraph(nodes,edges);"
            "const known=new Set(nodes.map(node=>node.id));"
            "return {count:layout.fog.length,allReal:layout.fog.every(region=>region.claim_ids.length>=1&&region.claim_ids.every(id=>known.has(id))),scopes:Array.from(new Set(layout.fog.map(region=>region.scope)))};",
        ))
        self.assertGreaterEqual(result["count"], 2)
        self.assertTrue(result["allReal"])
        self.assertEqual(["scope:one", "scope:two"], result["scopes"])

    def test_claim_selection_highlights_two_persisted_hops_and_nothing_beyond(self):
        result = self.evaluate(
            "(()=>{const edges=["
            "{id:'r1',from_claim_id:'claim:a',to_claim_id:'claim:b'},"
            "{id:'r2',from_claim_id:'claim:b',to_claim_id:'claim:c'},"
            "{id:'r3',from_claim_id:'claim:d',to_claim_id:'claim:a'},"
            "{id:'r4',from_claim_id:'claim:c',to_claim_id:'claim:e'},"
            "{id:'r5',from_claim_id:'claim:x',to_claim_id:'claim:y'}];"
            "const selected=window.EveNeuroCloud.selectionNeighborhood('claim:a',edges);"
            "return {claims:Array.from(selected.claimIds).sort(),relations:Array.from(selected.relationIds).sort(),"
            "claimHops:Array.from(selected.claimHops).sort(),relationHops:Array.from(selected.relationHops).sort()};})()"
        )
        self.assertEqual(["claim:a", "claim:b", "claim:c", "claim:d"], result["claims"])
        self.assertEqual(["r1", "r2", "r3"], result["relations"])
        self.assertEqual(
            [["claim:a", 0], ["claim:b", 1], ["claim:c", 2], ["claim:d", 1]],
            result["claimHops"],
        )
        self.assertEqual([["r1", 1], ["r2", 2], ["r3", 1]], result["relationHops"])

    def test_runtime_projection_requires_event_identity_and_deduplicates_stages(self):
        result = self.evaluate("""(()=>{const common={turn_id:'turn:t1',claim_ids:['claim:a'],compiler_evaluation_id:'eval-1',consumer:'planner',event_status:'completed'};const events=[
          {...common,event_id:'runtime-event:e1',event_kind:'claim_retrieved'},
          {...common,event_id:'runtime-event:e2',event_kind:'claim_returned_to_consumer'},
          {...common,event_id:'runtime-event:e3',event_kind:'claim_retrieved'},
          {...common,event_id:'',event_kind:'claim_retrieved'},
          {...common,event_id:'runtime-event:other',turn_id:'turn:t2',event_kind:'claim_retrieved'},
          {event_id:'runtime-event:r1',turn_id:'turn:t1',event_kind:'relation_traversed_for_retrieval',relation_id:'memory-relation:r',compiler_evaluation_id:'eval-1',consumer:'planner',event_status:'completed'},
          {event_id:'runtime-event:r2',turn_id:'turn:t1',event_kind:'relation_bound_to_plan',relation_id:'memory-relation:r',planner_round_id:'round-2',plan_id:'plan-2',event_status:'failed'}
        ];const pattern=window.EveNeuroCloud.projectRuntimeActivity(events,{turnId:'t1',complete:true});return{pattern,claimVisual:window.EveNeuroCloud.activityVisual(pattern,'claim','claim:a','all'),relationVisual:window.EveNeuroCloud.activityVisual(pattern,'relation','memory-relation:r','all')};})()""")
        self.assertEqual(5, len(result["pattern"]["events"]))
        self.assertEqual(1, result["pattern"]["claims"]["claim:a"]["categories"]["retrieval"]["count"])
        self.assertEqual(2, result["pattern"]["relations"]["memory-relation:r"]["categories"]["relations"]["count"])
        self.assertEqual("failed", result["relationVisual"]["status"])
        self.assertTrue(result["pattern"]["complete"])

    def test_runtime_projection_keeps_real_attempts_but_not_duplicate_action_stages(self):
        result = self.evaluate("""(()=>{const base={turn_id:'turn:t1',claim_ids:['claim:a'],action_id:'action-1',event_status:'completed'};const events=[
          {...base,event_id:'runtime-event:a0',event_kind:'claim_bound_to_action'},
          {...base,event_id:'runtime-event:a1',event_kind:'action_dispatch_attempted_with_claim',attempt_id:'attempt-1'},
          {...base,event_id:'runtime-event:a2',event_kind:'action_provider_response_with_claim',attempt_id:'attempt-1'},
          {...base,event_id:'runtime-event:a3',event_kind:'action_dispatch_attempted_with_claim',attempt_id:'attempt-2'},
          {...base,event_id:'runtime-event:a4',event_kind:'action_completed_with_claim',outcome_status:'success'}
        ];return window.EveNeuroCloud.projectRuntimeActivity(events,{turnId:'t1',complete:true});})()""")
        group = result["claims"]["claim:a"]["categories"]["actions"]
        self.assertEqual(2, group["count"])
        self.assertEqual(5, len(group["event_ids"]))

    def test_runtime_projection_separates_turns_categories_statuses_and_real_operations(self):
        result = self.evaluate("""(()=>{const events=[
          {event_id:'runtime-event:r1',turn_id:'turn:one',event_kind:'claim_retrieved',claim_ids:['claim:a'],compiler_evaluation_id:'eval-1',consumer:'planner',event_status:'completed'},
          {event_id:'runtime-event:r2',turn_id:'turn:one',event_kind:'claim_retrieved',claim_ids:['claim:a'],compiler_evaluation_id:'eval-2',consumer:'planner',event_status:'completed'},
          {event_id:'runtime-event:p1',turn_id:'turn:one',event_kind:'claim_bound_to_plan',claim_ids:['claim:a'],planner_round_id:'round-1',plan_id:'plan-1',operation_id:'plan-op-1',event_status:'cancelled'},
          {event_id:'runtime-event:a1',turn_id:'turn:one',event_kind:'action_completed_with_claim',claim_ids:['claim:b'],action_id:'action-1',attempt_id:'attempt-1',event_status:'failed',outcome_status:'error'},
          {event_id:'runtime-event:other',turn_id:'turn:two',event_kind:'claim_retrieved',claim_ids:['claim:c'],compiler_evaluation_id:'eval-3',consumer:'planner',event_status:'completed'}
        ];const one=window.EveNeuroCloud.projectRuntimeActivity(events,{turnId:'one',complete:false}),two=window.EveNeuroCloud.projectRuntimeActivity(events,{turnId:'two',complete:true}),empty=window.EveNeuroCloud.projectRuntimeActivity([],{turnId:'empty',complete:false});return{one,two,empty,retrieval:window.EveNeuroCloud.activityVisual(one,'claim','claim:a','retrieval'),all:window.EveNeuroCloud.activityVisual(one,'claim','claim:a','all'),action:window.EveNeuroCloud.activityVisual(one,'claim','claim:b','actions')};})()""")
        self.assertEqual(2, result["retrieval"]["count"])
        self.assertGreater(result["retrieval"]["intensity"], .32)
        self.assertEqual(2, result["all"]["count"])
        self.assertEqual("cancelled", result["all"]["status"])
        self.assertEqual("failed", result["action"]["status"])
        self.assertEqual(["claim:c"], list(result["two"]["claims"]))
        self.assertFalse(result["one"]["complete"])
        self.assertEqual({}, result["empty"]["claims"])
        self.assertFalse(result["empty"]["complete"])

    def test_relation_activity_never_invents_edges_or_directions(self):
        result = self.evaluate("""(()=>{const events=[
          {event_id:'runtime-event:ok',turn_id:'turn:t',event_kind:'relation_traversed_for_retrieval',relation_id:'memory-relation:stored',compiler_evaluation_id:'eval',consumer:'planner',event_status:'completed'},
          {event_id:'runtime-event:not-allowed',turn_id:'turn:t',event_kind:'relation_stored',relation_id:'memory-relation:stored',event_status:'completed'},
          {event_id:'runtime-event:no-relation',turn_id:'turn:t',event_kind:'relation_bound_to_plan',planner_round_id:'round',plan_id:'plan',event_status:'completed'}
        ];return window.EveNeuroCloud.projectRuntimeActivity(events,{turnId:'t',complete:true});})()""")
        self.assertEqual(["memory-relation:stored"], list(result["relations"]))
        self.assertEqual(1, len(result["events"]))
        self.assertNotIn("from_claim_id", result["events"][0])
        self.assertNotIn("to_claim_id", result["events"][0])

    def test_renderer_has_no_random_or_fake_activity_loop(self):
        self.assertNotIn("Math.random", self.source)
        self.assertNotIn("setInterval", self.source)
        self.assertNotIn("fetch(", self.source)
        self.assertNotIn("WebSocket", self.source)
        self.assertIn("requestRender()", self.source)
        self.assertIn("ambientAllowed()", self.source)
        self.assertIn("prefers-reduced-motion: reduce", self.source)
        self.assertIn("this.camera.yaw-=this.autoRotateSpeed", self.source)
        self.assertIn("this.stopAmbientMotion()", self.source)
        self.assertIn("this.continuousAmbientMotion", self.source)
        self.assertIn("this.depthMotion", self.source)
        self.assertIn('this.orbitMode=options.orbitMode==="sway"?"sway":"rotate"', self.source)
        self.assertIn('if(this.orbitMode==="sway")', self.source)
        self.assertIn("this.camera.yaw=this.baseCameraYaw+Math.sin(phase)*.16", self.source)
        self.assertIn("this.camera.target=[0,Math.sin(phase*.68)*.3,Math.sin(phase*.49)*.2]", self.source)
        self.assertIn("this.densityAwareExposure", self.source)
        self.assertIn("this.densityReference", self.source)
        self.assertIn("Math.sqrt(this.densityReference/this.nodes.length)", self.source)
        self.assertIn("this.relationStrength", self.source)
        self.assertIn("densityRelationExposure*this.relationStrength", self.source)
        self.assertIn("this.activityTimeScale", self.source)
        self.assertIn("(clock-impulseStart)/activityTimeScale", self.source)
        self.assertIn("2.9*this.activityTimeScale", self.source)
        self.assertIn("this.boundedBaseBlend", self.source)
        self.assertIn("this.transparentBackground", self.source)
        self.assertIn("this.transparentBackground?0:1", self.source)
        self.assertIn("gl.ONE_MINUS_SRC_ALPHA", self.source)
        self.assertIn("gl.depthMask(this.boundedBaseBlend&&pass===0)", self.source)
        self.assertIn("if(haloPass<.5&&alpha<.075)discard", self.source)
        self.assertIn("relationExposure", self.source)
        self.assertIn("Math.sqrt(36/Math.max(1,this.edges.length))", self.source)
        self.assertIn("this.camera.target=[Math.sin", self.source)
        self.assertIn("cancelAnimationFrame", self.source)
        self.assertIn("deleteBuffer", self.source)

    def test_layout_separates_provider_and_internal_provenance_without_inventing_edges(self):
        result = self.evaluate("""(()=>{const nodes=[
          {id:'ha:light',scope:'provider:home-assistant:demo',claim_kind:'provider_binding'},
          {id:'ha:cover',scope:'provider:home-assistant:demo',claim_kind:'provider_binding'},
          {id:'eve:phrase',scope:'semantic_links',claim_kind:'opaque_fact'},
          {id:'eve:action',scope:'semantic_actions',claim_kind:'opaque_fact'}
        ];const layout=window.EveNeuroCloud.layoutGraph(nodes,[]);return {
          providerRegion:window.EveNeuroCloud.provenanceRegion(nodes[0]),
          internalRegion:window.EveNeuroCloud.provenanceRegion(nodes[2]),
          providerX:(layout.positions.get('ha:light')[0]+layout.positions.get('ha:cover')[0])/2,
          internalX:(layout.positions.get('eve:phrase')[0]+layout.positions.get('eve:action')[0])/2,
          regions:layout.regions
        };})()""")
        self.assertEqual("provider:home-assistant", result["providerRegion"])
        self.assertEqual("eve-internal", result["internalRegion"])
        self.assertGreater(result["providerX"] / (4 / 460) ** (1 / 3), 2)
        self.assertLess(result["internalX"] / (4 / 460) ** (1 / 3), -2)
        self.assertEqual(2, result["regions"])

    def test_logo_palette_colors_are_derived_from_real_claim_metadata(self):
        result = self.evaluate("""(()=>({
          provider:window.EveNeuroCloud.colorFor({scope:'provider:home-assistant:demo',claim_kind:'provider_binding',lifecycle:'active'}),
          action:window.EveNeuroCloud.colorFor({scope:'semantic_actions',claim_kind:'opaque_fact',lifecycle:'active'}),
          phrase:window.EveNeuroCloud.colorFor({scope:'semantic_links',claim_kind:'opaque_fact',lifecycle:'active'}),
          language:window.EveNeuroCloud.colorFor({scope:'semantic_language_relations',claim_kind:'opaque_fact',lifecycle:'active'}),
          invalid:window.EveNeuroCloud.colorFor({scope:'semantic_links',claim_kind:'opaque_fact',lifecycle:'invalid'})
        }))()""")
        self.assertNotEqual(result["provider"], result["action"])
        self.assertNotEqual(result["action"], result["phrase"])
        self.assertNotEqual(result["phrase"], result["language"])
        self.assertLess(sum(result["invalid"]), sum(result["phrase"]))


if __name__ == "__main__":
    unittest.main()
