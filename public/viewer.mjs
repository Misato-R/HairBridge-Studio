import {t,h,msg,getLanguage,setLanguage,translateDOM,taskMessage} from './i18n.mjs';
import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';
import {GLTFLoader} from './vendor/GLTFLoader.js';
import {sectionScene} from './section-preview.mjs';
import {meshTriangles,scalpSurface} from './scalp-inset.mjs';

const directions = {
  front: [0, 0, 1],
  back: [0, 0, -1],
  left: [1, 0, 0],
  right: [-1, 0, 0],
  top: [0, 1, 0],
  bottom: [0, -1, 0],
  input: [-.574, .025, .819],
  fit: [.22, .13, 1],
};
// Rain's saved side camera faces the character's right. Keep that key for saved projects.
const canonicalView = view => view === 'side' ? 'right' : view;

function savedCamera(cameras, view) {
  if (cameras?.[view]) return cameras[view];
  const legacySide = cameras?.side;
  if (!legacySide || (view !== 'left' && view !== 'right') || !legacySide.direction[0]) return null;
  if (Math.sign(legacySide.direction[0]) === directions[view][0]) return legacySide;
  const [x, y, z] = legacySide.direction;
  return {...legacySide, direction: [-x, y, z]};
}

function dispose(object) {
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  object.traverse(item => {
    if (item.geometry) geometries.add(item.geometry);
    const owning = Array.isArray(item.material) ? item.material : [item.material];
    for (const material of owning.filter(Boolean)) {
      materials.add(material);
      for (const value of Object.values(material)) {
        if (value?.isTexture) textures.add(value);
      }
    }
  });
  geometries.forEach(geometry => geometry.dispose());
  materials.forEach(material => material.dispose());
  textures.forEach(texture => texture.dispose());
}

function surfaceGeometry(surface) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(surface.vertices,3));
  geometry.setIndex(surface.faces);
  return geometry;
}

const brushSamples = [[0,0],[-1,0],[1,0],[0,-1],[0,1],[-.7,-.7],[-.7,.7],[.7,-.7],[.7,.7]];

function circularCursor(radius, tool) {
  const image = document.createElement('canvas');
  const center = radius + 2;
  image.width = image.height = center * 2 + 1;
  const context = image.getContext('2d');
  if (!context) return 'crosshair';
  context.beginPath();
  context.arc(center + .5,center + .5,radius,0,Math.PI*2);
  context.lineWidth = 3.5;
  context.strokeStyle = '#231c30';
  context.stroke();
  context.lineWidth = 1.5;
  context.strokeStyle = tool === 'remove' ? '#ffb5c5' : '#a8f1d8';
  context.stroke();
  return `url(${image.toDataURL()}) ${center} ${center}, crosshair`;
}

