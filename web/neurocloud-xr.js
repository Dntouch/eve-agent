/* Optional WebXR presentation of the existing, persistent NeuroCloud. No remote assets. */
(() => {
  "use strict";
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const add = (a, b) => a.map((v, i) => v + b[i]);
  const sub = (a, b) => a.map((v, i) => v - b[i]);
  const scale = (a, s) => a.map(v => v * s);
  const dot = (a, b) => a.reduce((n, v, i) => n + v * b[i], 0);
  const norm = a => scale(a, 1 / (Math.hypot(...a) || 1));
  const identity = () => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  function multiply(a, b) {
    const out = Array(16).fill(0);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) out[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
    return out;
  }
  function point(m, p, w = 1) {
    return [0, 1, 2].map(i => m[i] * p[0] + m[i + 4] * p[1] + m[i + 8] * p[2] + m[i + 12] * w);
  }
  function compose(position, yaw = 0, pitch = 0, size = 1) {
    const y = Math.cos(yaw), s = Math.sin(yaw), p = Math.cos(pitch), t = Math.sin(pitch);
    return [y * size, 0, -s * size, 0, s * t * size, p * size, y * t * size, 0,
      s * p * size, -t * size, y * p * size, 0, ...position, 1];
  }
  // Inverse of a translation/rotation/uniform-scale transform (never a projection).
  function inverse(m) {
    const squared = m[0] ** 2 + m[1] ** 2 + m[2] ** 2;
    const out = identity();
    for (let c = 0; c < 3; c++) for (let r = 0; r < 3; r++) out[c * 4 + r] = m[r * 4 + c] / squared;
    const t = point(out, m.slice(12, 15), 0);
    out.splice(12, 3, ...scale(t, -1));
    return out;
  }
  function rotationOf(matrix) { const r = Array.from(matrix); r[12] = r[13] = r[14] = 0; return r; }
  function between(a, b) {
    a = norm(a); b = norm(b); const d = clamp(dot(a, b), -1, 1);
    let q = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0], 1+d];
    if (d < -.999999) { const axis = Math.abs(a[0]) < .8 ? [1,0,0] : [0,1,0]; q = [a[1]*axis[2]-a[2]*axis[1],a[2]*axis[0]-a[0]*axis[2],a[0]*axis[1]-a[1]*axis[0],0]; }
    const length = Math.hypot(...q); const [x,y,z,w] = q.map(v=>v/length);
    return [1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w),0,2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w),0,2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y),0,0,0,0,1];
  }
  const CLOUD_OFFSET = [-.3, -.12, -1.15];
  function rayFromPose(pose) {
    const m = pose.transform.matrix;
    return { origin: Array.from(m.slice(12, 15)), direction: norm([-m[8], -m[9], -m[10]]) };
  }
  function rayPoint(ray, p) {
    const distance = dot(sub(p, ray.origin), ray.direction);
    return { distance, gap: Math.hypot(...sub(p, add(ray.origin, scale(ray.direction, Math.max(0, distance))))) };
  }
  function raySegment(ray, a, b) {
    const v = sub(b, a), w = sub(ray.origin, a), vv = dot(v, v), dv = dot(ray.direction, v);
    const denominator = vv - dv * dv;
    let along = denominator > 1e-10 ? (dot(v, w) - dv * dot(ray.direction, w)) / denominator : 0;
    along = clamp(along, 0, 1);
    let p = add(a, scale(v, along)), distance = dot(sub(p, ray.origin), ray.direction);
    if (distance < 0) { along = clamp(dot(sub(ray.origin, a), v) / (vv || 1), 0, 1); p = add(a, scale(v, along)); distance = 0; }
    return { distance, gap: Math.hypot(...sub(p, add(ray.origin, scale(ray.direction, distance)))) };
  }
  const pickIndexes = new WeakMap();
  function buildPickIndex(renderer) {
    const items = [];
    for (const value of renderer.nodes) {
      const a = renderer.positions.get(value.id); if (!a) continue;
      items.push({kind:"claim",value,a,min:a,max:a});
    }
    for (const value of renderer.edges) {
      const curve = renderer.curves.get(value.id) || [];
      for (let i=1;i<curve.length;i++) {
        const a=curve[i-1],b=curve[i];
        items.push({kind:"relation",value,a,b,min:a.map((v,k)=>Math.min(v,b[k])),max:a.map((v,k)=>Math.max(v,b[k]))});
      }
    }
    function branch(items) {
      if (!items.length) return null;
      const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
      for (const item of items) for(let k=0;k<3;k++){min[k]=Math.min(min[k],item.min[k]);max[k]=Math.max(max[k],item.max[k]);}
      if(items.length<=12)return {min,max,items};
      const widths=max.map((v,k)=>v-min[k]),axis=widths.indexOf(Math.max(...widths));
      items.sort((a,b)=>(a.min[axis]+a.max[axis])-(b.min[axis]+b.max[axis]));
      const middle=items.length>>1;
      return {min,max,left:branch(items.slice(0,middle)),right:branch(items.slice(middle))};
    }
    return branch(items);
  }
  function intersectsBox(ray, box, padding, distance) {
    let near=0,far=distance;
    for(let k=0;k<3;k++){
      const lo=box.min[k]-padding,hi=box.max[k]+padding,o=ray.origin[k],d=ray.direction[k];
      if(Math.abs(d)<1e-12){if(o<lo||o>hi)return false;continue;}
      let a=(lo-o)/d,b=(hi-o)/d;if(a>b)[a,b]=[b,a];near=Math.max(near,a);far=Math.min(far,b);if(near>far)return false;
    }
    return true;
  }
  function pickCloud(renderer, ray, model, diagnostics) {
    const inv=inverse(model),size=Math.hypot(model[0],model[1],model[2]);
    ray={origin:point(inv,ray.origin),direction:norm(point(inv,ray.direction,0))};
    let cached=pickIndexes.get(renderer);
    if(!cached||cached.positions!==renderer.positions||cached.curves!==renderer.curves||cached.nodes!==renderer.nodes||cached.edges!==renderer.edges){
      cached={positions:renderer.positions,curves:renderer.curves,nodes:renderer.nodes,edges:renderer.edges,root:buildPickIndex(renderer)};
      pickIndexes.set(renderer,cached);
    }
    const stack=cached.root?[cached.root]:[];let best=null,tested=0;
    while(stack.length){
      const node=stack.pop();if(!intersectsBox(ray,node,.022/size,best?.distance??Infinity))continue;
      if(!node.items){stack.push(node.right,node.left);continue;}
      for(const item of node.items){
        tested++;
        const hit=item.kind==="claim"?rayPoint(ray,item.a):raySegment(ray,item.a,item.b);
        if(hit.distance<0&&hit.gap<(item.kind==="claim"?.022:.009)/size)hit.distance=0;
        if(hit.distance>=0&&hit.gap<(item.kind==="claim"?.022:.009)/size&&(!best||hit.distance<best.distance||(hit.distance===best.distance&&item.kind==="claim"&&best.kind==="relation")))best={...hit,kind:item.kind,value:item.value};
      }
    }
    if(diagnostics)diagnostics.tested=tested;
    return best?{...best,distance:best.distance*size}:null;
  }
  const PANEL = { position: [.68, 0, -1.35], width: .86, height: 1.04 };
  function pickPanel(ray, anchor, panelTransform = compose(PANEL.position)) {
    const inv = inverse(multiply(anchor,panelTransform)), origin = point(inv,ray.origin), direction = point(inv,ray.direction,0);
    if (Math.abs(direction[2]) < 1e-6) return null;
    const t=-origin[2]/direction[2];if(t<=0)return null;
    const p=add(origin,scale(direction,t)),x=p[0]/PANEL.width+.5,y=.5-p[1]/PANEL.height;
    return x>=0&&x<=1&&y>=0&&y<=1?{x,y,distance:t,kind:"panel"}:null;
  }
  function inspectorBlocks(root) {
    const blocks=[];
    function visit(node,card=false){
      if(node.hidden||node.getAttribute?.("aria-hidden")==="true")return;
      const tag=node.tagName,children=Array.from(node.children||[]),text=(node.innerText||node.textContent||"").trim();
      if(!text)return;
      if(tag==="DETAILS"&&!node.open){const summary=children.find(n=>n.tagName==="SUMMARY");if(summary)blocks.push({kind:"label",text:summary.textContent,card});return;}
      if(tag==="DL"){
        for(let i=0;i<children.length;i++)if(children[i].tagName==="DT"){
          blocks.push({kind:"label",text:children[i].textContent,card});
          if(children[i+1]?.tagName==="DD")blocks.push({kind:"field",text:children[++i].textContent,card});
        }return;
      }
      let kind=tag==="H2"?"title":/H[34]/.test(tag||"")?"section":tag==="STRONG"?"section":tag==="PRE"?"code":tag==="BUTTON"?"action":null;
      if(node.classList?.contains("eyebrow"))kind="label";
      if(node.classList?.contains("memory-claim-badges")||node.classList?.contains("memory-provenance")||node.classList?.contains("memory-runtime-badges"))kind="badge";
      if(kind||!children.length||tag==="P"){blocks.push({kind:kind||"body",text,card});return;}
      children.forEach(child=>visit(child,card||tag==="ARTICLE"));
    }
    visit(root);return blocks;
  }
  function wrapText(context, text, width) {
    const lines = [];
    for (const paragraph of String(text || "").split(/\r?\n/)) {
      let line = "";
      for (const word of paragraph.split(/\s+/).filter(Boolean)) {
        if (line && context.measureText(line + " " + word).width > width) { lines.push(line); line = ""; }
        // IDs/URLs also wrap, so long unbroken strings stay on the panel.
        for (const char of (line ? " " : "") + word) {
          if (context.measureText(line + char).width > width) { lines.push(line); line = ""; }
          line += char;
        }
      }
      lines.push(line);
    }
    return lines;
  }
  function program(gl, vertex, fragment) {
    const shaders = [];
    try {
      for (const [type, source] of [[gl.VERTEX_SHADER, vertex], [gl.FRAGMENT_SHADER, fragment]]) {
        const shader = gl.createShader(type); shaders.push(shader); gl.shaderSource(shader, source); gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
      }
      const p = gl.createProgram(); shaders.forEach(s => gl.attachShader(p, s)); gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) { const message = gl.getProgramInfoLog(p); gl.deleteProgram(p); throw new Error(message); }
      return p;
    } finally { shaders.forEach(s => gl.deleteShader(s)); }
  }

  class NeuroCloudXR {
    constructor(renderer, options = {}) {
      this.renderer = renderer; this.options = options; this.session = null; this.busy = false; this.disposed = false;
      this.support = { "immersive-vr": false, "immersive-ar": false }; this.page = 0; this.details = ""; this.panelOffset=[...PANEL.position];this.panelGrab=null;this.gripTargets=new WeakMap();
      this.select = event => this.handleSelect(event);
      this.resetReference = () => { this.anchor = null; this.grab = null; };
      this.change = () => this.detect().catch(error => this.notify(error.message));
      navigator.xr?.addEventListener("devicechange", this.change);
      this.canvas = document.createElement("canvas"); this.canvas.width = this.canvas.height = 2048;
      this.context = this.canvas.getContext("2d");
      this.context.setTransform?.(2, 0, 0, 2, 0, 0);
      if (options.inspector) {
        this.inspectorObserver = new MutationObserver(() => { if (renderer.selectedClaim || renderer.selectedRelation) this.setInspector(options.inspector); });
        this.inspectorObserver.observe(options.inspector, { childList: true, subtree: true, characterData: true });
      }
      if (renderer.selectedClaim || renderer.selectedRelation) this.setInspector(options.inspector);
      renderer.xrController = this;
    }
    notify(message = "") { if (this.disposed) return; this.options.onState?.({ session: Boolean(this.session), mode: this.mode, busy: this.busy, support: { ...this.support }, message }); }
    async detect() {
      if (!globalThis.isSecureContext) { this.notify("VR / AR benötigt eine vertrauenswürdige HTTPS-Verbindung."); return this.support; }
      if (!navigator.xr) { this.notify("Dieser Browser bietet kein WebXR an. Die normale 3D-Ansicht bleibt verfügbar."); return this.support; }
      const modes = Object.keys(this.support);
      const results = await Promise.allSettled(modes.map(mode => navigator.xr.isSessionSupported(mode)));
      if (this.disposed) return this.support;
      modes.forEach((mode, i) => { this.support[mode] = results[i].status === "fulfilled" && results[i].value === true; });
      this.notify(modes.some(mode => this.support[mode]) ? "Trigger: wählen / abwählen · ein Griff: bewegen / drehen · beide Griffe: Größe" : "Keine unterstützte VR-/AR-Sitzung gefunden.");
      return this.support;
    }
    async start(mode) {
      if (!Object.hasOwn(this.support, mode)) throw new Error("Unbekannter XR-Modus.");
      if (this.disposed || this.busy) return;
      if (!this.support[mode]) throw new Error(mode === "immersive-ar" ? "AR/MR wird in diesem Browser nicht angeboten." : "VR wird in diesem Browser nicht angeboten.");
      if (this.session && this.mode === mode) return;
      this.busy = true; this.notify();
      let session;
      try {
        if (this.session) await this.end();
        if (this.disposed) return;
        // Called from the user's button/select event; never enter XR automatically.
        session = await navigator.xr.requestSession(mode, { optionalFeatures: ["local-floor"] });
        if (this.disposed) { await session.end(); return; }
        this.session = session; this.mode = mode; this.anchor = null; this.page = 0; this.grab = null;this.panelGrab=null;this.gripTargets=new WeakMap();
        this.ended = () => this.cleanup(session);
        session.addEventListener("end", this.ended, { once: true });
        const renderer = this.renderer, gl = renderer.gl;
        renderer.xrSession = session; renderer.stopAmbientMotion(); renderer.stopActivityMotion();
        if (renderer.frame) cancelAnimationFrame(renderer.frame); renderer.frame = 0;
        await gl.makeXRCompatible();
        if (this.session !== session) return;
        const nativeScale = XRWebGLLayer.getNativeFramebufferScaleFactor?.(session);
        const layer = new XRWebGLLayer(session, gl, { alpha: true, depth: true, antialias: true,
          framebufferScaleFactor: Number.isFinite(nativeScale) && nativeScale > 0 ? nativeScale : 1 });
        if ("fixedFoveation" in layer) layer.fixedFoveation = 0;
        session.updateRenderState({ baseLayer: layer, depthNear: .05, depthFar: 30 });
        try { this.space = await session.requestReferenceSpace("local-floor"); }
        catch { this.space = await session.requestReferenceSpace("local"); }
        if (this.session !== session) return;
        this.space.addEventListener("reset", this.resetReference);
        this.initializeGraphics();
        session.addEventListener("select", this.select);
        let radius = 1; for (const position of renderer.positions.values()) radius = Math.max(radius, Math.hypot(...position));
        this.baseSize = .6 / radius; this.size = this.baseSize; this.yaw = 0; this.pitch = 0; this.offset = [...CLOUD_OFFSET]; this.rotation = identity();
        this.lastTime = null; this.model = identity(); this.panelDirty = true;
        session.requestAnimationFrame((time, frame) => this.frame(time, frame));
        this.notify(mode === "immersive-ar" ? "AR/MR aktiv · Passthrough" : "VR aktiv");
      } catch (error) {
        if (session && this.session === session) { try { await session.end(); } finally { this.cleanup(session); } }
        const message = error.name === "NotAllowedError"
          ? "XR-Zugriff nicht erlaubt. Berechtigung prüfen und den gewünschten Modus erneut anklicken."
          : `XR konnte nicht gestartet werden: ${error.message}`;
        this.notify(message); throw new Error(message);
      } finally { this.busy = false; this.notify(); }
    }
    async end() {
      const session = this.session;
      if (session) { try { await session.end(); } finally { this.cleanup(session); } }
    }
    cleanup(session) {
      if (this.session !== session) return;
      session.removeEventListener("select", this.select); session.removeEventListener("end", this.ended);
      this.space?.removeEventListener("reset", this.resetReference);
      this.session = null; this.space = null; this.grab = null;this.panelGrab=null; this.renderer.xrSession = null;
      const gl = this.renderer.gl;
      gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.bindVertexArray(null);
      this.releaseGraphics();
      if (!this.disposed) { this.renderer.setHover(null); this.renderer.requestRender(); this.renderer.syncAmbientMotion(); this.renderer.syncActivityMotion(); this.notify("XR beendet · normale Ansicht aktiv"); }
    }
    initializeGraphics() {
      const gl = this.renderer.gl;
      this.panelProgram = program(gl, `#version 300 es
        in vec2 position; uniform mat4 matrix; out vec2 uv;
        void main(){uv=position*.5+.5;gl_Position=matrix*vec4(position,0.,1.);}`,
      `#version 300 es
        precision mediump float; uniform sampler2D image; in vec2 uv; out vec4 color;
        void main(){color=texture(image,vec2(uv.x,1.-uv.y));}`);
      this.rayProgram = program(gl, `#version 300 es
        in vec3 position; uniform mat4 matrix; void main(){gl_Position=matrix*vec4(position,1.);}`,
      `#version 300 es
        precision mediump float; uniform vec4 tint; out vec4 color; void main(){color=tint;}`);
      this.vao = gl.createVertexArray(); this.buffer = gl.createBuffer(); this.texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.texture); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    }
    releaseGraphics() {
      const gl = this.renderer.gl;
      if (this.panelProgram) gl.deleteProgram(this.panelProgram);
      if (this.rayProgram) gl.deleteProgram(this.rayProgram);
      if (this.vao) gl.deleteVertexArray(this.vao);
      if (this.buffer) gl.deleteBuffer(this.buffer);
      if (this.texture) gl.deleteTexture(this.texture);
      this.panelProgram = this.rayProgram = this.vao = this.buffer = this.texture = null;
    }
    setDetails(text) {
      text = String(text || ""); if (text === this.details) return;
      this.details = text;this.blocks=null;this.panelSource=null; this.page = 0; this.panelDirty = true;
    }
    setInspector(root) {
      if(!root)return;
      this.setDetails(root.innerText||root.textContent||"");
      this.blocks=inspectorBlocks(root);this.panelSource=null;this.panelDirty=true;
    }
    panelTransform(){return compose(this.panelOffset||PANEL.position);}
    panelRows() {
      const source=this.blocks||[{kind:"section",text:"NEUROCLOUD"},{kind:"body",text:this.details||"Claim oder Verbindung mit dem Trigger auswählen. Erneutes Auswählen oder ins Leere klicken hebt die Auswahl auf."},
        ...(!this.details?[{kind:"section",text:"BEDIENUNG"},{kind:"body",text:`Auf die Titelleiste zeigen und Griff halten: Fenster verschieben.
Wolke greifen: bewegen und um ihren Mittelpunkt drehen. Zwei Griffe: Größe und Ausrichtung ändern. Rot / Grün / Blau zeigen X / Y / Z. Die helle Linie zeigt die aktuelle Drehachse.`}]:[])];
      const key=JSON.stringify(source);if(key===this.panelSource)return this.panelLines;
      this.panelSource=key;const rows=[],styles={title:["bold 31px sans-serif","#e6f8fa",40],section:["bold 24px sans-serif","#7ee8df",36],label:["bold 18px sans-serif","#779ba9",25],badge:["bold 21px sans-serif","#68e6da",32],code:["20px monospace","#acd1dc",29],action:["bold 20px sans-serif","#79cdd8",30],body:["24px sans-serif","#ccdde3",33],field:["23px sans-serif","#e1f0f4",32]};
      for(const block of source){const [font,color,height]=styles[block.kind]||styles.body;this.context.font=font;
        if(block.kind==="section"||block.kind==="title")rows.push({height:12});
        for(const text of wrapText(this.context,block.text,block.card?864:904))rows.push({text,font,color,height,card:block.card,kind:block.kind});
      }
      this.panelLines=rows;return rows;
    }
    updatePanel() {
      if (!this.panelDirty) return;
      this.panelDirty = false;
      const c=this.context,lines=this.panelRows(),pages=[[]];let used=0;
      for(const row of lines){if(used+row.height>580&&pages[pages.length-1].length){pages.push([]);used=0;}pages[pages.length-1].push(row);used+=row.height;}
      this.pages=pages.length; this.page = clamp(this.page, 0, this.pages - 1);
      c.fillStyle = "#061118"; c.fillRect(0, 0, 1024, 1024);
      c.fillStyle = "#8febff"; c.font = "bold 32px sans-serif"; c.fillText(`EVE BRAINWATCH · ${this.mode === "immersive-ar" ? "AR / MR" : "VR"}`, 48, 58);
      c.fillStyle = "#91aabb"; c.font = "18px sans-serif";
      c.fillText(`${this.renderer.nodes.length} Claims · ${this.renderer.edges.length} Relations`, 48, 96);
      c.fillText(this.status || "Kein Turn gewählt", 48, 121, 920);
      c.fillStyle="#12343d";c.fillRect(32,137,960,2);
      c.fillStyle="#6b9da8";c.font="16px sans-serif";c.fillText("TITELLEISTE GREIFEN = FENSTER VERSCHIEBEN",48,81);
      let top=153;
      for(const row of pages[this.page]){
        if(row.card){c.fillStyle="#0c242e";c.fillRect(40,top,944,row.height);c.fillStyle="#267e87";c.fillRect(40,top,3,row.height);}
        if(row.kind==="badge"){c.fillStyle="#103136";c.fillRect(40,top,944,row.height);}
        if(row.text){c.font=row.font;c.fillStyle=row.color;c.fillText(row.text,row.card?64:48,top+row.height-8);}
        top+=row.height;
      }
      c.font = "22px sans-serif"; c.fillStyle = "#91aabb"; c.fillText(`Seite ${this.page + 1} / ${this.pages}`, 48, 780);
      const rows = [[.79, ["ZURÜCK", "WEITER", "ABWÄHLEN", "ZENTRIEREN"]], [.88, ["VR", "AR / MR", "BEENDEN"]]];
      for (const [y, labels] of rows) labels.forEach((label, i) => {
        const width = 990 / labels.length;
        c.fillStyle = "#17384c"; c.fillRect(24 + i * width, y * 1024, width - 12, 72);
        c.fillStyle = "#e8faff"; c.font = "bold 20px sans-serif"; c.fillText(label, 36 + i * width, y * 1024 + 45);
      });
      const gl = this.renderer.gl; gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, this.canvas);
      gl.generateMipmap(gl.TEXTURE_2D);
    }
    hit(ray) {
      const panel = pickPanel(ray, this.anchor,this.panelTransform()), cloud = pickCloud(this.renderer, ray, this.model);
      return panel && (!cloud || panel.distance < cloud.distance) ? panel : cloud;
    }
    handleSelect(event) {
      if (!this.anchor || !this.space || this.busy) return;
      const pose = event.frame.getPose(event.inputSource.targetRaySpace, this.space);
      if (!pose) return;
      const selection = this.hit(rayFromPose(pose));
      if (selection?.kind === "panel") {
        const column = Math.floor(clamp((selection.x * 1024 - 30) / 330, 0, 2.99));
        if (selection.y >= .79 && selection.y <= .86) {
          if (selection.x >= .75) { this.anchor = null; this.offset = [...CLOUD_OFFSET]; this.rotation = identity(); this.yaw = 0; this.pitch = 0; this.size = this.baseSize;this.panelOffset=[...PANEL.position];this.panelGrab=null; }
          else if (selection.x >= .5) this.clearSelection();
          else this.page = clamp(this.page + (selection.x < .25 ? -1 : 1), 0, (this.pages || 1) - 1);
          this.panelDirty = true;
        } else if (selection.y >= .88 && selection.y <= .95) {
          if (column === 2) this.end().catch(error => this.notify(error.message));
          else this.start(column === 0 ? "immersive-vr" : "immersive-ar").catch(error => this.notify(error.message));
        }
      } else if (selection) {
        const renderer = this.renderer;
        if ((selection.kind === "claim" && renderer.selectedClaim === selection.value.id)
            || (selection.kind === "relation" && renderer.selectedRelation === selection.value.id)) { this.clearSelection(); return; }
        this.setDetails(selection.kind === "claim" ? `${selection.value.display_text || selection.value.id}\n\nDetails werden geladen …` : `${selection.value.relation_type}\n\nDetails werden geladen …`);
        if (selection.kind === "claim") { renderer.selectClaim(selection.value.id); renderer.options.onClaimSelect?.(selection.value); }
        else { renderer.selectRelation(selection.value.id); renderer.options.onRelationSelect?.(selection.value); }
      } else this.clearSelection();
    }
    clearSelection() { this.renderer.clearSelection(); this.setDetails(""); }
    cloudMatrix() { return multiply(this.anchor, multiply(compose(this.offset), multiply(this.rotation, compose([0,0,0], 0, 0, this.size)))); }
    input(frame, dt) {
      const rays = [], grips = [], panelGrips=[], sticks = []; let hover = null;const previousRotation=[...this.rotation];
      for (const source of this.session.inputSources) {
        const pose = frame.getPose(source.targetRaySpace, this.space);
        let pointed=null;
        if (pose) {
          const ray = rayFromPose(pose), hit = this.hit(ray);
          pointed=hit;rays.push(ray.origin, add(ray.origin, scale(ray.direction, hit?.distance ?? 2.5)));
          if (!hover && hit && hit.kind !== "panel") hover = hit;
        }
        const gamepad = source.gamepad;
        if (!gamepad) continue;
        const axes = gamepad.axes;
        sticks.push({source, x: axes.length >= 4 ? axes[2] : axes[0] || 0, y: axes.length >= 4 ? axes[3] : axes[1] || 0});
        if(!gamepad.buttons[1]?.pressed)this.gripTargets.delete(source);
        if (gamepad.buttons[1]?.pressed) {
          if(!this.gripTargets.has(source))this.gripTargets.set(source,pointed?.kind==="panel"&&pointed.y<.15?"panel":"cloud");
          const grip = source.gripSpace ? frame.getPose(source.gripSpace, this.space) : pose;
          if (grip) { const local = multiply(inverse(this.anchor), grip.transform.matrix);
            (this.gripTargets.get(source)==="panel"?panelGrips:grips).push({source, position: local.slice(12,15), rotation: rotationOf(local)}); }
        }
      }
      const panelHand=panelGrips.find(h=>h.source===this.panelGrab?.source)||panelGrips[0];
      if(panelHand){
        if(this.panelGrab?.source!==panelHand.source)this.panelGrab={source:panelHand.source,position:panelHand.position,offset:[...this.panelOffset]};
        this.panelOffset=add(this.panelGrab.offset,sub(panelHand.position,this.panelGrab.position));
      }else this.panelGrab=null;
      grips.sort((a,b)=>String(a.source.handedness).localeCompare(String(b.source.handedness)));
      if (grips.length) {
        const hands = grips.slice(0,2), midpoint = hands.length === 2 ? scale(add(hands[0].position,hands[1].position),.5) : hands[0].position;
        const vector = hands.length === 2 ? sub(hands[1].position,hands[0].position) : null;
        const distance = vector ? Math.hypot(...vector) : 0;
        if (!this.grab || hands.length !== this.grab.hands.length || hands.some((h,i)=>h.source!==this.grab.hands[i])) {
          this.grab = {hands: hands.map(h=>h.source), midpoint, vector, distance, handRotation: hands[0].rotation,
            offset: [...this.offset], rotation: [...this.rotation], size: this.size};
        }
        const grab = this.grab;
        if (hands.length === 2 && distance > .02 && grab.distance > .02) {
          const delta = between(grab.vector,vector);
          this.size = clamp(grab.size*distance/grab.distance,this.baseSize*.25,this.baseSize*4);
          this.rotation = multiply(delta,grab.rotation);
          this.offset = add(grab.offset,sub(midpoint,grab.midpoint));
        } else if (hands.length === 1) {
          this.rotation = multiply(multiply(hands[0].rotation,inverse(grab.handRotation)),grab.rotation);
          this.offset = add(grab.offset,sub(midpoint,grab.midpoint));
        }
      } else {
        this.grab = null;
        for (const {source,x,y} of sticks) {
          if (source.handedness === "left") { if (Math.abs(y)>.15) this.size=clamp(this.size*Math.exp(-y*dt),this.baseSize*.25,this.baseSize*4); }
          else { const dy=Math.abs(x)>.15?x*dt:0, dp=Math.abs(y)>.15?y*dt:0;
            this.yaw+=dy; this.pitch+=dp; this.rotation=multiply(compose([0,0,0],dy,dp),this.rotation); }
        }
      }
      this.rotationGuide=grips.length>0||sticks.some(({source,x,y})=>source.handedness!=="left"&&(Math.abs(x)>.15||Math.abs(y)>.15));
      const delta=multiply(this.rotation,inverse(previousRotation)),axis=[delta[6]-delta[9],delta[8]-delta[2],delta[1]-delta[4]];
      if(Math.hypot(...axis)>1e-5)this.rotationAxis=norm(axis);
      this.renderer.setHover(hover);
      return rays;
    }
    frame(time, frame) {
      const session = this.session;
      if (!session || frame.session !== session) return;
      session.requestAnimationFrame((next, f) => this.frame(next, f));
      try {
        const pose = frame.getViewerPose(this.space); if (!pose) return;
        if (!this.anchor) {
          const m = pose.transform.matrix, yaw = Math.atan2(m[8], m[10]);
          this.anchor = compose(Array.from(m.slice(12, 15)), yaw); this.grab = null;
        }
        const dt = this.lastTime === null ? 0 : Math.min(.05, (time - this.lastTime) / 1000); this.lastTime = time;
        if (this.positions !== this.renderer.positions) {
          this.positions = this.renderer.positions;
          let radius = 1; for (const position of this.positions.values()) radius = Math.max(radius, Math.hypot(...position));
          const factor = this.size / this.baseSize;
          this.baseSize = .6 / radius; this.size = this.baseSize * factor;
        }
        this.model = this.cloudMatrix();
        const rays = this.input(frame, dt);
        this.model = this.cloudMatrix();
        const status = this.options.getStatus?.() || "";
        if (status !== this.status) { this.status = status; this.panelDirty = true; }
        this.updatePanel();
        const gl = this.renderer.gl, layer = session.renderState.baseLayer;
        gl.bindFramebuffer(gl.FRAMEBUFFER, layer.framebuffer); gl.disable(gl.SCISSOR_TEST); gl.depthMask(true);
        gl.clearColor(0, 0, this.mode === "immersive-ar" ? 0 : .018, this.mode === "immersive-ar" ? 0 : 1);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        const invModel = inverse(this.model);
        for (const view of pose.views) {
          const vp = layer.getViewport(view); gl.viewport(vp.x, vp.y, vp.width, vp.height);
          const viewProjection = multiply(view.projectionMatrix, view.transform.inverse.matrix), eye = view.transform.matrix;
          // Opaque panel first: its real depth also clips transparent cloud passes.
          this.drawPanel(viewProjection);
          this.renderer.renderView(time, { viewport: vp, matrix: multiply(viewProjection, this.model), basis: {
            eye: point(invModel, Array.from(eye.slice(12, 15))),
            right: norm(point(invModel, Array.from(eye.slice(0, 3)), 0)), up: norm(point(invModel, Array.from(eye.slice(4, 7)), 0)),
          } });
          this.drawRotationGuide(viewProjection);
          this.drawRays(viewProjection, rays);
        }
      } catch (error) { this.end().catch(() => {}).finally(() => this.notify(`XR-Darstellung beendet: ${error.message}`)); }
    }
    drawPanel(viewProjection) {
      const gl = this.renderer.gl;
      gl.bindVertexArray(this.vao); gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS); gl.depthMask(true); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.useProgram(this.panelProgram);
      const panel = multiply(this.anchor,this.panelTransform());
      const panelScale = identity(); panelScale[0] = PANEL.width / 2; panelScale[5] = PANEL.height / 2;
      gl.uniformMatrix4fv(gl.getUniformLocation(this.panelProgram, "matrix"), false, multiply(viewProjection, multiply(panel, panelScale)));
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.texture); gl.uniform1i(gl.getUniformLocation(this.panelProgram, "image"), 0);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.DYNAMIC_DRAW);
      let location = gl.getAttribLocation(this.panelProgram, "position"); gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, 2, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(location, 0); gl.drawArrays(gl.TRIANGLES, 0, 6);
      gl.bindVertexArray(null);
    }
    drawRotationGuide(viewProjection) {
      if(!this.rotationGuide)return;
      const gl=this.renderer.gl,radius=.68*this.size/this.baseSize;
      gl.bindVertexArray(this.vao);gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.enable(gl.DEPTH_TEST);gl.depthMask(false);
      gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);gl.useProgram(this.rayProgram);
      const base=multiply(viewProjection,multiply(this.anchor,compose(this.offset))),matrix=multiply(base,this.rotation);
      const colors=[[1,.32,.27,.9],[.3,1,.52,.9],[.35,.6,1,.9]];
      const draw=(vertices,color,m)=>{gl.uniform4fv(gl.getUniformLocation(this.rayProgram,"tint"),color);gl.uniformMatrix4fv(gl.getUniformLocation(this.rayProgram,"matrix"),false,m);
        gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(vertices),gl.DYNAMIC_DRAW);const location=gl.getAttribLocation(this.rayProgram,"position");gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,3,gl.FLOAT,false,0,0);gl.vertexAttribDivisor(location,0);gl.drawArrays(gl.LINES,0,vertices.length/3);};
      for(let axis=0;axis<3;axis++){
        const vertices=[];
        for(let i=0;i<48;i++)for(const t of [i/48*2*Math.PI,(i+1)/48*2*Math.PI]){const p=[0,0,0];p[(axis+1)%3]=Math.cos(t)*radius;p[(axis+2)%3]=Math.sin(t)*radius;vertices.push(...p);}
        const a=[0,0,0];a[axis]=radius;vertices.push(...scale(a,-1),...a);draw(vertices,colors[axis],matrix);
      }
      if(this.rotationAxis)draw([...scale(this.rotationAxis,-radius*1.25),...scale(this.rotationAxis,radius*1.25)],[1,1,.85,1],base);
      gl.bindVertexArray(null);
    }
    drawRays(viewProjection, rays) {
      if (!rays.length) return;
      const gl = this.renderer.gl;
      gl.bindVertexArray(this.vao); gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.depthMask(false);
      gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      {
        gl.useProgram(this.rayProgram);gl.uniform4fv(gl.getUniformLocation(this.rayProgram,"tint"),[.35,.95,1,1]); gl.uniformMatrix4fv(gl.getUniformLocation(this.rayProgram, "matrix"), false, viewProjection);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(rays.flat()), gl.DYNAMIC_DRAW);
        const location = gl.getAttribLocation(this.rayProgram, "position"); gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(location, 0); gl.drawArrays(gl.LINES, 0, rays.length);
      }
      gl.depthFunc(gl.LESS); gl.bindVertexArray(null);
    }
    dispose() {
      this.disposed = true; navigator.xr?.removeEventListener("devicechange", this.change);
      this.inspectorObserver?.disconnect();
      const session = this.session;
      if (session) { this.cleanup(session); session.end().catch(() => {}); }
      this.renderer.xrController = null;
    }
  }
  globalThis.EveNeuroCloudXR = { NeuroCloudXR, multiply, compose, inverse, between, point, rayFromPose, rayPoint, raySegment, pickCloud, pickPanel, wrapText, inspectorBlocks };
})();
