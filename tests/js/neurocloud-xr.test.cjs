const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
function load(overrides={}) {
 const sessions=[];
 class Session extends EventTarget {
  constructor(mode){super();this.mode=mode;this.inputSources=[];this.renderState={};this.ended=false;this.space=new EventTarget();}
  requestReferenceSpace(type){return type==='local-floor'?Promise.reject(new Error('floor unavailable')):Promise.resolve(this.space);}
  updateRenderState(state){Object.assign(this.renderState,state);}
  requestAnimationFrame(callback){this.callback=callback;}
  async end(){this.ended=true;this.dispatchEvent(new Event('end'));}
 }
 const xr=new EventTarget();xr.isSessionSupported=async()=>true;
 xr.requestSession=async mode=>{const session=new Session(mode);sessions.push(session);return session;};
 const calls=[];
 const gl=new Proxy({makeXRCompatible:async()=>{},getShaderParameter:()=>true,getProgramParameter:()=>true,getAttribLocation:()=>0,
  createShader:()=>({}),createProgram:()=>({}),createBuffer:()=>({}),createTexture:()=>({}),createVertexArray:()=>({}),getUniformLocation:()=>({})},
  {get:(o,k)=>k in o?o[k]:typeof k==='string'&&k.toUpperCase()===k?k:(...args)=>calls.push([k,...args])});
 const renderer={gl,nodes:[],edges:[],positions:new Map(),curves:new Map(),frame:0,
  stopAmbientMotion(){},stopActivityMotion(){},requestRender(){},syncAmbientMotion(){},syncActivityMotion(){},setHover(){},renderView(...args){calls.push(['view',...args]);}};
 const context=vm.createContext({console, navigator:{xr},isSecureContext:true,
  document:{createElement:()=>({getContext:()=>({measureText:s=>({width:s.length*12}),fillRect(){},fillText(){}})})},
  cancelAnimationFrame(){},XRWebGLLayer:class{static getNativeFramebufferScaleFactor(){return 1.5;} constructor(session,gl,options){this.options=options;this.fixedFoveation=.8;this.framebuffer='xr-framebuffer';}getViewport(view){return{x:view.eye==='left'?0:500,y:0,width:500,height:500};}},...overrides});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../../web/neurocloud-xr.js'),'utf8'),context);
 return {api:context.EveNeuroCloudXR,context,renderer,sessions,calls};
}
const approx=(a,b)=>a.forEach((n,i)=>assert.ok(Math.abs(n-b[i])<1e-7,`${a} != ${b}`));
test('uniform model inverse preserves position and directions after rotation and scale',()=>{
 const {api:a}=load(),m=a.compose([.4,1.5,-2],.7,-.3,.035),inv=a.inverse(m);
 approx(a.point(inv,a.point(m,[3,-5,7])),[3,-5,7]);
 approx(a.multiply(inv,m),[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]);
});
test('controller ray selects only actual forward claims and relations',()=>{
 const {api:a,renderer:r}=load(),m=a.compose([0,0,0]),ray={origin:[0,0,0],direction:[0,0,-1]};
 r.nodes=[{id:'behind'},{id:'real'}];r.positions.set('behind',[0,0,1]);r.positions.set('real',[0,0,-2]);
 assert.equal(a.pickCloud(r,ray,m).value.id,'real');
 r.nodes=[];r.edges=[{id:'relation'}];r.curves.set('relation',[[-1,0,-2],[1,0,-2]]);
 assert.equal(a.pickCloud(r,ray,m).value.id,'relation');
 assert.equal(a.pickCloud(r,{origin:[0,1,0],direction:[0,0,-1]},m),null);
 const hit=a.pickPanel({origin:[.68,0,0],direction:[0,0,-1]},m);approx([hit.x,hit.y,hit.distance],[.5,.5,1.35]);
 assert.equal(a.pickPanel({origin:[.68,0,0],direction:[0,0,1]},m),null);
});
test('VR to MR ends old session, uses local fallback and restores desktop on end',async()=>{
 const {api:a,renderer:r,sessions}=load(),host=new a.NeuroCloudXR(r);
 await host.detect();await host.start('immersive-vr');const old=sessions[0];
 assert.equal(r.xrSession,old);assert.equal(host.space,old.space);
 await host.start('immersive-ar');assert.equal(old.ended,true);assert.equal(host.session,sessions[1]);
 assert.equal(host.mode,'immersive-ar');await host.end();assert.equal(r.xrSession,null);assert.equal(host.session,null);
 host.dispose();
});
test('MR clears transparent and renders each real eye projection separately',async()=>{
 const {api:a,renderer:r,calls}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-ar');
 const identity=a.compose([0,0,0]);const views=['left','right'].map((eye,i)=>({eye,projectionMatrix:identity,transform:{matrix:a.compose([i*.064,1.6,0]),inverse:{matrix:a.compose([-i*.064,-1.6,0])}}}));
 host.frame(100,{session:host.session,getViewerPose:()=>({transform:{matrix:a.compose([0,1.6,0])},views})});
 assert.ok(calls.some(c=>c[0]==='clearColor'&&c.slice(1).every(x=>x===0)));
 const eyes=calls.filter(c=>c[0]==='view');assert.equal(eyes.length,2);assert.notDeepEqual(eyes[0][2].matrix,eyes[1][2].matrix);
 assert.ok(calls.some(c=>c[0]==='bindFramebuffer'&&c[2]==='xr-framebuffer'));
 await host.end();
});
test('unsupported mode and failed graphics initialization leave no active XR session',async()=>{
 const {api:a,renderer:r,sessions}=load(),host=new a.NeuroCloudXR(r);
 await assert.rejects(host.start('immersive-ar'));
 await host.detect();r.gl.makeXRCompatible=async()=>{throw new Error('context unavailable');};
 await assert.rejects(host.start('immersive-vr'),/context unavailable/);
 assert.equal(host.session,null);assert.equal(r.xrSession,null);assert.equal(sessions[0].ended,true);assert.equal(host.busy,false);
});
test('untrusted or unsupported browser retains desktop and never requests a session',async()=>{
 const {api:a,renderer:r,sessions}=load({isSecureContext:false}),host=new a.NeuroCloudXR(r);
 const support=await host.detect();assert.equal(support['immersive-vr'],false);assert.equal(sessions.length,0);
 await assert.rejects(host.start('immersive-vr'));host.dispose();
});
test('disposing an active session closes it and clears XR before renderer teardown',async()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-vr');
 const session=host.session;host.dispose();assert.equal(r.xrSession,null);assert.equal(r.xrController,null);assert.equal(session.ended,true);
 assert.equal(host.session,null);
});
test('grip translates cloud and thumbsticks rotate and scale without moving the viewer',async()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-vr');
 host.anchor=a.compose([0,0,0]);host.model=a.compose([0,0,-2]);
 const source={handedness:'right',targetRaySpace:{},gripSpace:{},gamepad:{axes:[0,0,.8,.4],buttons:[{}, {pressed:true}]}};
 host.session.inputSources=[source];let position=[0,1,-1];const frame={getPose:()=>({transform:{matrix:a.compose(position)}})};
 host.input(frame,.05);const initial=[...host.offset];position=[.2,1.3,-1.1];host.input(frame,.05);
 approx(host.offset,[initial[0]+.2,initial[1]+.3,initial[2]-.1]);
 source.handedness='left';source.gamepad.axes=[0,0,0,-1];source.gamepad.buttons[1].pressed=false;
 const size=host.size;host.input(frame,.05);assert.ok(host.size>size);assert.equal(host.grab,null);source.handedness='right';source.gamepad.axes=[0,0,.8,.4];host.input(frame,.05);assert.ok(host.yaw>0);assert.ok(host.pitch>0);await host.end();
});
test('disposing while the browser permission request is pending ends the late session',async()=>{
 const fixture=load(),{api:a,renderer:r,context}=fixture,host=new a.NeuroCloudXR(r);await host.detect();
 let finish;context.navigator.xr.requestSession=()=>new Promise(resolve=>{finish=resolve;});
 const starting=host.start('immersive-vr');host.dispose();let ended=false;finish({end:async()=>{ended=true;}});await starting;
 assert.equal(ended,true);assert.equal(host.session,null);assert.equal(r.xrSession,undefined);
});
test('one grip applies controller orientation, releasing and changing hands never jumps',async()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-vr');host.anchor=a.compose([0,0,0]);host.model=host.cloudMatrix();
 const right={handedness:'right',targetRaySpace:{},gripSpace:{},gamepad:{axes:[],buttons:[{}, {pressed:true}]}};
 let matrix=a.compose([0,1,-.6]);const frame={getPose:()=>({transform:{matrix}})};host.session.inputSources=[right];host.input(frame,.01);
 matrix=a.compose([.1,1,-.6],.7,.3);host.input(frame,.01);approx(host.rotation,a.compose([0,0,0],.7,.3));
 const offset=[...host.offset],rotation=[...host.rotation];right.gamepad.buttons[1].pressed=false;host.input(frame,.01);
 matrix=a.compose([1,2,-1],-1,-.5);right.gamepad.buttons[1].pressed=true;host.input(frame,.01);approx(host.rotation,rotation);approx(host.offset,offset);await host.end();
});
test('two grips scale by separation and rotate together with a stable one-hand transition',async()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-vr');host.anchor=a.compose([0,0,0]);host.model=host.cloudMatrix();
 const hands=['left','right'].map(handedness=>({handedness,targetRaySpace:{},gripSpace:{handedness},gamepad:{axes:[],buttons:[{}, {pressed:true}]}}));
 let positions={left:[-.2,0,-1],right:[.2,0,-1]};const frame={getPose:space=>({transform:{matrix:a.compose(positions[space.handedness]||[0,0,0])}})};
 host.session.inputSources=hands;host.input(frame,.01);const size=host.size,center=[...host.offset];
 positions={left:[0,-.4,-1],right:[0,.4,-1]};host.input(frame,.01);
 approx(host.offset,center);assert.ok(host.rotationGuide);assert.ok(host.rotationAxis);assert.ok(Math.abs(host.size-size*2)<1e-8);approx(a.point(host.rotation,[1,0,0],0),[0,1,0]);
 const offset=[...host.offset],rotation=[...host.rotation];hands[0].gamepad.buttons[1].pressed=false;host.input(frame,.01);
 approx(host.rotation,rotation);approx(host.offset,offset);assert.ok(Math.abs(host.size-size*2)<1e-8);await host.end();
});
test('selecting the same claim or empty space clears the selection and detail text',async()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-vr');host.anchor=a.compose([0,0,0]);
 r.selectedClaim='claim:a';r.clearSelection=()=>{r.selectedClaim=null;};
 const source={targetRaySpace:{}};const event={inputSource:source,frame:{getPose:()=>({transform:{matrix:a.compose([0,0,0])}})}};
 host.hit=()=>({kind:'claim',value:{id:'claim:a'}});host.setDetails('Selected claim');host.handleSelect(event);assert.equal(r.selectedClaim,null);assert.equal(host.details,'');
 r.selectedClaim='claim:b';host.hit=()=>null;host.handleSelect(event);assert.equal(r.selectedClaim,null);await host.end();
});
test('XR requests native render scale and antialiasing with foveation disabled',async()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-vr');
 const layer=host.session.renderState.baseLayer;assert.equal(layer.options.antialias,true);assert.equal(layer.options.framebufferScaleFactor,1.5);assert.equal(layer.fixedFoveation,0);
 assert.equal(host.canvas.width,2048);assert.ok(host.offset[2]>-1.3);await host.end();
});
test('panel writes depth before the cloud; controller rays also respect depth',async()=>{
 const {api:a,renderer:r,calls}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-vr');
 const order=[];const panel=host.drawPanel.bind(host),rays=host.drawRays.bind(host);
 host.drawPanel=m=>{order.push('panel');panel(m);};r.renderView=()=>order.push('cloud');host.drawRays=(m,p)=>{order.push('rays');rays(m,p);};
 const matrix=a.compose([0,0,0]);host.frame(100,{session:host.session,getViewerPose:()=>({transform:{matrix},views:[{eye:'left',projectionMatrix:matrix,transform:{matrix,inverse:{matrix}}}]})});
 assert.deepEqual(order,['panel','cloud','rays']);assert.ok(calls.some(c=>c[0]==='depthMask'&&c[1]===true));
 assert.ok(!calls.some(c=>c[0]==='disable'&&c[1]==='DEPTH_TEST'));await host.end();
});
test('ray selection follows the near cloud or the panel in front of a farther cloud',()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);host.anchor=a.compose([0,0,0]);host.model=a.compose([0,0,0]);
 const ray={origin:[.68,0,0],direction:[0,0,-1]};r.nodes=[{id:'actual-claim'}];r.positions.set('actual-claim',[.68,0,-1]);
 assert.equal(host.hit(ray).kind,'claim');r.positions=new Map([['actual-claim',[.68,0,-2]]]);assert.equal(host.hit(ray).kind,'panel');host.dispose();
});