export class HairViewer {
  constructor(canvas, onSelect) {
    this.renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.scene = new THREE.Scene();
    this.perspective = new THREE.PerspectiveCamera(36, 1, .001, 10000);
    this.orthographic = new THREE.OrthographicCamera(-1, 1, 1, -1, .01, 50);
    this.orthoScale = 1;
    this.camera = this.perspective;
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.scene.add(new THREE.HemisphereLight(0xe8d9ff, 0x544354, 2.7));
    const light = new THREE.DirectionalLight(0xffebd4, 3);
    light.position.set(2, 3, 4);
    this.scene.add(light);
    const rim = new THREE.DirectionalLight(0xb295ff, 2);
    rim.position.set(-3, 1, -2);
    this.scene.add(rim);

    this.content = new THREE.Group();
    this.hair = new THREE.Group();
    this.context = new THREE.Group();
    this.referenceHair = new THREE.Group();
    this.referenceMode = 'off';
    this.referenceMaterials = [];
    this.referenceTint = new THREE.MeshStandardMaterial({
      color:0xefbd79, roughness:.8, transparent:true, opacity:.24, depthWrite:false,
    });
    this.renderSize = new THREE.Vector2();
    this.markers = new THREE.Group();
    this.pointLine = new THREE.Group();
    this.sectionDraft = new THREE.Group();
    this.flowRegions = new THREE.Group();
    this.content.add(this.context, this.hair, this.referenceHair);
    this.scene.add(this.content, this.markers, this.pointLine, this.sectionDraft, this.flowRegions);
    this.pointPins = canvas.parentElement.querySelector('#pointPins');

    const markerShape = new THREE.SphereGeometry(1, 12, 8);
    this.rootMarker = new THREE.Mesh(markerShape, new THREE.MeshBasicMaterial({color: 0x74d9ac, depthTest: false}));
    this.tipMarker = new THREE.Mesh(markerShape, new THREE.MeshBasicMaterial({color: 0xf6b083, depthTest: false}));
    this.rootMarker.renderOrder = this.tipMarker.renderOrder = 4;
    this.markers.add(this.rootMarker, this.tipMarker);
    this.markers.visible = false;

    this.loader = new GLTFLoader();
    this.radius = .3;
    this.center = new THREE.Vector3();
    this.lines = [];
    this.painted = [];
    this.strandMeshes = new Map();
    this.ticket = 0;
    this.frameKey = null;
    this.framing = 1;
    this.view = 'fit';
    this.index = -1;
    this.showAll = true;
    this.connected = [];
    this.allowed = null;
    this.reversed = false;
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(canvas.parentElement);

    this.pickRay = new THREE.Raycaster();
    this.brushNdc = new THREE.Vector2();
    let start;
    canvas.addEventListener('pointerdown', event => {
      if (event.button === 0 && this.surfaceBrush) {
        this.brushStroke = {faces:new Set(),last:null,dirty:false,pointerId:event.pointerId};
        canvas.setPointerCapture(event.pointerId);
        this.sampleBrush(event);
        return;
      }
      start = event.button === 0 ? [event.clientX, event.clientY] : undefined;
    });
    canvas.addEventListener('pointermove', event => {
      if (this.brushStroke?.pointerId === event.pointerId) this.sampleBrush(event);
    });
    const cancelStroke = event => {
      if (this.brushStroke?.pointerId !== event.pointerId) return;
      this.brushStroke = null;
      this.surfaceBrush?.preview([]);
    };
    canvas.addEventListener('pointercancel', cancelStroke);
    canvas.addEventListener('lostpointercapture', cancelStroke);
    canvas.addEventListener('pointerup', event => {
      if (this.brushStroke?.pointerId === event.pointerId && event.button === 0) {
        this.sampleBrush(event);
        const faces = [...this.brushStroke.faces];
        this.brushStroke = null;
        this.surfaceBrush?.finish(faces);
        return;
      }
      const point = start;
      start = undefined;
      if (!point || Math.hypot(event.clientX - point[0], event.clientY - point[1]) > 5) return;
      if (this.regionSelect) {
        const ray = this.pointerRay(event);
        const [region] = ray.intersectObjects(this.flowRegions.children,false);
        const [visible] = ray.intersectObject(this.context,true);
        if (region && (!visible || visible.distance + .004 >= region.distance)) {
          this.regionSelect(region.object.userData.strandId);
        }
        return;
      }
      if (this.pointPick) {
        this.pointPick.onHit(this.pickOnSurface(event, this.pointPick));
        return;
      }
      const ray = this.pointerRay(event);
      ray.params.Line.threshold = this.radius * .018;
      const [hit] = ray.intersectObjects(this.lines.filter(line => line.visible));
      if (hit) onSelect(hit.object.userData.index);
    });
    const tick = () => {
      requestAnimationFrame(tick);
      this.controls.update();
      if (this.brushStroke?.dirty) {
        this.brushStroke.dirty = false;
        this.surfaceBrush.preview(this.brushStroke.faces);
      }
      this.renderFrame();
      this.positionPointPins();
    };
    tick();
  }

