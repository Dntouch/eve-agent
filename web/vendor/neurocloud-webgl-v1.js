/* EVE NeuroCloud WebGL2 renderer v1.1. Local, deterministic and event-driven. */
(() => {
  "use strict";

  const VERSION = "eve-neurocloud-webgl2-v1.21";
  const DEFAULT_LAYOUT_VERSION = "neurocloud-layout-v3-provenance-regions";
  const TAU = Math.PI * 2;
  const QUALITY = Object.freeze({
    low: { curveSegments: 6, fogLayers: 2, fogLimit: 48, pixelRatio: 1.25 },
    medium: { curveSegments: 10, fogLayers: 3, fogLimit: 96, pixelRatio: 1.75 },
    high: { curveSegments: 14, fogLayers: 4, fogLimit: 160, pixelRatio: 2 },
  });
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const hash = (value) => {
    let output = 2166136261;
    for (const char of String(value)) {
      output ^= char.charCodeAt(0);
      output = Math.imul(output, 16777619);
    }
    output ^= output >>> 16;
    output = Math.imul(output, 0x85ebca6b);
    output ^= output >>> 13;
    output = Math.imul(output, 0xc2b2ae35);
    output ^= output >>> 16;
    return output >>> 0;
  };
  const unit = (value, salt = "") => hash(`${salt}|${value}`) / 4294967295;
  const vector = (value, radius = 1) => {
    const angle = unit(value, "angle") * TAU;
    const z = unit(value, "height") * 2 - 1;
    const planar = Math.sqrt(Math.max(0, 1 - z * z)) * radius;
    return [Math.cos(angle) * planar, z * radius, Math.sin(angle) * planar];
  };
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const scale = (a, value) => [a[0] * value, a[1] * value, a[2] * value];
  const mix = (a, b, amount) => add(scale(a, 1 - amount), scale(b, amount));
  const length = (a) => Math.hypot(a[0], a[1], a[2]);
  const normalize = (a) => scale(a, 1 / (length(a) || 1));
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const mean = (points) => scale(points.reduce((sum, point) => add(sum, point), [0, 0, 0]), 1 / Math.max(1, points.length));

  function provenanceRegion(node) {
    const scope = String(node?.scope || "unscoped");
    const parts = scope.split(":");
    if (parts[0] === "provider" && parts[1] && parts[1] !== "runtime") return `provider:${parts[1]}`;
    if (node?.claim_kind === "provider_binding" && parts[1]) return `provider:${parts[1]}`;
    return "eve-internal";
  }

  function scopeCenter(scope, version, regionCenter = [0, 0, 0]) {
    const direction = vector(`${version}|scope|${scope}`, 1);
    const phase = unit(scope, "scope-phase") * TAU;
    return [
      regionCenter[0] + direction[0] * 3.8 + Math.sin(phase * 1.7) * 1.15,
      regionCenter[1] + direction[1] * 3.4 + Math.sin(phase + direction[2]) * 1.35,
      regionCenter[2] + direction[2] * 4.2 + Math.cos(phase * 1.3) * 1.45,
    ];
  }

  function densityRegion(id, scope, claimIds, points, layerCount) {
    if (!points.length) return [];
    const center = mean(points);
    const variance = points.reduce((sum, point) => [
      sum[0] + (point[0] - center[0]) ** 2,
      sum[1] + (point[1] - center[1]) ** 2,
      sum[2] + (point[2] - center[2]) ** 2,
    ], [0, 0, 0]).map((value) => value / points.length);
    const spread = Math.sqrt(variance[0] + variance[1] + variance[2]);
    const radius = Math.max(2.4, spread * 1.45 + 1.9 + Math.cbrt(points.length) * .55);
    const aspect = clamp(.78 + Math.sqrt(Math.max(...variance)) / Math.max(.1, radius) * .65, .78, 1.65);
    const layers = [];
    for (let layer = 0; layer < layerCount; layer += 1) {
      const layerId = `${id}|layer:${layer}`;
      const offset = scale(vector(layerId, 1), radius * (.035 + layer * .045));
      layers.push({
        id: `density:${layerId}`, scope, claim_ids: [...claimIds],
        center: add(center, offset), radius: radius * (1 + layer * .09), density: points.length,
        aspect: aspect * (.92 + unit(layerId, "aspect") * .2),
        rotation: unit(layerId, "rotation") * TAU,
        seed: unit(layerId, "seed"), opacity: .6 / Math.sqrt(layer + 1),
      });
    }
    return layers;
  }

  function buildFogRegions(nodes, positions, quality = QUALITY.medium) {
    const scopes = new Map();
    for (const node of nodes) {
      const point = positions.get(node.id);
      if (!point) continue;
      const scope = node.scope || "unscoped";
      if (!scopes.has(scope)) scopes.set(scope, []);
      scopes.get(scope).push({ id: node.id, point });
    }
    const fog = [];
    for (const [scope, entries] of [...scopes].sort(([left], [right]) => left.localeCompare(right))) {
      if (!entries.length) continue;
      entries.sort((left, right) => left.id.localeCompare(right.id));
      fog.push(...densityRegion(`${scope}|envelope`, scope, entries.map((entry) => entry.id), entries.map((entry) => entry.point), quality.fogLayers));
      const bucketCount = Math.min(4, Math.max(1, Math.floor(Math.sqrt(entries.length) / 2)));
      const buckets = Array.from({ length: bucketCount }, () => []);
      for (const entry of entries) buckets[hash(`${scope}|${entry.id}`) % bucketCount].push(entry);
      for (let index = 0; index < buckets.length; index += 1) {
        if (buckets[index].length < 2 || buckets[index].length === entries.length) continue;
        fog.push(...densityRegion(`${scope}|lobe:${index}`, scope, buckets[index].map((entry) => entry.id), buckets[index].map((entry) => entry.point), Math.max(1, quality.fogLayers - 1)));
      }
    }
    // Keep every scope represented; spend the remaining quality budget on detail.
    const envelopes = fog.filter(region => region.id.includes("|envelope|layer:0"));
    const detail = fog.filter(region => !region.id.includes("|envelope|layer:0"));
    return envelopes.concat(detail.slice(0, Math.max(0, quality.fogLimit - envelopes.length)));
  }

  function layoutWorkingMemory(positions, nodes) {
    const result = new Map(positions);
    for (const node of nodes) {
      if (node.node_kind !== "working_material") continue;
      const center = add([0, 14, 0], vector(node.workspace_id, 2));
      result.set(node.id, add(center, vector(node.id, 4)));
    }
    return result;
  }

  function shapePositions(positions, shape = "organic") {
    const source = new Map([...positions].map(([id, point]) => [id, [...point]]));
    if (shape !== "brain" || source.size < 2) return source;
    const center = mean([...source.values()]);
    const extents = [0, 1, 2].map((axis) => Math.max(1, ...[...source.values()].map((point) => Math.abs(point[axis] - center[axis]))));
    const growth = Math.cbrt(source.size / 460);
    const shaped = new Map();
    for (const [id, point] of source) {
      const normalized = point.map((value, axis) => clamp((value - center[axis]) / extents[axis], -1, 1));
      const [x, y, z] = normalized;
      const upper = clamp((y + 1) / 2, 0, 1);
      const lowerTaper = 1 - clamp(-y, 0, 1) * .22;
      const crown = (1 - clamp(x * x * .68 + z * z * .32, 0, 1)) * .78;
      shaped.set(id, [
        x * 12.2 * lowerTaper * (.92 + Math.abs(x) * .08),
        y * 7.6 + crown - .28,
        z * 6.8 * (.94 - Math.abs(y) * .1),
      ].map(value => value * growth));
    }
    return shaped;
  }

  function layoutGraph(nodes, edges, version = DEFAULT_LAYOUT_VERSION, quality = QUALITY.medium) {
    const ordered = [...(nodes || [])].sort((a, b) => String(a.id).localeCompare(String(b.id)));
    const parent = new Map(ordered.map((node) => [node.id, node.id]));
    const find = (identifier) => {
      let root = identifier;
      while (parent.get(root) !== root) root = parent.get(root);
      while (parent.get(identifier) !== identifier) { const next = parent.get(identifier); parent.set(identifier, root); identifier = next; }
      return root;
    };
    const union = (leftId, rightId) => {
      if (!parent.has(leftId) || !parent.has(rightId)) return;
      const left = find(leftId), right = find(rightId);
      if (left !== right) parent.set(left < right ? right : left, left < right ? left : right);
    };
    for (const edge of edges || []) union(edge.from_claim_id, edge.to_claim_id);
    const components = new Map();
    for (const node of ordered) {
      const root = find(node.id);
      if (!components.has(root)) components.set(root, []);
      components.get(root).push(node);
    }
    const regions = new Map();
    for (const node of ordered) {
      const region = provenanceRegion(node);
      if (!regions.has(region)) regions.set(region, []);
      regions.get(region).push(node);
    }
    const regionCenters = new Map();
    if (regions.has("eve-internal")) regionCenters.set("eve-internal", [-7.2, 0, -1]);
    const providerRegions = [...regions.keys()].filter((key) => key !== "eve-internal").sort();
    providerRegions.forEach((region, index) => {
      const angle = providerRegions.length === 1 ? 0 : index / providerRegions.length * TAU;
      regionCenters.set(region, [7.2, Math.sin(angle) * 5.6, Math.cos(angle) * 4.4]);
    });
    const scopeCenters = new Map();
    for (const node of ordered) {
      const scope = node.scope || "unscoped";
      const region = provenanceRegion(node);
      if (!scopeCenters.has(scope)) scopeCenters.set(scope, scopeCenter(scope, version, regionCenters.get(region)));
    }
    const positions = new Map();
    for (const members of components.values()) {
      members.sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")) || String(a.id).localeCompare(String(b.id)));
      const anchor = members[0].id;
      const componentScopes = [...new Set(members.map((node) => node.scope || "unscoped"))];
      const scopeMean = mean(componentScopes.map((scope) => scopeCenters.get(scope)));
      const componentCenter = add(scopeMean, vector(`${version}|component|${anchor}`, 3.6));
      for (const node of members) {
        const localRadius = 1.3 + unit(node.id, "local-radius") * (members.length === 1 ? 5.8 : 3.9);
        const organic = vector(`${version}|claim|${node.id}`, localRadius);
        const scopeBias = scopeCenters.get(node.scope || "unscoped");
        let point = add(mix(componentCenter, scopeBias, .22), [organic[0] * 1.32, organic[1] * .78, organic[2]]);
        const phase = unit(node.id, "warp") * TAU;
        point = [point[0] + Math.sin(point[2] * .22 + phase) * 1.15, point[1] + Math.sin(point[0] * .27 + phase * .7) * 1.35, point[2] + Math.cos(point[1] * .31 + phase * 1.2) * .95];
        positions.set(node.id, point);
      }
    }
    const growth = Math.cbrt(ordered.length / 460);
    for (const [id, point] of positions) positions.set(id, scale(point, growth));
    const fog = buildFogRegions(ordered, positions, quality);
    return { version, positions, fog, components: components.size, regions: regions.size };
  }

  function neuronAppearance(identifier) {
    return { size: .19 + unit(identifier, "soma-size") * .18, aspect: .78 + unit(identifier, "soma-aspect") * .48, rotation: unit(identifier, "soma-rotation") * TAU, seed: unit(identifier, "soma-texture"), lobes: 3 + Math.floor(unit(identifier, "soma-lobes") * 4) };
  }

  function bezierPoint(start, controlA, controlB, end, time) {
    const inverse = 1 - time;
    return [0, 1, 2].map((axis) => inverse ** 3 * start[axis] + 3 * inverse ** 2 * time * controlA[axis] + 3 * inverse * time ** 2 * controlB[axis] + time ** 3 * end[axis]);
  }

  function relationCurve(edge, positions, segments = QUALITY.medium.curveSegments) {
    const start = positions.get(edge.from_claim_id), end = positions.get(edge.to_claim_id);
    if (!start || !end) return [];
    const delta = sub(end, start), distance = length(delta), direction = normalize(delta);
    let reference = vector(`${edge.id}|curve-reference`, 1);
    if (Math.abs(dot(reference, direction)) > .9) reference = [reference[2], reference[0], reference[1]];
    const normal = normalize(cross(direction, reference)), binormal = normalize(cross(direction, normal));
    const bend = clamp(distance * (.11 + unit(edge.id, "curve-bend") * .13), .35, 3.4);
    const twist = (unit(edge.id, "curve-twist") - .5) * bend * .9;
    const controlA = add(add(start, scale(delta, .31)), add(scale(normal, bend), scale(binormal, twist)));
    const controlB = add(add(start, scale(delta, .69)), add(scale(normal, bend * .72), scale(binormal, -twist * .8)));
    return Array.from({ length: segments + 1 }, (_, index) => bezierPoint(start, controlA, controlB, end, index / segments));
  }

  function selectionNeighborhood(claimId, edges, maxDepth = 2) {
    const claimHops = new Map(claimId ? [[claimId, 0]] : []), relationHops = new Map();
    const claimIds = new Set(claimHops.keys()), relationIds = new Set();
    if (!claimId) return { claimIds, relationIds, claimHops, relationHops };
    const depthLimit = clamp(Math.floor(Number(maxDepth) || 0), 0, 2), adjacency = new Map();
    for (const edge of edges || []) {
      if (!edge?.id || !edge.from_claim_id || !edge.to_claim_id) continue;
      for (const endpoint of [edge.from_claim_id, edge.to_claim_id]) {
        if (!adjacency.has(endpoint)) adjacency.set(endpoint, []);
        adjacency.get(endpoint).push(edge);
      }
    }
    const queue = [claimId];
    for (let cursor = 0; cursor < queue.length; cursor += 1) {
      const current = queue[cursor], depth = claimHops.get(current);
      if (depth >= depthLimit) continue;
      for (const edge of adjacency.get(current) || []) {
        const next = edge.from_claim_id === current ? edge.to_claim_id : edge.from_claim_id;
        const nextDepth = depth + 1, knownDepth = claimHops.get(next), knownRelationDepth = relationHops.get(edge.id);
        if (knownRelationDepth === undefined || nextDepth < knownRelationDepth) relationHops.set(edge.id, nextDepth);
        if (knownDepth === undefined || nextDepth < knownDepth) {
          claimHops.set(next, nextDepth);
          claimIds.add(next);
          queue.push(next);
        }
      }
    }
    for (const relationId of relationHops.keys()) relationIds.add(relationId);
    return { claimIds, relationIds, claimHops, relationHops };
  }

  const ACTIVITY_CATEGORIES = Object.freeze({
    retrieval: ["claim_retrieved","claim_eligible","claim_selected_for_view","claim_returned_to_consumer"],
    llm_context: ["claim_added_to_prompt_context","claim_received_by_llm_client","claim_serialized_for_transport"],
    deterministic: ["claim_resolved","alias_read_for_stt","claim_technical_verification","claim_bound_to_plan"],
    actions: ["claim_bound_to_action","action_dispatch_attempted_with_claim","action_provider_response_with_claim","action_verification_with_claim","action_completed_with_claim"],
    lifecycle: ["claim_lifecycle_changed"],
    relations: ["relation_traversed_for_retrieval","relation_bound_to_plan"],
  });
  const ACTIVITY_CATEGORY_BY_KIND = new Map(Object.entries(ACTIVITY_CATEGORIES).flatMap(([category,kinds])=>kinds.map((kind)=>[kind,category])));
  const ACTIVITY_COLORS = Object.freeze({retrieval:[.12,.92,.9],llm_context:[.62,.38,1],deterministic:[.58,.88,1],actions:[.28,1,.66],lifecycle:[.94,.35,.82],relations:[.3,.7,1]});
  const STATUS_COLORS = Object.freeze({success:null,uncertain:[.72,.5,1],cancelled:[1,.7,.25],failed:[1,.24,.34]});
  const statusRank = (status) => ({success:0,uncertain:1,cancelled:2,failed:3})[status] ?? 1;

  function activityStatus(event) {
    if (["failed","rejected"].includes(event.event_status)||["failed","error","denied"].includes(event.outcome_status)||["contradictory","error"].includes(event.verification_status)) return "failed";
    if (event.event_status==="cancelled"||event.outcome_status==="cancelled"||event.verification_status==="cancelled") return "cancelled";
    if (event.event_status==="started"||["partial","outcome_uncertain","not_available"].includes(event.outcome_status)||["in_progress","inconclusive","not_available"].includes(event.verification_status)) return "uncertain";
    return "success";
  }
  function activityEventColor(event) { const category=ACTIVITY_CATEGORY_BY_KIND.get(event?.event_kind),status=activityStatus(event);return STATUS_COLORS[status]||ACTIVITY_COLORS[category]||[.4,.9,1]; }

  function activityEventId(event) { return String(event?.event_id||event?.runtime_event_id||"").replace(/^runtime-event:/,""); }
  function normalizedClaimId(event) { const raw=event?.claim_ids?.[0]||event?.claim_id||"";return raw?`claim:${String(raw).replace(/^claim:/,"")}`:""; }
  function normalizedRelationId(event) { const raw=event?.relation_id||"";return raw?`memory-relation:${String(raw).replace(/^memory-relation:/,"")}`:""; }
  function activityIntensity(count) { return count>0 ? .32+.68*Math.min(1,Math.log1p(count)/Math.log1p(8)) : 0; }

  function projectRuntimeActivity(events, options = {}) {
    const turnId=String(options.turnId||"").replace(/^turn:/,""),accepted=[],seen=new Set(),attempts=new Map();
    for(const event of events||[]){const eventId=activityEventId(event),category=ACTIVITY_CATEGORY_BY_KIND.get(event?.event_kind),eventTurn=String(event?.turn_id||"").replace(/^turn:/,"");if(!eventId||!category||(turnId&&eventTurn!==turnId)||seen.has(eventId))continue;const claimId=normalizedClaimId(event),relationId=normalizedRelationId(event);if(category==="relations"?!relationId:!claimId)continue;if(category==="relations"&&!ACTIVITY_CATEGORIES.relations.includes(event.event_kind))continue;seen.add(eventId);accepted.push({...event,event_id:`runtime-event:${eventId}`,runtime_event_id:eventId,category,claim_id:claimId||null,relation_id:relationId||null,visual_status:activityStatus(event)});const root=category==="llm_context"?`llm|${event.llm_call_id||event.operation_id||eventId}|${event.context_block_id||""}`:category==="actions"?`action|${event.action_id||event.operation_id||eventId}`:"";if(root&&event.attempt_id){if(!attempts.has(root))attempts.set(root,new Set());attempts.get(root).add(String(event.attempt_id));}}
    const firstAttempt=(root)=>[...(attempts.get(root)||[])].sort()[0]||"";
    const operationKey=(event)=>{const category=event.category;if(category==="retrieval")return `${event.compiler_evaluation_id||event.operation_id||event.runtime_event_id}|${event.consumer||""}`;if(category==="llm_context"){const root=`llm|${event.llm_call_id||event.operation_id||event.runtime_event_id}|${event.context_block_id||""}`;return `${root}|${event.attempt_id||firstAttempt(root)||"call"}`;}if(category==="actions"){const root=`action|${event.action_id||event.operation_id||event.runtime_event_id}`;return `${root}|${event.attempt_id||firstAttempt(root)||"action"}`;}if(category==="relations")return event.event_kind==="relation_bound_to_plan"?`plan|${event.planner_round_id||""}|${event.plan_id||event.operation_id}`:`retrieval|${event.compiler_evaluation_id||event.operation_id}|${event.consumer||""}`;if(category==="lifecycle")return event.learning_decision_id||event.runtime_event_id;return `${event.operation_id||event.runtime_event_id}|${event.planner_round_id||""}|${event.plan_id||""}|${event.action_id||""}`;};
    const claims={},relations={},categoryOperations=Object.fromEntries(Object.keys(ACTIVITY_CATEGORIES).map((category)=>[category,new Set()]));
    for(const event of accepted){const collection=event.claim_id?claims:relations,id=event.claim_id||event.relation_id,key=operationKey(event);collection[id]||={id,categories:{}};const group=collection[id].categories[event.category]||={operations:new Set(),event_ids:[],status:"success"};group.operations.add(key);group.event_ids.push(event.event_id);if(statusRank(event.visual_status)>statusRank(group.status))group.status=event.visual_status;categoryOperations[event.category].add(`${id}|${key}`);}
    for(const collection of [claims,relations])for(const item of Object.values(collection))for(const group of Object.values(item.categories)){group.count=group.operations.size;group.intensity=activityIntensity(group.count);delete group.operations;}
    return {version:"neurocloud-activity-v1",turn_id:turnId?`turn:${turnId}`:null,complete:options.complete===true,events:accepted,claims,relations,categories:Object.fromEntries(Object.entries(categoryOperations).map(([category,operations])=>[category,operations.size])),semantics:{persisted_events_only:true,universal_used_count:false,intensity:"0.32 + 0.68 * min(1, log1p(count) / log1p(8))",all_filter:"category_union_max_not_sum"}};
  }

  function activityVisual(pattern, kind, identifier, filter="all") {
    const item=(kind==="relation"?pattern?.relations:pattern?.claims)?.[identifier];if(!item)return{intensity:0,color:[0,0,0],status:"success",count:0};const entries=Object.entries(item.categories||{}).filter(([category])=>filter==="all"||category===filter);if(!entries.length)return{intensity:0,color:[0,0,0],status:"success",count:0};let intensity=0,count=0,status="success",color=[0,0,0];for(const[category,value]of entries){if(value.intensity>intensity){intensity=value.intensity;color=ACTIVITY_COLORS[category]||[.4,.9,1];}count=Math.max(count,value.count||0);if(statusRank(value.status)>statusRank(status))status=value.status;}if(STATUS_COLORS[status])color=STATUS_COLORS[status];return{intensity,color,status,count};
  }

  function perspective(fieldOfView, aspect, near, far) { const f = 1 / Math.tan(fieldOfView / 2), range = 1 / (near - far); return [f/aspect,0,0,0,0,f,0,0,0,0,(near+far)*range,-1,0,0,near*far*range*2,0]; }
  function lookAt(eye, target, up) { const z=normalize(sub(eye,target)),x=normalize(cross(up,z)),y=cross(z,x);return[x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]; }
  function multiply(a,b){const output=new Array(16).fill(0);for(let column=0;column<4;column+=1)for(let row=0;row<4;row+=1)for(let index=0;index<4;index+=1)output[column*4+row]+=a[index*4+row]*b[column*4+index];return output;}
  function transform(matrix,point){const[x,y,z]=point;return[matrix[0]*x+matrix[4]*y+matrix[8]*z+matrix[12],matrix[1]*x+matrix[5]*y+matrix[9]*z+matrix[13],matrix[2]*x+matrix[6]*y+matrix[10]*z+matrix[14],matrix[3]*x+matrix[7]*y+matrix[11]*z+matrix[15]];}
  function shader(gl,type,source){const item=gl.createShader(type);gl.shaderSource(item,source);gl.compileShader(item);if(!gl.getShaderParameter(item,gl.COMPILE_STATUS)){const message=gl.getShaderInfoLog(item)||"Shader konnte nicht kompiliert werden";gl.deleteShader(item);throw new Error(message);}return item;}
  function program(gl,vertexSource,fragmentSource){const vertex=shader(gl,gl.VERTEX_SHADER,vertexSource),fragment=shader(gl,gl.FRAGMENT_SHADER,fragmentSource),item=gl.createProgram();gl.attachShader(item,vertex);gl.attachShader(item,fragment);gl.linkProgram(item);gl.deleteShader(vertex);gl.deleteShader(fragment);if(!gl.getProgramParameter(item,gl.LINK_STATUS)){const message=gl.getProgramInfoLog(item)||"WebGL-Programm konnte nicht verknüpft werden";gl.deleteProgram(item);throw new Error(message);}return item;}
  function colorForScope(value){const scope=String(value||"");if(scope.startsWith("provider:home-assistant:"))return[.03,.82,1];if(scope.startsWith("provider:"))return[.08,.58,1];if(scope==="semantic_language_relations"||scope==="semantic_similarity_relations")return[.95,.2,.82];if(scope==="semantic_links")return[.69,.25,.98];if(scope==="semantic_actions")return[.3,.4,1];if(scope.startsWith("household:")||scope.startsWith("user:"))return[.86,.28,.92];return[.12,.72,.94];}
  function colorFor(node){if(node.node_kind==="working_material")return node.work_status==="failed"?[1,.25,.32]:node.kind==="tool_result"?[.58,.48,1]:[.3,.78,1];if(node.lifecycle==="invalid")return[.05,.18,.55];if(node.lifecycle==="retired")return[.32,.14,.72];if(node.claim_kind==="alias")return[.96,.22,.84];return colorForScope(node.scope);}

  class NeuroCloudRenderer {
    constructor(canvas, options = {}) {
      this.canvas=canvas;this.options=options;this.qualityName=QUALITY[options.quality]?options.quality:"medium";
      this.gl=canvas?.getContext?.("webgl2",{alpha:true,antialias:true,premultipliedAlpha:true,xrCompatible:true,powerPreference:options.powerPreference||"default"});
      this.supported=Boolean(this.gl);this.nodes=[];this.edges=[];this.positions=new Map();this.fog=[];this.curves=new Map();
      this.selectedClaim=null;this.selectedRelation=null;this.highlightedClaims=new Set();this.hoveredClaim=null;this.hoveredRelation=null;this.visible=true;this.frame=0;this.ambientFrame=0;this.ambientTimer=0;this.lastAmbientTime=0;this.activityFrame=0;this.activityPaused=false;
      this.activityPattern=null;this.activityFilter="all";this.claimImpulses=new Map();this.relationImpulses=new Map();this.animatedEventIds=new Set();this.animatedEventOrder=[];
      const cameraYaw=Number(options.cameraYaw);this.baseCameraDistance=Number(options.cameraDistance)||36;this.baseCameraPitch=Number(options.cameraPitch)||.24;this.baseCameraYaw=Number.isFinite(cameraYaw)?cameraYaw:-.62;this.camera={yaw:this.baseCameraYaw,pitch:this.baseCameraPitch,distance:this.baseCameraDistance,target:[0,0,0],fieldOfView:Number(options.fieldOfView)||.82};this.ambientDeadline=0;this.ambientPhase=0;
      this.intensity=clamp(Number(options.intensity)||1,.55,1.5);this.haloStrength=clamp(Number(options.haloStrength)||1,.005,1.25);this.fogStrength=clamp(Number(options.fogStrength)||1,.2,1.25);this.densityAwareExposure=options.densityAwareExposure===true;this.densityReference=clamp(Number(options.densityReference)||420,20,2000);this.relationStrength=clamp(Number(options.relationStrength)||1,.25,4);this.activityTimeScale=clamp(Number(options.activityTimeScale)||1,1,4);this.spatialShape=options.spatialShape==="brain"?"brain":"organic";this.orbitMode=options.orbitMode==="sway"?"sway":"rotate";this.boundedBaseBlend=options.boundedBaseBlend===true;this.additiveRelations=options.additiveRelations===true;this.transparentBackground=options.transparentBackground===true;this.ambientMotion=options.ambientMotion!==false;this.continuousAmbientMotion=options.continuousAmbientMotion===true;this.depthMotion=options.depthMotion===true;this.autoRotateSpeed=clamp(Number(options.autoRotateSpeed)||.018,.004,.05);this.animationFps=clamp(Number(options.animationFps)||30,12,60);this.drag=null;this.listeners=[];
      this.statsValue={version:VERSION,supported:this.supported,quality:this.qualityName,nodes:0,relations:0,fog_layers:0,curve_segments:0,draw_calls:0,gpu_buffer_bytes:0,last_frame_ms:null};
      if(!this.supported)return;try{this.initialize();}catch(error){this.supported=false;this.error=error;this.dispose();return;}this.bind();this.reducedMotionQuery=matchMedia("(prefers-reduced-motion: reduce)");this.pageVisible=!document.hidden;this.listen(this.reducedMotionQuery,"change",()=>{this.syncAmbientMotion();this.syncActivityMotion();});this.listen(document,"visibilitychange",()=>{this.pageVisible=!document.hidden;this.syncAmbientMotion();this.syncActivityMotion();});this.resizeObserver=new ResizeObserver(()=>{if(this.nodes.length&&this.quality().curveSegments!==this.bufferCurveSegments)this.setData(this.nodes,this.edges,this.layoutVersion);else this.requestRender();});this.resizeObserver.observe(canvas);
    }
    effectiveQualityName(){if((this.canvas.clientWidth&&this.canvas.clientWidth<520)||this.nodes.length>3000)return "low";if(this.nodes.length>1200&&this.qualityName==="high")return "medium";return this.qualityName;}
    quality(){return QUALITY[this.effectiveQualityName()];}
    initialize(){
      const gl=this.gl;
      const billboardVertex=`#version 300 es
        precision highp float; layout(location=0) in vec2 corner; layout(location=1) in vec3 position;
        layout(location=2) in vec3 color; layout(location=3) in float size; layout(location=4) in vec4 appearance; layout(location=5) in float emphasis; layout(location=6) in vec3 activityColor; layout(location=7) in float activityLevel; layout(location=8) in float impulseStartedAt;
        uniform mat4 viewProjection; uniform vec3 cameraRight; uniform vec3 cameraUp; uniform vec3 cameraPosition; uniform float passScale; uniform float angularLimit; uniform float cullInside;
        out vec2 uv; out vec3 tint; out vec4 style; out float depthDistance; out float focusEmphasis; out vec3 activityTint; out float persistentActivity; out float impulseStart;
        void main(){ if(cullInside>.5&&length(cameraPosition-position)<size*1.25){gl_Position=vec4(2.,2.,2.,1.);return;} float c=cos(appearance.y),s=sin(appearance.y); vec2 shaped=vec2(c*corner.x-s*corner.y,s*corner.x+c*corner.y); shaped.x*=appearance.x; float extent=size*passScale; if(angularLimit>0.0)extent=min(extent,max(.001,length(cameraPosition-position))*angularLimit); vec3 world=position+(cameraRight*shaped.x+cameraUp*shaped.y)*extent; gl_Position=viewProjection*vec4(world,1.0); uv=corner; tint=color; style=appearance; depthDistance=length(cameraPosition-position); focusEmphasis=emphasis; activityTint=activityColor; persistentActivity=activityLevel; impulseStart=impulseStartedAt; }`;
      this.nodeProgram=program(gl,billboardVertex,`#version 300 es
        precision highp float; in vec2 uv; in vec3 tint; in vec4 style; in float depthDistance; in float focusEmphasis; in vec3 activityTint; in float persistentActivity; in float impulseStart; uniform float intensity; uniform float haloPass; uniform float haloStrength; uniform float densityExposure; uniform float activityTimeScale; uniform float clock; out vec4 outColor;
        void main(){ float angle=atan(uv.y,uv.x); float lobes=3.0+floor(style.w*4.0); float boundary=1.0+.075*sin(angle*lobes+style.z*19.0)+.035*sin(angle*(lobes+3.0)-style.z*31.0); float d=length(uv)/boundary; if(d>1.05) discard; float halo=exp(-d*d*2.55); float soma=exp(-d*d*16.0); float nucleus=exp(-d*d*68.0); float depthFade=clamp(1.34-(depthDistance-10.0)/50.0,.25,1.0); float learning=step(2.5,focusEmphasis); float related=step(.5,focusEmphasis); float selected=max(0.0,step(1.5,focusEmphasis)-learning); float direct=max(0.0,step(.9,focusEmphasis)-selected-learning); float nextHop=max(0.0,related-direct-selected-learning); float subdued=focusEmphasis<-.5?.13:1.0; float ringA=exp(-abs(d-.57)*46.0); float ringB=exp(-abs(d-.83)*58.0); float marker=(ringA*1.15+ringB*.92)*selected+(ringA*.38+ringB*.72)*direct+(ringA*.18+ringB*.48)*nextHop+(ringA*.9+ringB*1.18)*learning; float age=(clock-impulseStart)/activityTimeScale; float alive=step(0.0,age)*step(age,2.5); float onset=smoothstep(0.0,.075,age); float corePulse=alive*onset*exp(-max(0.0,age-.075)*2.35); float wavePhase=clamp(age/1.55,0.0,1.0); float waveEnvelope=alive*onset*exp(-max(0.0,age-.18)*1.18); float impulseRing=exp(-abs(d-(.16+wavePhase*.72))*42.0)*waveEnvelope; float afterglow=alive*onset*exp(-max(0.0,age-.12)*1.5); float activity=clamp(persistentActivity*.8+afterglow*.42,0.0,1.2); vec3 ice=mix(tint,vec3(.76,.99,1.0),.18+nucleus*.38); float base=mix(soma*.2+nucleus*1.42,halo*.045,haloPass)*subdued*densityExposure; float activityGlow=mix(soma*.38+nucleus*.94,halo*.26,haloPass)*activity; float impulseGlow=mix(nucleus*1.68+soma*.24,halo*.16,haloPass)*corePulse+impulseRing*mix(1.05,.3,haloPass); float alpha=(base+marker*(1.0-haloPass)+halo*(selected*.18+direct*.1+nextHop*.07+learning*.14)*haloPass+activityGlow+impulseGlow)*depthFade*intensity*mix(1.0,haloStrength*densityExposure,haloPass); if(haloPass<.5&&alpha<.075)discard; vec3 light=mix(ice*(.64+nucleus*.86),tint*.8,haloPass); if(haloPass<.5){alpha=clamp(max(alpha,.22+nucleus*.68),0.0,1.0);light=mix(tint,vec3(.9,1.0,1.0),.2+nucleus*.58);} light=mix(light,vec3(.78,1.0,1.0),direct*.8+selected*.92); light=mix(light,vec3(.74,.48,1.0),nextHop*.82); light=mix(light,vec3(1.0,.63,.24),learning*.96); light=mix(light,activityTint,clamp(activity*.7+afterglow*.16,0.0,.88)); light=mix(light,vec3(.94,1.0,1.0),clamp(corePulse*.82+impulseRing*.55,0.0,.92)); outColor=vec4(light,alpha); }`);
      this.fogProgram=program(gl,billboardVertex,`#version 300 es
        precision highp float; in vec2 uv; in vec3 tint; in vec4 style; in float depthDistance; in float focusEmphasis; uniform float intensity; uniform float fogVisibility; uniform float focusMode; out vec4 outColor;
        float hash21(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7))+style.z*91.7)*43758.5453);} float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(hash21(i),hash21(i+vec2(1,0)),f.x),mix(hash21(i+vec2(0,1)),hash21(i+vec2(1,1)),f.x),f.y);} float fbm(vec2 p){float value=0.0,weight=.56;for(int i=0;i<4;i++){value+=noise(p)*weight;p=p*2.03+vec2(3.1,1.7);weight*=.48;}return value;}
        void main(){float d=dot(uv,uv);float turbulence=fbm(uv*3.2+style.z*17.0);float edge=1.0+.24*(turbulence-.5)+.08*sin(atan(uv.y,uv.x)*5.0+style.z*13.0);if(d>edge)discard;float body=exp(-d*(1.55+style.z*.75))*(1.0-smoothstep(.18,edge,d));float depthFade=clamp(1.26-(depthDistance-8.0)/62.0,.26,1.0);float local=(.4+.78*turbulence)*body*style.w*fogVisibility*depthFade*mix(1.0,.3,focusMode);vec3 color=mix(tint*.48,mix(tint,vec3(.55,.88,1.0),.32),turbulence);outColor=vec4(color,local*.19*intensity);}`);
      const lineFragment = `#version 300 es
        precision highp float;in vec3 tint;in float strength;in float depthDistance;in float progress;in float impulseStart;uniform float intensity;uniform float filamentPass;uniform float relationExposure;uniform float activityTimeScale;uniform float clock;out vec4 outColor;void main(){float depthFade=clamp(1.26-(depthDistance-8.0)/55.0,.22,1.0);float age=(clock-impulseStart)/activityTimeScale;float head=clamp(age/1.25,0.0,1.0);float path=step(0.0,age)*step(age,2.8)*smoothstep(head-.34,head,progress)*(1.0-smoothstep(head,head+.105,progress));float afterglow=step(0.0,age)*step(age,2.8)*smoothstep(0.0,head,progress)*exp(-max(0.0,age-1.2)*1.35);float pulse=path+afterglow*.58;float focusPath=step(5.0,strength);float effectiveStrength=mix(strength,strength*.28,focusPath);float effectiveExposure=mix(relationExposure,max(relationExposure,.72),focusPath);float base=effectiveStrength*mix(.31,.12,filamentPass)*effectiveExposure;float alpha=(base+pulse*mix(1.42,.52,filamentPass))*depthFade*intensity;vec3 color=mix(tint,vec3(.82,1.0,1.0),clamp(.18+pulse*.82,0.0,.97))*mix(.96,.68,filamentPass);outColor=vec4(color,alpha);}`;
      this.lineProgram=program(gl,`#version 300 es
        precision highp float;layout(location=0)in vec3 position;layout(location=1)in vec3 color;layout(location=2)in float opacity;layout(location=3)in float pathProgress;layout(location=4)in float impulseStartedAt;uniform mat4 viewProjection;uniform vec3 cameraPosition;out vec3 tint;out float strength;out float depthDistance;out float progress;out float impulseStart;void main(){gl_Position=viewProjection*vec4(position,1.0);tint=color;strength=opacity;depthDistance=length(cameraPosition-position);progress=pathProgress;impulseStart=impulseStartedAt;}`,
      lineFragment);

      this.xrLineProgram=program(gl,`#version 300 es
        precision highp float;
        layout(location=0)in vec3 position;layout(location=1)in vec3 color;layout(location=2)in float opacity;
        layout(location=3)in float pathProgress;layout(location=4)in float impulseStartedAt;
        layout(location=5)in vec3 endPosition;layout(location=6)in vec3 endColor;layout(location=7)in float endOpacity;layout(location=8)in float endProgress;
        uniform mat4 viewProjection;uniform vec3 cameraPosition;uniform vec2 viewportSize;uniform float pixelWidth;
        out vec3 tint;out float strength;out float depthDistance;out float progress;out float impulseStart;
        void main(){
          vec2 corners[6]=vec2[6](vec2(0.,-1.),vec2(1.,-1.),vec2(0.,1.),vec2(0.,1.),vec2(1.,-1.),vec2(1.,1.));
          vec2 corner=corners[gl_VertexID];vec4 a=viewProjection*vec4(position,1.),b=viewProjection*vec4(endPosition,1.);
          float da=a.z+a.w,db=b.z+b.w;
          if(da<0.&&db<0.){gl_Position=vec4(2.,2.,2.,1.);return;}
          if(da<0.)a=mix(a,b,da/(da-db));else if(db<0.)b=mix(a,b,da/(da-db));
          vec2 delta=(b.xy/b.w-a.xy/a.w)*viewportSize;
          vec2 perpendicular=vec2(-delta.y,delta.x)/max(length(delta),.001);
          vec4 clip=mix(a,b,corner.x);clip.xy+=perpendicular*corner.y*pixelWidth/viewportSize*clip.w;
          gl_Position=clip;tint=mix(color,endColor,corner.x);strength=mix(opacity,endOpacity,corner.x);
          progress=mix(pathProgress,endProgress,corner.x);impulseStart=impulseStartedAt;
          depthDistance=length(cameraPosition-mix(position,endPosition,corner.x));
        }`,lineFragment);
      this.quad=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,this.quad);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);this.nodeBuffer=gl.createBuffer();this.fogBuffer=gl.createBuffer();this.lineBuffer=gl.createBuffer();
    }
    listen(target,name,callback,options){target.addEventListener(name,callback,options);this.listeners.push([target,name,callback,options]);}
    bind(){
      this.listen(this.canvas,"contextmenu",(event)=>event.preventDefault());this.listen(this.canvas,"pointerdown",(event)=>{this.pauseAmbientMotion();this.canvas.setPointerCapture(event.pointerId);this.drag={x:event.clientX,y:event.clientY,button:event.button,moved:false};});
      this.listen(this.canvas,"pointermove",(event)=>{if(this.drag){const dx=event.clientX-this.drag.x,dy=event.clientY-this.drag.y;this.drag.x=event.clientX;this.drag.y=event.clientY;this.drag.moved||=Math.abs(dx)+Math.abs(dy)>2;if(this.drag.button===2||event.shiftKey)this.pan(dx,dy);else this.rotate(dx,dy);return;}const selection=this.pick(event.offsetX,event.offsetY);this.setHover(selection);this.canvas.style.cursor=selection?"pointer":"grab";this.options.onHover?.(selection,event);});
      this.listen(this.canvas,"pointerleave",()=>{if(!this.drag){this.setHover(null);this.options.onHover?.(null,null);}});this.listen(this.canvas,"pointerup",(event)=>{const click=this.drag&&!this.drag.moved;this.drag=null;this.pauseAmbientMotion();if(!click)return;const selection=this.pick(event.offsetX,event.offsetY);if(selection?.kind==="claim")this.options.onClaimSelect?.(selection.value);else if(selection?.kind==="relation")this.options.onRelationSelect?.(selection.value);else this.clearSelection();});
      this.listen(this.canvas,"wheel",(event)=>{event.preventDefault();this.pauseAmbientMotion();this.camera.distance=clamp(this.camera.distance*Math.exp(event.deltaY*.0012),5,100);this.requestRender();},{passive:false});
      this.listen(this.canvas,"keydown",(event)=>{if(event.key!=="Escape")return;event.preventDefault();this.pauseAmbientMotion();this.clearSelection();});
    }
    rotate(dx,dy){this.camera.yaw-=dx*.006;this.camera.pitch=clamp(this.camera.pitch-dy*.006,-1.35,1.35);this.requestRender();}
    pan(dx,dy){const basis=this.cameraBasis(),amount=this.camera.distance*.0015;this.camera.target=add(this.camera.target,add(scale(basis.right,-dx*amount),scale(basis.up,dy*amount)));this.requestRender();}
    cameraBasis(){const cp=Math.cos(this.camera.pitch),eye=add(this.camera.target,[Math.sin(this.camera.yaw)*cp*this.camera.distance,Math.sin(this.camera.pitch)*this.camera.distance,Math.cos(this.camera.yaw)*cp*this.camera.distance]),forward=normalize(sub(this.camera.target,eye)),right=normalize(cross(forward,[0,1,0]));return{eye,forward,right,up:normalize(cross(right,forward))};}
    setData(nodes,edges,layoutVersion=DEFAULT_LAYOUT_VERSION){this.nodes=[...(nodes||[])];this.edges=[...(edges||[])];this.layoutVersion=layoutVersion;const quality=this.quality(),baseNodes=this.nodes.filter(node=>node.node_kind!=="working_material"),baseEdges=this.edges.filter(edge=>edge.node_kind!=="working_link"),baseLayout=layoutGraph(baseNodes,baseEdges,layoutVersion,quality),positions=layoutWorkingMemory(shapePositions(baseLayout.positions,this.spatialShape),this.nodes),fog=this.spatialShape==="brain"?buildFogRegions(baseNodes,positions,quality):baseLayout.fog,layout={...baseLayout,positions,fog,spatial_shape:this.spatialShape};this.bufferCurveSegments=quality.curveSegments;this.positions=positions;this.fog=fog;this.ambientDeadline=performance.now()+12000;if(this.supported)this.upload();this.statsValue={...this.statsValue,nodes:this.nodes.length,relations:this.edges.length,fog_layers:this.fog.length};this.requestRender();this.syncAmbientMotion();return layout;}
    upload(){
      const gl=this.gl,nodeData=[],fogData=[],lineData=[],quality=this.quality(),neighborhood=selectionNeighborhood(this.selectedClaim,this.edges),nodeById=new Map(this.nodes.map((node)=>[node.id,node]));if(this.curvePositions!==this.positions||this.curveSegments!==quality.curveSegments){this.curves=new Map();this.curvePositions=this.positions;this.curveSegments=quality.curveSegments;}this.nodeOffsets=new Map();this.relationVertexRanges=new Map();this.nodeHoverSizes=new Map();this.relationHoverStyles=new Map();let segmentCount=0;
      for(const node of this.nodes){this.nodeOffsets.set(node.id,nodeData.length);const position=this.positions.get(node.id),baseColor=colorFor(node),appearance=neuronAppearance(node.id),selected=node.id===this.selectedClaim,learning=this.highlightedClaims.has(node.id),hop=neighborhood.claimHops.get(node.id),direct=hop===1,nextHop=hop===2,hovered=node.id===this.hoveredClaim,color=selected?[.82,1,1]:learning?[1,.58,.18]:direct?mix(baseColor,[.58,1,1],.68):nextHop?mix(baseColor,[.64,.42,1],.6):baseColor,emphasis=selected?2:learning?3:direct?1:nextHop?.62:(this.selectedClaim||this.highlightedClaims.size)?-1:0,activity=activityVisual(this.activityPattern,"claim",node.id,this.activityFilter),impulse=this.claimImpulses.get(node.id);nodeData.push(...position,...color,selected ? .78 : learning ? Math.max(.7,appearance.size*2.15) : direct ? Math.max(.52,appearance.size*1.9) : nextHop ? Math.max(.42,appearance.size*1.55) : appearance.size,appearance.aspect,appearance.rotation,appearance.seed,(appearance.lobes-3)/4,emphasis,...activity.color,activity.intensity,impulse?.startedAt??-1000);const normal=nodeData[nodeData.length-11];this.nodeHoverSizes.set(node.id,[normal,selected||learning||direct||nextHop?normal:.4]);}
      for(const region of this.fog){const color=colorForScope(region.scope);fogData.push(...region.center,...color,region.radius,region.aspect,region.rotation,region.seed,region.opacity,0,0,0,0,0,-1000);}
      for(const edge of this.edges){const curve=this.curves.get(edge.id)||relationCurve(edge,this.positions,quality.curveSegments);if(curve.length<2)continue;this.curves.set(edge.id,curve);const rangeStart=lineData.length/9,selected=edge.id===this.selectedRelation,learning=this.highlightedClaims.has(edge.from_claim_id)&&this.highlightedClaims.has(edge.to_claim_id),hop=neighborhood.relationHops.get(edge.id),direct=hop===1,nextHop=hop===2,hovered=edge.id===this.hoveredRelation,focused=Boolean(this.selectedClaim||this.highlightedClaims.size),activity=activityVisual(this.activityPattern,"relation",edge.id,this.activityFilter),active=activity.intensity>0,impulse=this.relationImpulses.get(edge.id),endpointColor=mix(colorFor(nodeById.get(edge.from_claim_id)||{}),colorFor(nodeById.get(edge.to_claim_id)||{}),.5),color=selected?[.98,.42,1]:learning?[1,.58,.18]:direct?[.68,1,1]:nextHop?[.64,.42,1]:active?activity.color:focused?[.04,.15,.2]:endpointColor;this.relationHoverStyles.set(edge.id,{normal:color,hover:selected||learning||direct||nextHop||active||focused?color:mix(endpointColor,[.72,1,1],.52),opacity:selected?16:learning?13:direct?12:nextHop?7:active?.85+activity.intensity*1.45:focused?.07:null});for(let index=1;index<curve.length;index+=1){const progressA=(index-1)/(curve.length-1),progressB=index/(curve.length-1),fadeA=.55+Math.sin(progressA*Math.PI)*.45,fadeB=.55+Math.sin(progressB*Math.PI)*.45,opacity=selected?16:learning?13:direct?12:nextHop?7:active?.85+activity.intensity*1.45:focused?.07:null,start=impulse?.startedAt??-1000;lineData.push(...curve[index-1],...color,opacity??fadeA,progressA,start,...curve[index],...color,opacity??fadeB,progressB,start);segmentCount+=1;}this.relationVertexRanges.set(edge.id,{start:rangeStart,count:lineData.length/9-rangeStart});}
      this.nodeArray=new Float32Array(nodeData);this.lineArray=new Float32Array(lineData);gl.bindBuffer(gl.ARRAY_BUFFER,this.nodeBuffer);gl.bufferData(gl.ARRAY_BUFFER,this.nodeArray,gl.DYNAMIC_DRAW);gl.bindBuffer(gl.ARRAY_BUFFER,this.fogBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(fogData),gl.STATIC_DRAW);gl.bindBuffer(gl.ARRAY_BUFFER,this.lineBuffer);gl.bufferData(gl.ARRAY_BUFFER,this.lineArray,gl.DYNAMIC_DRAW);this.lineVertexCount=lineData.length/9;this.patchHover("claim",this.hoveredClaim,true);this.patchHover("relation",this.hoveredRelation,true);this.statsValue={...this.statsValue,quality:this.effectiveQualityName(),curve_segments:segmentCount,activity_events:this.activityPattern?.events?.length||0,gpu_buffer_bytes:(nodeData.length+fogData.length+lineData.length+12)*4};
    }
    updateActivityImpulseBuffer(claimId,relationId,startedAt,color){const gl=this.gl;if(claimId&&this.nodeArray){const offset=this.nodeOffsets?.get(claimId);if(offset!==undefined){this.nodeArray.set(color,offset+12);this.nodeArray[offset+16]=startedAt;gl.bindBuffer(gl.ARRAY_BUFFER,this.nodeBuffer);gl.bufferSubData(gl.ARRAY_BUFFER,(offset+12)*4,this.nodeArray.subarray(offset+12,offset+17));this.statsValue.last_activity_buffer_bytes=20;}}else if(relationId&&this.lineArray){const range=this.relationVertexRanges?.get(relationId);if(range){const start=range.start*9,end=(range.start+range.count)*9;for(let vertex=range.start;vertex<range.start+range.count;vertex+=1){this.lineArray.set(color,vertex*9+3);this.lineArray[vertex*9+8]=startedAt;}gl.bindBuffer(gl.ARRAY_BUFFER,this.lineBuffer);gl.bufferSubData(gl.ARRAY_BUFFER,start*4,this.lineArray.subarray(start,end));this.statsValue.last_activity_buffer_bytes=(end-start)*4;}}}
    setIntensity(value){this.intensity=clamp(Number(value)||1,.55,1.5);this.requestRender();}
    setQuality(value){if(!QUALITY[value]||value===this.qualityName)return;this.qualityName=value;if(this.nodes.length)this.setData(this.nodes,this.edges,this.layoutVersion);}
    setVisible(value){const wasVisible=this.visible;this.visible=Boolean(value);if(!this.visible&&this.frame)cancelAnimationFrame(this.frame);this.frame=0;if(this.visible){if(!wasVisible)this.ambientDeadline=performance.now()+6000;this.requestRender();}this.syncAmbientMotion();this.syncActivityMotion();}
    selectClaim(id){if(this.selectedClaim===(id||null)&&!this.selectedRelation)return;this.selectedClaim=id||null;this.selectedRelation=null;if(this.supported)this.upload();this.requestRender();}
    selectRelation(id){if(this.selectedRelation===(id||null)&&!this.selectedClaim)return;this.selectedRelation=id||null;this.selectedClaim=null;if(this.supported)this.upload();this.requestRender();}
    clearSelection(){if(!this.selectedClaim&&!this.selectedRelation)return;this.selectedClaim=null;this.selectedRelation=null;if(this.supported)this.upload();this.requestRender();this.options.onSelectionClear?.();}
    setHighlightedClaims(ids,{focus=true}={}){this.highlightedClaims=new Set([...(ids||[])].filter((id)=>this.positions.has(id)));if(focus&&this.highlightedClaims.size){const points=[...this.highlightedClaims].map((id)=>this.positions.get(id)),center=points.reduce((sum,point)=>add(sum,point),[0,0,0]).map((value)=>value/points.length),radius=Math.max(0,...points.map((point)=>length(sub(point,center))));this.pauseAmbientMotion(30000);this.camera.target=center;this.camera.distance=clamp(10+radius*2.35,10,44);}if(this.supported)this.upload();this.requestRender();return this.highlightedClaims.size;}
    clearHighlightedClaims(){if(!this.highlightedClaims.size)return;this.highlightedClaims.clear();if(this.supported)this.upload();this.requestRender();}
    setActivityPattern(pattern){const next=pattern?.version==="neurocloud-activity-v1"?pattern:null;if(this.activityPattern?.turn_id!==next?.turn_id){this.claimImpulses.clear();this.relationImpulses.clear();this.animatedEventIds.clear();this.animatedEventOrder=[];}this.activityPattern=next;if(this.supported)this.upload();this.requestRender();return next;}
    setActivityFilter(value){if(value!=="all"&&!ACTIVITY_CATEGORIES[value])value="all";this.activityFilter=value;if(this.supported)this.upload();this.requestRender();}
    animateActivityEvent(event){const eventId=activityEventId(event),category=ACTIVITY_CATEGORY_BY_KIND.get(event?.event_kind);if(!eventId||!category||this.animatedEventIds.has(eventId))return false;const claimId=normalizedClaimId(event),relationId=normalizedRelationId(event);if(category==="relations"?!relationId:!claimId)return false;if(category==="relations"&&!ACTIVITY_CATEGORIES.relations.includes(event.event_kind))return false;this.animatedEventIds.add(eventId);this.animatedEventOrder.push(eventId);while(this.animatedEventOrder.length>5000)this.animatedEventIds.delete(this.animatedEventOrder.shift());const impulse={eventId,startedAt:performance.now()/1000,category,status:activityStatus(event)};if(claimId)this.claimImpulses.set(claimId,impulse);else this.relationImpulses.set(relationId,impulse);if(this.supported)this.updateActivityImpulseBuffer(claimId,relationId,impulse.startedAt,activityEventColor(event));this.requestRender();this.startActivityMotion();return true;}
    animateWorkingEvent(event){
      const startedAt=performance.now()/1000,color=event.status==='cancelled'?[1,.5,.25]:[.4,.8,1];
      for(const id of event.node_ids||[]){if(!this.positions.has(id))continue;this.claimImpulses.set(id,{startedAt});if(this.supported)this.updateActivityImpulseBuffer(id,null,startedAt,color);}
      for(const id of event.edge_ids||[]){if(!this.curves.has(id))continue;this.relationImpulses.set(id,{startedAt});if(this.supported)this.updateActivityImpulseBuffer(null,id,startedAt,color);}
      this.requestRender();this.startActivityMotion();
    }
    clearActivity(){this.activityPattern=null;this.claimImpulses.clear();this.relationImpulses.clear();this.animatedEventIds.clear();this.animatedEventOrder=[];this.stopActivityMotion();if(this.supported)this.upload();this.requestRender();}
    pauseActivity(){this.activityPaused=true;this.stopActivityMotion();}
    resumeActivity(){this.activityPaused=false;this.startActivityMotion();}
    patchHover(kind,id,active){
      if(!id||!this.supported)return;const gl=this.gl;
      if(kind==="claim"){
        const offset=this.nodeOffsets?.get(id),sizes=this.nodeHoverSizes?.get(id);if(offset===undefined||!sizes)return;
        this.nodeArray[offset+6]=sizes[active?1:0];gl.bindBuffer(gl.ARRAY_BUFFER,this.nodeBuffer);
        gl.bufferSubData(gl.ARRAY_BUFFER,(offset+6)*4,this.nodeArray.subarray(offset+6,offset+7));
      }else{
        const range=this.relationVertexRanges?.get(id),style=this.relationHoverStyles?.get(id);if(!range||!style)return;
        for(let v=range.start;v<range.start+range.count;v++){
          this.lineArray.set(active?style.hover:style.normal,v*9+3);
          this.lineArray[v*9+6]=style.opacity??(active?.82:.55+Math.sin(this.lineArray[v*9+7]*Math.PI)*.45);
        }
        gl.bindBuffer(gl.ARRAY_BUFFER,this.lineBuffer);
        gl.bufferSubData(gl.ARRAY_BUFFER,range.start*36,this.lineArray.subarray(range.start*9,(range.start+range.count)*9));
      }
    }
    setHover(selection){
      const claim=selection?.kind==="claim"?selection.value.id:null,relation=selection?.kind==="relation"?selection.value.id:null;
      if(claim===this.hoveredClaim&&relation===this.hoveredRelation)return;
      this.patchHover("claim",this.hoveredClaim,false);this.patchHover("relation",this.hoveredRelation,false);
      this.hoveredClaim=claim;this.hoveredRelation=relation;
      this.patchHover("claim",claim,true);this.patchHover("relation",relation,true);this.requestRender();
    }
    focusClaim(id){const position=this.positions.get(id);if(!position)return;this.pauseAmbientMotion();this.camera.target=[...position];this.camera.distance=clamp(this.camera.distance,8,24);this.selectClaim(id);}
    resetCamera(){this.pauseAmbientMotion();this.camera={...this.camera,yaw:this.baseCameraYaw,pitch:this.baseCameraPitch,distance:this.baseCameraDistance,target:[0,0,0]};this.requestRender();}
    requestRender(){if(!this.supported||!this.visible||this.xrSession||this.frame)return;this.frame=requestAnimationFrame((time)=>{this.frame=0;this.render(time);});}
    ambientAllowed(){const withinDeadline=performance.now()<this.ambientDeadline;return !this.xrSession&&this.supported&&this.visible&&this.pageVisible!==false&&this.nodes.length>0&&this.ambientMotion&&(this.continuousAmbientMotion||withinDeadline)&&!this.reducedMotionQuery?.matches;}
    ambientFrameRate(){if(this.nodes.length>3000)return Math.min(this.animationFps,20);if(this.canvas.clientWidth&&this.canvas.clientWidth<520)return Math.min(this.animationFps,24);return this.animationFps;}
    startAmbientMotion(){if(!this.ambientAllowed()||this.ambientFrame||this.activityFrame)return;this.lastAmbientTime=performance.now();const step=(time)=>{this.ambientFrame=0;if(!this.ambientAllowed()||this.activityFrame)return;const elapsed=time-this.lastAmbientTime;if(elapsed>=1000/this.ambientFrameRate()){if(this.orbitMode==="sway"){this.ambientPhase+=elapsed*.00022;const phase=this.ambientPhase;this.camera.yaw=this.baseCameraYaw+Math.sin(phase)*.16;this.camera.pitch=this.baseCameraPitch+Math.sin(phase*.74+.8)*.045;if(this.depthMotion){this.camera.distance=this.baseCameraDistance+Math.sin(phase*.57)*.55;this.camera.target=[0,Math.sin(phase*.68)*.3,Math.sin(phase*.49)*.2];}}else{this.camera.yaw-=this.autoRotateSpeed*elapsed/1000;if(this.depthMotion){const phase=time*.00019;this.camera.pitch=this.baseCameraPitch+Math.sin(phase)*.085;this.camera.distance=this.baseCameraDistance+Math.sin(phase*.73)*1.15;this.camera.target=[Math.sin(phase*.61)*.72,Math.cos(phase*.83)*.42,Math.sin(phase*.47)*.58];}}this.lastAmbientTime=time;if(this.frame){cancelAnimationFrame(this.frame);this.frame=0;}this.render(time);}this.ambientFrame=requestAnimationFrame(step);};this.ambientFrame=requestAnimationFrame(step);}
    stopAmbientMotion(){if(this.ambientFrame)cancelAnimationFrame(this.ambientFrame);this.ambientFrame=0;if(this.ambientTimer)clearTimeout(this.ambientTimer);this.ambientTimer=0;}
    syncAmbientMotion(){if(this.ambientAllowed())this.startAmbientMotion();else this.stopAmbientMotion();}
    pauseAmbientMotion(delay=5000){this.stopAmbientMotion();if(!this.supported||!this.visible||this.pageVisible===false||!this.ambientMotion||this.reducedMotionQuery?.matches)return;this.ambientTimer=setTimeout(()=>{this.ambientTimer=0;this.ambientDeadline=performance.now()+6000;this.startAmbientMotion();},delay);}
    activityMotionAllowed(){return !this.xrSession&&this.supported&&this.visible&&this.pageVisible!==false&&!this.activityPaused&&!this.reducedMotionQuery?.matches&&(this.claimImpulses.size>0||this.relationImpulses.size>0);}
    pruneActivityImpulses(clock){const lifetime=2.9*this.activityTimeScale;for(const[id,value]of this.claimImpulses)if(clock-value.startedAt>lifetime)this.claimImpulses.delete(id);for(const[id,value]of this.relationImpulses)if(clock-value.startedAt>lifetime)this.relationImpulses.delete(id);}
    startActivityMotion(){if(!this.activityMotionAllowed()||this.activityFrame)return;if(this.ambientFrame)cancelAnimationFrame(this.ambientFrame);this.ambientFrame=0;let last=performance.now();const step=(time)=>{this.activityFrame=0;if(!this.activityMotionAllowed()){this.syncAmbientMotion();return;}if(time-last>=1000/this.ambientFrameRate()){last=time;if(this.frame){cancelAnimationFrame(this.frame);this.frame=0;}this.render(time);}this.activityFrame=requestAnimationFrame(step);};this.activityFrame=requestAnimationFrame(step);}
    stopActivityMotion(){if(this.activityFrame)cancelAnimationFrame(this.activityFrame);this.activityFrame=0;}
    syncActivityMotion(){if(this.activityMotionAllowed())this.startActivityMotion();else this.stopActivityMotion();}
    blend(destination){const gl=this.gl;if(this.xrSession)gl.blendFuncSeparate(gl.SRC_ALPHA,destination,gl.ONE,gl.ONE_MINUS_SRC_ALPHA);else gl.blendFunc(gl.SRC_ALPHA,destination);}
    prepareInstances(programItem,buffer){const gl=this.gl;gl.useProgram(programItem);gl.bindBuffer(gl.ARRAY_BUFFER,this.quad);gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,2,gl.FLOAT,false,0,0);gl.vertexAttribDivisor(0,0);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);for(const[location,size,offset]of[[1,3,0],[2,3,12],[3,1,24],[4,4,28],[5,1,44],[6,3,48],[7,1,60],[8,1,64]]){gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,size,gl.FLOAT,false,68,offset);gl.vertexAttribDivisor(location,1);}}
    render(start){
      if(this.xrSession||!this.visible||!this.supported)return;const gl=this.gl,clock=performance.now()/1000,quality=this.quality(),ratio=Math.min(devicePixelRatio||1,quality.pixelRatio),width=Math.max(1,Math.round(this.canvas.clientWidth*ratio)),height=Math.max(1,Math.round(this.canvas.clientHeight*ratio));this.pruneActivityImpulses(clock);if(this.canvas.width!==width||this.canvas.height!==height){this.canvas.width=width;this.canvas.height=height;}gl.viewport(0,0,width,height);gl.clearColor(0,0,this.transparentBackground?0:.012,this.transparentBackground?0:1);gl.depthMask(true);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.BLEND);this.blend(this.boundedBaseBlend?gl.ONE_MINUS_SRC_ALPHA:gl.ONE);gl.depthMask(false);
      const basis=this.cameraBasis(),matrix=multiply(perspective(this.camera.fieldOfView,width/height,.1,190),lookAt(basis.eye,this.camera.target,basis.up));
      this.renderView(start,{basis,matrix,viewport:{x:0,y:0,width,height}});
    }
    // The XR host supplies each eye's real projection and camera in cloud coordinates.
    // Framebuffer, viewport and clearing belong to the host, never to this draw pass.
    renderView(start,{basis,matrix,viewport}){
      const gl=this.gl,clock=performance.now()/1000,uniform=(item,name)=>gl.getUniformLocation(item,name),common=(item)=>{gl.uniformMatrix4fv(uniform(item,"viewProjection"),false,matrix);gl.uniform3fv(uniform(item,"cameraPosition"),basis.eye);};
      this.pruneActivityImpulses(clock);gl.enable(gl.BLEND);this.blend(this.boundedBaseBlend?gl.ONE_MINUS_SRC_ALPHA:gl.ONE);gl.depthMask(false);
      let draws=0;
      if(this.fog.length){if(this.xrSession)gl.enable(gl.DEPTH_TEST);else gl.disable(gl.DEPTH_TEST);this.prepareInstances(this.fogProgram,this.fogBuffer);common(this.fogProgram);gl.uniform1f(uniform(this.fogProgram,"angularLimit"),0);gl.uniform1f(uniform(this.fogProgram,"cullInside"),this.xrSession?1:0);gl.uniform3fv(uniform(this.fogProgram,"cameraRight"),basis.right);gl.uniform3fv(uniform(this.fogProgram,"cameraUp"),basis.up);gl.uniform1f(uniform(this.fogProgram,"passScale"),1);gl.uniform1f(uniform(this.fogProgram,"intensity"),this.intensity);gl.uniform1f(uniform(this.fogProgram,"fogVisibility"),clamp((this.camera.distance-5)/25,.16,1)*this.fogStrength);gl.uniform1f(uniform(this.fogProgram,"focusMode"),(this.selectedClaim||this.highlightedClaims.size)?1:0);gl.drawArraysInstanced(gl.TRIANGLES,0,6,this.fog.length);draws+=1;}
      if(this.lineVertexCount){
        if(this.additiveRelations)this.blend(gl.ONE);
        const densityRelationExposure=this.densityAwareExposure?clamp(Math.sqrt(36/Math.max(1,this.edges.length)),.1,1):1;
        const relationExposure=clamp(densityRelationExposure*this.relationStrength,.1,2.5),xr=Boolean(this.xrSession),item=xr?this.xrLineProgram:this.lineProgram;
        gl.enable(gl.DEPTH_TEST);gl.useProgram(item);gl.bindBuffer(gl.ARRAY_BUFFER,this.lineBuffer);
        const attributes=xr?[[0,3,0],[1,3,12],[2,1,24],[3,1,28],[4,1,32],[5,3,36],[6,3,48],[7,1,60],[8,1,64]]:[[0,3,0],[1,3,12],[2,1,24],[3,1,28],[4,1,32]];
        for(const[location,size,offset]of attributes){gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,size,gl.FLOAT,false,xr?72:36,offset);gl.vertexAttribDivisor(location,xr?1:0);}
        common(item);gl.uniform1f(uniform(item,"intensity"),this.intensity);
        gl.uniform1f(uniform(item,"relationExposure"),xr?Math.max(.65,relationExposure):relationExposure);
        gl.uniform1f(uniform(item,"activityTimeScale"),this.activityTimeScale);gl.uniform1f(uniform(item,"clock"),clock);
        if(xr)gl.uniform2f(uniform(item,"viewportSize"),viewport.width,viewport.height);
        for(const pass of[1,0]){gl.uniform1f(uniform(item,"filamentPass"),pass);
          if(xr){gl.uniform1f(uniform(item,"pixelWidth"),pass?3.5:2);gl.drawArraysInstanced(gl.TRIANGLES,0,6,this.lineVertexCount/2);}
          else gl.drawArrays(gl.LINES,0,this.lineVertexCount);draws+=1;}
      }
      if(this.nodes.length){this.blend(this.boundedBaseBlend?gl.ONE_MINUS_SRC_ALPHA:gl.ONE);const densityExposure=this.densityAwareExposure?clamp(Math.sqrt(this.densityReference/this.nodes.length),.18,1):1;gl.enable(gl.DEPTH_TEST);this.prepareInstances(this.nodeProgram,this.nodeBuffer);common(this.nodeProgram);gl.uniform1f(uniform(this.nodeProgram,"cullInside"),0);gl.uniform1f(uniform(this.nodeProgram,"angularLimit"),this.xrSession?.22:0);gl.uniform3fv(uniform(this.nodeProgram,"cameraRight"),basis.right);gl.uniform3fv(uniform(this.nodeProgram,"cameraUp"),basis.up);gl.uniform1f(uniform(this.nodeProgram,"intensity"),this.intensity);gl.uniform1f(uniform(this.nodeProgram,"haloStrength"),this.haloStrength);gl.uniform1f(uniform(this.nodeProgram,"densityExposure"),densityExposure);gl.uniform1f(uniform(this.nodeProgram,"activityTimeScale"),this.activityTimeScale);gl.uniform1f(uniform(this.nodeProgram,"clock"),clock);for(const pass of[1,0]){gl.depthMask(this.boundedBaseBlend&&pass===0);gl.uniform1f(uniform(this.nodeProgram,"haloPass"),pass);gl.uniform1f(uniform(this.nodeProgram,"passScale"),pass?2.45:1);gl.drawArraysInstanced(gl.TRIANGLES,0,6,this.nodes.length);draws+=1;}gl.depthMask(false);}
      this.lastMatrix=matrix;this.statsValue.draw_calls=draws;this.statsValue.last_frame_ms=Math.max(0,performance.now()-start);this.options.onStats?.(this.stats());
    }
    project(point){if(!this.lastMatrix||!point)return null;const clip=transform(this.lastMatrix,point);if(clip[3]<=0)return null;return[(clip[0]/clip[3]*.5+.5)*this.canvas.clientWidth,(.5-clip[1]/clip[3]*.5)*this.canvas.clientHeight,clip[2]/clip[3]];}
    pick(x,y){let best=null,distance=17;for(const node of this.nodes){const point=this.project(this.positions.get(node.id));if(!point)continue;const delta=Math.hypot(point[0]-x,point[1]-y);if(delta<distance){distance=delta;best={kind:"claim",value:node};}}if(best)return best;distance=8;for(const edge of this.edges){const curve=this.curves.get(edge.id)||[];for(let index=1;index<curve.length;index+=1){const a=this.project(curve[index-1]),b=this.project(curve[index]);if(!a||!b)continue;const dx=b[0]-a[0],dy=b[1]-a[1],divisor=dx*dx+dy*dy||1,time=clamp(((x-a[0])*dx+(y-a[1])*dy)/divisor,0,1),delta=Math.hypot(x-(a[0]+time*dx),y-(a[1]+time*dy));if(delta<distance){distance=delta;best={kind:"relation",value:edge};}}}return best;}
    stats(){return{...this.statsValue};}
    dispose(){this.xrController?.dispose();if(this.frame)cancelAnimationFrame(this.frame);this.frame=0;this.stopAmbientMotion();this.stopActivityMotion();this.claimImpulses.clear();this.relationImpulses.clear();this.resizeObserver?.disconnect();for(const[target,name,callback,options]of this.listeners)target.removeEventListener(name,callback,options);this.listeners=[];if(!this.gl)return;for(const item of[this.quad,this.nodeBuffer,this.fogBuffer,this.lineBuffer])if(item)this.gl.deleteBuffer(item);for(const item of[this.nodeProgram,this.fogProgram,this.lineProgram,this.xrLineProgram])if(item)this.gl.deleteProgram(item);}
  }

  window.EveNeuroCloud={VERSION,DEFAULT_LAYOUT_VERSION,QUALITY,ACTIVITY_CATEGORIES,NeuroCloudRenderer,layoutGraph,shapePositions,buildFogRegions,neuronAppearance,relationCurve,selectionNeighborhood,projectRuntimeActivity,activityVisual,provenanceRegion,colorFor,colorForScope,layoutWorkingMemory};
})();