test('a nearer relation also wins over a claim behind the panel',()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);host.anchor=a.compose([0,0,0]);host.model=a.compose([0,0,0]);
 r.nodes=[{id:'far-claim'}];r.positions.set('far-claim',[.68,0,-2]);r.edges=[{id:'near-relation'}];r.curves.set('near-relation',[[.5,0,-1],[.8,0,-1]]);
 const hit=host.hit({origin:[.68,0,0],direction:[0,0,-1]});assert.equal(hit.kind,'relation');assert.equal(hit.value.id,'near-relation');host.dispose();
});
test('spatial picking matches exhaustive picking and skips unrelated geometry',()=>{
 const {api:a,renderer:r}=load();r.nodes=[];r.edges=[];
 for(let i=0;i<1200;i++){const node={id:'n'+i};r.nodes.push(node);r.positions.set(node.id,[(i%20)*.1-1,(Math.floor(i/20)%20)*.1-1,-1-Math.floor(i/400)*.5]);}
 for(let i=0;i<400;i++){const edge={id:'e'+i};r.edges.push(edge);r.curves.set(edge.id,[r.positions.get('n'+i),r.positions.get('n'+(i+1))]);}
 const model=a.compose([.2,0,-.5],.15,.1,.6),inv=a.inverse(model);
 function exhaustive(ray){const local={origin:a.point(inv,ray.origin),direction:a.point(inv,ray.direction,0)};const length=Math.hypot(...local.direction);local.direction=local.direction.map(v=>v/length);let best=null;
  for(const node of r.nodes){const h=a.rayPoint(local,r.positions.get(node.id));if(h.distance>0&&h.gap<.022/.6&&(!best||h.distance<best.distance))best={...h,value:node};}
  for(const edge of r.edges){const c=r.curves.get(edge.id),h=a.raySegment(local,c[0],c[1]);if(h.distance>0&&h.gap<.009/.6&&(!best||h.distance<best.distance))best={...h,value:edge};}return best;}
 let tested=0;
 for(let i=0;i<35;i++){const direction=[Math.sin(i*1.7)*.6,Math.cos(i*.9)*.6,-1],length=Math.hypot(...direction);const ray={origin:[0,0,0],direction:direction.map(v=>v/length)},diag={};
  assert.equal(a.pickCloud(r,ray,model,diag)?.value.id,exhaustive(ray)?.value.id);tested+=diag.tested;}
 assert.ok(tested<35*1600/3,`narrow checks: ${tested}`);
});
test('picking from inside the cloud accepts a claim touching the controller but not a distant one behind',()=>{
 const {api:a,renderer:r}=load(),model=a.compose([0,0,0]);r.nodes=[{id:'touch'},{id:'behind'}];r.positions=new Map([['touch',[0,0,.005]],['behind',[0,0,.2]]]);
 const ray={origin:[0,0,0],direction:[0,0,-1]},hit=a.pickCloud(r,ray,model);assert.equal(hit.value.id,'touch');assert.equal(hit.distance,0);
 r.nodes=[{id:'behind'}];assert.equal(a.pickCloud(r,ray,model),null);
});
test('moving the head into the cloud does not change its world placement or grip baseline',async()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-vr');
 const pose=position=>({session:host.session,getViewerPose:()=>({transform:{matrix:a.compose(position)},views:[]})});
 host.frame(0,pose([0,1.6,0]));const initial=[...host.model];host.frame(16,pose([-.3,1.48,-1.15]));approx(host.model,initial);await host.end();
});
test('title grip moves the panel independently and remains latched when the ray leaves',async()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);await host.detect();await host.start('immersive-vr');host.anchor=a.compose([0,0,0]);host.model=host.cloudMatrix();
 const source={handedness:'right',targetRaySpace:{},gripSpace:{},gamepad:{axes:[],buttons:[{}, {pressed:true}]}};
 host.session.inputSources=[source];let grip=[.68,.44,-.35],ray=[...grip];
 const frame={getPose:space=>({transform:{matrix:a.compose(space===source.gripSpace?grip:ray)}})};
 const cloud=[...host.offset],panel=[...host.panelOffset];host.input(frame,.01);
 grip=[.98,.64,-.55];ray=[4,4,0];host.input(frame,.01);
 approx(host.panelOffset,[panel[0]+.3,panel[1]+.2,panel[2]-.2]);approx(host.offset,cloud);assert.equal(host.rotationGuide,false);
 const hit=a.pickPanel({origin:[host.panelOffset[0],host.panelOffset[1],0],direction:[0,0,-1]},host.anchor,host.panelTransform());approx([hit.x,hit.y],[.5,.5]);
 source.gamepad.buttons[1].pressed=false;host.input(frame,.01);assert.equal(host.panelGrab,null);
 source.gamepad.buttons[1].pressed=true;host.input(frame,.01);assert.equal(host.gripTargets.get(source),'cloud');await host.end();
});
test('inspector preserves headings, badges, metadata and evidence cards in the panel',()=>{
 const {api:a,renderer:r}=load(),host=new a.NeuroCloudXR(r);
 const el=(tagName,text,children=[],classes=[])=>({tagName,innerText:text,textContent:text,children,classList:{contains:s=>classes.includes(s)},getAttribute:()=>null});
 const root=el('DIV','Claim details',[el('H2','Claim heading'),el('P','fact · active',[],['memory-claim-badges']),el('DL','Scope user:self',[el('DT','Scope'),el('DD','user:self')]),el('ARTICLE','Evidence',[el('STRONG','Evidence'),el('P','Quoted evidence')])]);
 host.setInspector(root);const rows=host.panelRows();assert.ok(rows.some(row=>row.kind==='title'&&row.text==='Claim heading'));assert.ok(rows.some(row=>row.kind==='badge'));assert.ok(rows.some(row=>row.kind==='field'&&row.text==='user:self'));assert.ok(rows.some(row=>row.card&&row.text==='Quoted evidence'));assert.notEqual(rows.find(row=>row.kind==='title').font,rows.find(row=>row.kind==='field').font);
});