  renderFrame() {
    if (!this.referenceMode.startsWith('split')) {
      this.renderer.render(this.scene,this.camera);
      return;
    }
    const renderer = this.renderer;
    const {x:width,y:height} = renderer.getSize(this.renderSize);
    const half = Math.floor(width/2);
    const hairVisible = this.hair.visible, draftVisible = this.sectionDraft.visible;
    renderer.setScissorTest(true);
    this.referenceHair.visible = true;
    this.hair.visible = this.sectionDraft.visible = false;
    renderer.setViewport(0,0,half,height);
    renderer.setScissor(0,0,half,height);
    renderer.render(this.scene,this.camera);
    const overlay = this.referenceMode === 'split-overlay' && this.referenceTint.opacity > 0;
    this.referenceHair.visible = overlay;
    if (overlay) this.tintReference(true);
    this.hair.visible = hairVisible;
    this.sectionDraft.visible = draftVisible;
    renderer.setViewport(half,0,width-half,height);
    renderer.setScissor(half,0,width-half,height);
    renderer.render(this.scene,this.camera);
    if (overlay) this.tintReference(false);
    this.referenceHair.visible = false;
    renderer.setScissorTest(false);
    renderer.setViewport(0,0,width,height);
  }

  tintReference(enabled) {
    for (const [mesh,material] of this.referenceMaterials) mesh.material = enabled ? this.referenceTint : material;
  }

  setReferenceOpacity(opacity) {
    this.referenceTint.opacity = opacity;
    if (this.referenceMode === 'overlay') this.referenceHair.visible = opacity > 0;
  }

  resize() {
    const {clientWidth: width, clientHeight: height} = this.renderer.domElement.parentElement;
    if (!width || !height) return;
    const aspect = (this.referenceMode.startsWith('split') ? Math.floor(width/2) : width) / height;
    this.renderer.setSize(width, height, false);
    this.perspective.aspect = aspect;
    this.perspective.updateProjectionMatrix();
    if (this.camera === this.orthographic) {
      const scale = this.orthoScale / 2;
      this.camera.top = scale * Math.max(1, 1 / aspect);
      this.camera.bottom = -this.camera.top;
      this.camera.right = scale * Math.max(1, aspect);
      this.camera.left = -this.camera.right;
      this.camera.updateProjectionMatrix();
    }
  }

  clear({resetFrame = true} = {}) {
    this.ticket++;
    this.tintReference(false);
    this.referenceMaterials = [];
    for (const group of [this.hair, this.context, this.referenceHair]) {
      for (const child of group.children) dispose(child);
      group.clear();
    }
    this.referenceMode = 'off';
    this.lines = [];
    this.painted = [];
    this.strandMeshes.clear();
    this.markers.visible = false;
    this.clearPointFlow();
    this.showSectionDraft(null);
    this.headAsset = null;
    this.showFlowRegions(null);
    this.setSurfaceBrush(null);
    if (resetFrame) this.frameKey = null;
  }

  showSectionDraft(draft) {
    for (const child of this.sectionDraft.children) dispose(child);
    this.sectionDraft.clear();
    this.hair.visible = !draft;
    if (!draft) return;
    let scalp;
    if (this.headAsset && Object.values(draft.settings).some(setting => setting?.scalpInset !== undefined)) {
      const {asset,url} = this.headAsset;
      if (this.headSpatial?.url !== url) {
        asset.updateWorldMatrix(true,true);
        const triangles = [];
        asset.traverse(item => {
          if (!item.isMesh) return;
          for (const triangle of meshTriangles(item.geometry,item.matrixWorld)) triangles.push(triangle);
        });
        this.headSpatial = {url,surface:scalpSurface(triangles)};
      }
      scalp = this.headSpatial.surface;
    }
    this.sectionDraft.add(sectionScene(draft.cards,draft.settings,draft.strand,draft.range,draft.strands,draft.fitted,scalp));
  }

  showFlowRegions(choices, select) {
    for (const child of this.flowRegions.children) dispose(child);
    this.flowRegions.clear();
    this.surfaceRegions = null;
    this.regionSelect = select ?? null;
    for (const choice of choices ?? []) {
      const mesh = new THREE.Mesh(surfaceGeometry(choice.surface),new THREE.MeshBasicMaterial({
        color:choice.color, transparent:true, opacity:choice.opacity ?? .5, side:THREE.DoubleSide, depthWrite:false,
        polygonOffset:true, polygonOffsetFactor:-1, polygonOffsetUnits:-1,
      }));
      mesh.userData.strandId = choice.id;
      mesh.renderOrder = 3;
      this.flowRegions.add(mesh);
    }
    this.flowRegions.updateMatrixWorld(true);
  }

  showSurfaceRegions(surface, groups, activeId, mask, select) {
    if (this.surfaceRegions?.surface !== surface) {
      this.showFlowRegions(null);
      this.surfaceRegions = {surface,meshes:new Map()};
    }
    const {meshes} = this.surfaceRegions;
    const groupIds = new Set(groups.map(group => group.id));
    for (const [id,mesh] of meshes) {
      if (groupIds.has(id)) continue;
      this.flowRegions.remove(mesh);
      dispose(mesh);
      meshes.delete(id);
    }
    const selected = new Set(mask);
    this.regionSelect = select;
    for (const group of groups) {
      let mesh = meshes.get(group.id);
      if (!mesh) {
        const geometry = new THREE.BufferGeometry();
        const positions = new THREE.Float32BufferAttribute(surface.vertices,3);
        const IndexArray = positions.count > 65535 ? Uint32Array : Uint16Array;
        geometry.setAttribute('position',positions);
        geometry.setIndex(new THREE.BufferAttribute(new IndexArray(surface.faces.length),1).setUsage(THREE.DynamicDrawUsage));
        mesh = new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({
          color:group.color, transparent:true, side:THREE.DoubleSide, depthWrite:false,
          polygonOffset:true, polygonOffsetFactor:-1, polygonOffsetUnits:-1,
        }));
        mesh.userData.strandId = group.id;
        mesh.renderOrder = 3;
        meshes.set(group.id,mesh);
        this.flowRegions.add(mesh);
        mesh.updateMatrixWorld(true);
      }
      const active = group.id === activeId;
      mesh.material.color.setHex(group.color);
      mesh.material.opacity = active ? .66 : .24;
      const index = mesh.geometry.index;
      let count = 0, firstChange = index.array.length, lastChange = -1;
      for (const face of active ? mask : group.faces) {
        if (!active && selected.has(face)) continue;
        for (let vertex = 0; vertex < 3; vertex++) {
          const value = surface.faces[face*3+vertex];
          if (index.array[count] !== value) {
            index.array[count] = value;
            firstChange = Math.min(firstChange,count);
            lastChange = count;
          }
          count++;
        }
      }
      mesh.geometry.setDrawRange(0,count);
      mesh.visible = count > 0;
      if (lastChange >= 0) {
        index.addUpdateRange(firstChange,lastChange-firstChange+1);
        index.needsUpdate = true;
      }
    }
  }

  clearPointFlow() {
    this.setPointFlow(null);
    if (this.pointSurface) dispose(this.pointSurface);
    this.pointSurface = null;
    this.pointSurfaceData = null;
  }

  setSurfaceBrush(brush) {
    if (brush?.surface !== this.brushSurface) {
      if (this.brushMesh) dispose(this.brushMesh);
      this.brushMesh = brush ? new THREE.Mesh(surfaceGeometry(brush.surface),
        new THREE.MeshBasicMaterial({side:THREE.DoubleSide})) : null;
      this.brushSurface = brush?.surface;
    }
    this.surfaceBrush = brush;
    this.brushStroke = null;
    this.controls.mouseButtons.LEFT = brush ? null : THREE.MOUSE.ROTATE;
    if (brush) this.setSurfaceBrushRadius(brush.radius);
    else {
      this.brushCursorKey = null;
      this.renderer.domElement.style.cursor = '';
    }
  }

  setSurfaceBrushRadius(radius) {
    if (!this.surfaceBrush) return;
    this.surfaceBrush.radius = radius;
    const key = `${this.surfaceBrush.tool}:${radius}`;
    if (key === this.brushCursorKey) return;
    this.renderer.domElement.style.cursor = circularCursor(radius,this.surfaceBrush.tool);
    this.brushCursorKey = key;
  }

  sampleBrush(event) {
    const brush = this.surfaceBrush, stroke = this.brushStroke;
    if (!brush || !stroke) return;
    const point = [event.clientX,event.clientY], last = stroke.last ?? point;
    const span = Math.hypot(point[0]-last[0],point[1]-last[1]);
    const steps = Math.max(1,Math.min(12,Math.ceil(span/(brush.radius*.65))));
    if (stroke.last && span < 2) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const previousSize = stroke.faces.size;
    for (let step=1;step<=steps;step++) {
      const x = last[0]+(point[0]-last[0])*step/steps, y = last[1]+(point[1]-last[1])*step/steps;
      for (const [dx,dy] of brushSamples) {
        this.brushNdc.set((x+dx*brush.radius-rect.left)/rect.width*2-1,1-(y+dy*brush.radius-rect.top)/rect.height*2);
        const ray = this.pickRay;
        ray.setFromCamera(this.brushNdc,this.camera);
        const [hit] = ray.intersectObject(this.brushMesh,false);
        if (!hit) continue;
        const [cover] = ray.intersectObject(this.context,true);
        if (!cover || cover.distance + .003 >= hit.distance) stroke.faces.add(hit.faceIndex);
      }
    }
    stroke.last = point;
    if (stroke.faces.size !== previousSize) stroke.dirty = true;
  }

  pointerRay(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2);
    this.pickRay.setFromCamera(ndc, this.camera);
    return this.pickRay;
  }

  pickOnSurface(event, options) {
    const ray = this.pointerRay(event);
    const [candidate] = ray.intersectObject(this.pointSurface, false);
    const [visible] = ray.intersectObject(this.context, true);
    const position = candidate?.point.toArray();
    if (candidate && (!visible || visible.distance + .004 >= candidate.distance) && options.accepts(position, candidate.faceIndex)) {
      return {position, triangle: candidate.faceIndex};
    }
    const rect = this.renderer.domElement.getBoundingClientRect();
    let nearest = null, bestDistance = options.snapDistance ?? 16;
    for (const mark of options.snap ?? []) {
      const point = new THREE.Vector3(...mark.position);
      const view = point.clone().project(this.camera);
      if (Math.abs(view.x) > 1 || Math.abs(view.y) > 1 || Math.abs(view.z) > 1) continue;
      const x = rect.left + (view.x + 1) * rect.width / 2;
      const y = rect.top + (1 - view.y) * rect.height / 2;
      const gap = Math.hypot(x - event.clientX, y - event.clientY);
      if (gap >= bestDistance) continue;
      ray.setFromCamera(new THREE.Vector2(view.x, view.y), this.camera);
      const [cover] = ray.intersectObject(this.context, true);
      if (cover && cover.distance + .006 < ray.ray.origin.distanceTo(point)) continue;
      nearest = mark;
      bestDistance = gap;
    }
    return nearest;
  }

  bindPointPin(pin, item) {
    let press = null, dragged = false;
    if (item.drop || item.dragPlane) {
      pin.dataset.draggablePoint = 'true';
      pin.onpointerdown = event => {
        if (event.button !== 0) return;
        press = [event.clientX, event.clientY];
        dragged = false;
        pin.setPointerCapture(event.pointerId);
      };
      pin.onpointerup = event => {
        if (!press) return;
        dragged = Math.hypot(event.clientX - press[0], event.clientY - press[1]) > 5;
        const start = press;
        press = null;
        if (!dragged) return;
        if (item.dragPlane) {
          const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(this.camera.getWorldDirection(new THREE.Vector3()),
            new THREE.Vector3(...item.position));
          const from = this.pointerRay({clientX:start[0],clientY:start[1]}).ray.intersectPlane(plane,new THREE.Vector3());
          const to = this.pointerRay(event).ray.intersectPlane(plane,new THREE.Vector3());
          if (from && to) item.dragPlane(to.sub(from).toArray());
        } else item.drop.onHit(this.pickOnSurface(event, item.drop));
      };
      pin.onpointercancel = () => { press = null; };
    }
    pin.onclick = () => { if (!dragged) item.onClick?.(); };
  }

  setPointFlow(state) {
    for (const child of this.pointLine.children) dispose(child);
    this.pointLine.clear();
    this.pointPick = state?.pick ?? null;
    this.pointMarkers = [];
    if (this.pointPins) {
      this.pointPins.replaceChildren();
      this.pointPins.hidden = !state;
    }
    if (!state) return;
    if (this.pointSurfaceData !== state.surface) {
      if (this.pointSurface) dispose(this.pointSurface);
      this.pointSurface = new THREE.Mesh(surfaceGeometry(state.surface),
        new THREE.MeshBasicMaterial({side: THREE.DoubleSide}));
      this.pointSurfaceData = state.surface;
    }
    for (const [moveFaces,color] of [[state.moveFaces,0x56d9bd],[state.extraMoveFaces,0xeeb269]]) {
      if (!moveFaces?.length) continue;
      const {vertices, faces} = state.surface;
      const range = surfaceGeometry({vertices, faces:moveFaces.flatMap(i => faces.slice(3 * i, 3 * i + 3))});
      const material = new THREE.MeshBasicMaterial({color, transparent:true, opacity:.34,
        depthWrite:false, side:THREE.DoubleSide, polygonOffset:true, polygonOffsetFactor:-1, polygonOffsetUnits:-1});
      this.pointLine.add(new THREE.Mesh(range,material));
    }
    for (const [index, card] of [state.card,...state.others].entries()) {
      if (!card) continue;
      const {seq} = card;
      const current = index === 0;
      const path = new THREE.CatmullRomCurve3(seq.map(row => new THREE.Vector3(...row.slice(0, 3))));
      const geometry = new THREE.TubeGeometry(path, seq.length * 2, this.radius * (current ? .0044 : .0035), 5, false);
      const material = new THREE.MeshBasicMaterial({color: current ? state.color : state.otherColor ?? 0x8dbfe5,
        transparent:!current, opacity:current ? 1 : .83, depthTest:false, depthWrite:false});
      const curve = new THREE.Mesh(geometry, material);
      curve.renderOrder = current ? 3 : 2;
      this.pointLine.add(curve);
    }
    if (this.pointPins) {
      for (const item of state.markers) {
        const pin = document.createElement('button');
        pin.type = 'button';
        pin.className = 'point-pin';
        pin.dataset.pointPin = item.id;
        pin.dataset.confirmed = String(item.confirmed);
        pin.dataset.locked = String(item.locked);
        if (item.dragPlane) pin.classList.add('point-arc-pin');
        pin.setAttribute('aria-pressed', String(item.active));
        pin.setAttribute('aria-label', t(item.label + ' · ' +
          (item.locked ? '已锁定' : item.confirmed ? '已标记' : '确认建议点')));
        pin.title = t(pin.getAttribute('aria-label'));
        pin.textContent = t(item.number);
        pin.disabled = !item.onClick;
        this.bindPointPin(pin, item);
        this.pointPins.append(pin);
        this.pointMarkers.push({pin, position: new THREE.Vector3(...item.position)});
      }
    }
    this.positionPointPins();
  }

  positionPointPins() {
    for (const {pin, position} of this.pointMarkers ?? []) {
      const projected = position.clone().project(this.camera);
      pin.hidden = Math.abs(projected.x) > 1 || Math.abs(projected.y) > 1 || Math.abs(projected.z) > 1;
      pin.style.left = ((projected.x * .5 + .5) * 100) + '%';
      pin.style.top = ((-projected.y * .5 + .5) * 100) + '%';
    }
  }

  createGuides(cards) {
    this.lines = cards.map((card, index) => {
      const points = card.seq.map(row => new THREE.Vector3(row[0], row[1], row[2]));
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      const material = new THREE.LineBasicMaterial({color: 0xae99c7, transparent: true, opacity: .8, depthTest: false});
      const line = new THREE.Line(geometry, material);
      line.renderOrder = 3;
      line.userData.index = index;
      line.userData.endpoints = [points[0], points.at(-1)];
      this.hair.add(line);
      return line;
    });
  }

  createMarks(strands) {
    strands.forEach((strand, index) => {
      for (const [view, path] of Object.entries(strand.marks ?? {})) {
        if (!Array.isArray(path) || path.length < 2) continue;
        const points = path.map(point => new THREE.Vector3(...point));
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const material = new THREE.LineDashedMaterial({
          color: 0xf2ce84, transparent: true, opacity: .8, dashSize: .008, gapSize: .005,
          depthTest: false, depthWrite: false,
        });
        const mark = new THREE.Line(geometry, material);
        mark.computeLineDistances();
        mark.renderOrder = 2;
        mark.userData = {index, view};
        this.context.add(mark);
        this.painted.push(mark);
      }
    });
  }

  styleModel(asset, kind) {
    if (kind === 'reference') return;
    if (kind === 'marks') {
      asset.traverse(object => {
        if (!object.isMesh) return;
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        for (const material of materials.filter(Boolean)) {
          material.polygonOffset = true;
          material.polygonOffsetFactor = -1;
          material.polygonOffsetUnits = -1;
        }
      });
      return;
    }
    const replacedMaterials = new Set();
    const textures = new Set();
    const replacement = new THREE.MeshStandardMaterial({
      color: kind === 'overlay' ? 0xaaa0ae : 0x9a7ea9,
      roughness: .68, metalness: .04, side: THREE.DoubleSide,
    });
    let styled = false;
    asset.traverse(object => {
      if (!object.isMesh) return;
      for (const existing of (Array.isArray(object.material) ? object.material : [object.material])) {
        if (existing) replacedMaterials.add(existing);
      }
      object.material = replacement;
      styled = true;
    });
    if (!styled) replacement.dispose();
    for (const material of replacedMaterials) {
      for (const value of Object.values(material)) {
        if (value?.isTexture) textures.add(value);
      }
      material.dispose();
    }
    textures.forEach(texture => texture.dispose());
  }

  indexMeshes(asset, strands) {
    asset.traverse(object => {
      const {hairbridge_strand_id, strandId, hairdeck_card_index: deckIndex} = object.userData;
      const id = hairbridge_strand_id ?? strandId;
      const index = id == null ? deckIndex : strands.findIndex(strand => String(strand.id) === String(id));
      if (!Number.isInteger(index) || index < 0) return;
      const matching = this.strandMeshes.get(index) ?? [];
      matching.push(object);
      this.strandMeshes.set(index, matching);
    });
  }

  async show({cards = [], strands = [], headUrl, meshUrl, coarseUrl, markMeshUrl, referenceHairUrl, referenceMode,
              referenceOpacity=.24,
              useMarks = false, comparisonKey = null, cameras, camera = null, preserveFrame = false,
              preserveMaterial = false, framing = 1}) {
    // Keep the last accepted frame while either version of its geometry loads.
    this.clear({resetFrame: !preserveFrame});
    const ticket = this.ticket;
    const inputs = [
      {url: headUrl, target: this.context, kind: 'reference', head:true},
      {url: coarseUrl, target: this.context, kind: 'overlay'},
      {url: referenceHairUrl, target: this.referenceHair, kind: 'overlay'},
      {url: markMeshUrl, target: this.context, kind: 'marks'},
      {url: meshUrl, target: this.hair, kind: preserveMaterial ? 'reference' : 'result'},
    ].filter(item => item.url);
    const settled = await Promise.allSettled(inputs.map(async item => ({
      ...item, asset: (await this.loader.loadAsync(item.url)).scene,
    })));
    const fetched = settled.filter(item => item.status === 'fulfilled').map(item => item.value);
    if (ticket !== this.ticket) {
      fetched.forEach(item => dispose(item.asset));
      return false;
    }
    const failure = settled.find(item => item.status === 'rejected');
    if (failure) {
      fetched.forEach(item => dispose(item.asset));
      throw failure.reason;
    }
    this.referenceMode = referenceHairUrl ? referenceMode : 'off';
    this.referenceHair.visible = false;
    for (const {asset,kind,target,head,url} of fetched) {
      this.styleModel(asset, kind);
      target.add(asset);
      if (head) this.headAsset = {asset,url};
      if (target === this.hair) this.indexMeshes(asset, strands);
      if (target === this.referenceHair) asset.traverse(mesh => {
        if (mesh.isMesh) this.referenceMaterials.push([mesh,mesh.material]);
      });
    }
    this.tintReference(this.referenceMode === 'overlay');
    this.setReferenceOpacity(referenceOpacity);
    this.cameras = cameras ?? {};
    this.framing = framing;
    this.createGuides(cards);
    if (useMarks) this.createMarks(strands);
    if (!comparisonKey || this.frameKey !== comparisonKey) {
      this.fit(camera ?? 'fit');
      this.frameKey = comparisonKey;
    } else this.resize();
    this.select(this.index, this.showAll, this.connected, this.allowed, this.reversed);
    return true;
  }

  fit(view = 'fit') {
    const bounds = new THREE.Box3().setFromObject(this.content);
    if (bounds.isEmpty()) return;
    bounds.getCenter(this.center);
    this.radius = Math.max(bounds.getSize(new THREE.Vector3()).length() / 2, .01);
    this.cameraView(view);
  }

  cameraView(view) {
    view = canonicalView(view);
    if (!Object.hasOwn(directions, view)) view = 'fit';
    this.view = view;
    const free = view === 'fit';
    const fixed = free ? null : savedCamera(this.cameras, view);
    this.camera = free ? this.perspective : this.orthographic;
    const direction = new THREE.Vector3(...(fixed?.direction ?? directions[view])).normalize();
    const target = fixed ? new THREE.Vector3(...fixed.target) : this.center;
    const distance = fixed ? 2.5 : this.radius * 3.25 * this.framing;
    this.orthoScale = fixed?.scale ?? this.radius * 2.2 * this.framing;
    this.camera.near = this.radius / 1000;
    this.camera.far = distance + this.radius * 100;
    // Set the camera up-axis before building controls; OrbitControls caches that axis.
    const pole = Math.abs(direction.y) > .999;
    this.camera.up.set(0, pole ? 0 : 1, pole ? -Math.sign(direction.y) : 0);
    this.controls.dispose();
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    if (this.surfaceBrush) this.controls.mouseButtons.LEFT = null;
    this.controls.enableDamping = true;
    this.controls.enableRotate = free;
    this.controls.target.copy(target);
    this.camera.position.copy(target).addScaledVector(direction, distance);
    this.camera.zoom = 1;
    this.controls.update();
    this.resize();
    this.camera.updateMatrixWorld();
    this.positionPointPins();
    this.updateMarks();
  }

  updateMarks() {
    for (const item of this.painted) {
      const matchesView = canonicalView(item.userData.view) === (this.view === 'fit' ? 'input' : this.view);
      item.visible = matchesView && (this.index < 0 || this.index === item.userData.index);
    }
  }

  select(index, all, connected = [], allowed = null, reversed = false) {
    this.index = index;
    this.showAll = all;
    this.connected = connected;
    this.allowed = allowed;
    this.reversed = reversed;
    const visible = i => i === index || connected.includes(i) || (all || index < 0) && (!allowed || allowed.includes(i));
    this.lines.forEach((line, i) => {
      const match = i === index;
      const relationship = connected.includes(i);
      line.visible = visible(i);
      line.material.color.setHex(match ? 0xebc2ff : relationship ? 0xbddde3 : 0x9e8ab6);
      line.material.opacity = index < 0 ? .8 : match ? 1 : relationship ? .8 : .25;
    });
    for (const [i, objects] of this.strandMeshes) {
      for (const item of objects) item.visible = visible(i);
    }
    this.updateMarks();
    const endpoints = this.lines[index]?.userData.endpoints;
    this.markers.visible = !!endpoints;
    if (endpoints) {
      [this.rootMarker, this.tipMarker].forEach((marker, i) => {
        marker.position.copy(endpoints[reversed ? 1 - i : i]);
        marker.scale.setScalar(this.radius * .016);
      });
    }
  }
}
