// Overlay 3D léger sans dépendance externe.
// Représentation par projection manuelle avec caméra orbitale.

const MAGNET_DISTANCE = 48;
const GRID_COLOR = 'rgba(255,255,255,0.06)';

export class Constellation3DOverlay {
  constructor(root, options = {}) {
    this.root = root;
    this.bus = options.bus;
    this.getNodes = options.getNodes;
    this.onNodeMove = options.onNodeMove || (() => {});
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d');
    this.root.innerHTML = '';
    this.root.appendChild(this.canvas);
    this.dimensions = { width: 0, height: 0 };
    this.nodes = new Map();
    this.center = { x: 0, y: 0 };
    this.camera = {
      theta: Math.PI / 6,
      phi: Math.PI / 8,
      radius: 420,
      targetRadius: 420,
      minRadius: 180,
      maxRadius: 900,
    };
    this.dragState = null;
    this.hoverNode = null;
    this.showGrid = true;
    this.animationFrame = null;
    this.pointerState = { x: 0, y: 0 };
    this.boundResize = () => this.resize();
    this.unsubscribers = [];
  }

  async init() {
    this.resize();
    this.attachEvents();
    this.start();
  }

  attachEvents() {
    this.canvas.addEventListener('pointerdown', (event) => this.handlePointerDown(event));
    this.canvas.addEventListener('pointermove', (event) => this.handlePointerMove(event));
    this.canvas.addEventListener('pointerup', (event) => this.handlePointerUp(event));
    this.canvas.addEventListener('pointerleave', (event) => this.handlePointerUp(event));
    this.canvas.addEventListener('wheel', (event) => this.handleWheel(event), { passive: false });
    window.addEventListener('resize', this.boundResize);
    if (this.bus) {
      this.unsubscribers.push(this.bus.on('system:update', () => this.updateFrom2D()));
      this.unsubscribers.push(this.bus.on('system:change', () => this.updateFrom2D()));
      this.unsubscribers.push(this.bus.on('overlay:ready', () => this.updateFrom2D()));
    }
  }

  resize() {
    const rect = this.root.getBoundingClientRect();
    this.dimensions.width = rect.width;
    this.dimensions.height = rect.height;
    this.canvas.width = rect.width * window.devicePixelRatio;
    this.canvas.height = rect.height * window.devicePixelRatio;
    this.canvas.style.width = `${rect.width}px`;
    this.canvas.style.height = `${rect.height}px`;
    if (this.ctx) {
      this.ctx.setTransform(1, 0, 0, 1, 0, 0);
      this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    }
  }

  start() {
    const loop = () => {
      this.render();
      this.animationFrame = requestAnimationFrame(loop);
    };
    this.animationFrame = requestAnimationFrame(loop);
  }

  stop() {
    if (this.animationFrame) {
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }
  }

  updateFrom2D(nodes = null) {
    const source = Array.isArray(nodes) ? nodes : this.getNodes?.() || [];
    this.nodes.clear();
    const centroid = source.reduce(
      (acc, node) => {
        acc.x += node.x;
        acc.y += node.y;
        return acc;
      },
      { x: 0, y: 0 },
    );
    const count = source.length || 1;
    centroid.x /= count;
    centroid.y /= count;
    this.center = centroid;
    source.forEach((node) => {
      this.nodes.set(node.id, {
        id: node.id,
        label: node.label || node.id,
        x: node.x - centroid.x,
        y: node.y - centroid.y,
        z: node.group ? node.group.length * 6 : 0,
        color: node.color || '#6c63ff',
        r: Math.max(6, Math.min(26, node.r || 12)),
      });
    });
  }

  project(node) {
    const { theta, phi } = this.camera;
    this.camera.radius += (this.camera.targetRadius - this.camera.radius) * 0.08;
    const radius = this.camera.radius;
    const cosTheta = Math.cos(theta);
    const sinTheta = Math.sin(theta);
    const cosPhi = Math.cos(phi);
    const sinPhi = Math.sin(phi);
    const x = node.x;
    const y = node.y;
    const z = node.z;
    const camX = radius * cosPhi * cosTheta;
    const camY = radius * sinPhi;
    const camZ = radius * cosPhi * sinTheta;
    const relX = x - camX;
    const relY = y - camY;
    const relZ = z - camZ;
    const dist = Math.sqrt(relX ** 2 + relY ** 2 + relZ ** 2);
    const fov = 400;
    const scale = fov / (fov + relZ + radius * 0.5);
    const screenX = this.dimensions.width / 2 + relX * scale;
    const screenY = this.dimensions.height / 2 + relY * scale;
    return { x: screenX, y: screenY, scale: Math.max(0.35, scale), dist };
  }

  handlePointerDown(event) {
    this.canvas.setPointerCapture(event.pointerId);
    const node = this.pickNode(event.offsetX, event.offsetY);
    if (node) {
      this.dragState = {
        id: node.id,
        startX: event.offsetX,
        startY: event.offsetY,
        node: this.nodes.get(node.id),
      };
    } else {
      this.dragState = {
        orbit: true,
        startX: event.clientX,
        startY: event.clientY,
        theta: this.camera.theta,
        phi: this.camera.phi,
      };
    }
  }

  handlePointerMove(event) {
    this.pointerState.x = event.offsetX;
    this.pointerState.y = event.offsetY;
    if (this.dragState?.orbit) {
      const deltaX = event.clientX - this.dragState.startX;
      const deltaY = event.clientY - this.dragState.startY;
      this.camera.theta = this.dragState.theta + deltaX * 0.005;
      this.camera.phi = Math.min(Math.PI / 2.2, Math.max(-Math.PI / 2.2, this.dragState.phi + deltaY * 0.004));
    } else if (this.dragState && this.dragState.id) {
      const node = this.nodes.get(this.dragState.id);
      if (!node) return;
      const dx = event.offsetX - this.dragState.startX;
      const dy = event.offsetY - this.dragState.startY;
      node.x += dx;
      node.y += dy;
      this.dragState.startX = event.offsetX;
      this.dragState.startY = event.offsetY;
      this.onNodeMove(
        node.id,
        { x: node.x + this.center.x, y: node.y + this.center.y },
        'move',
      );
    } else {
      const hovered = this.pickNode(event.offsetX, event.offsetY);
      this.hoverNode = hovered ? hovered.id : null;
    }
  }

  handlePointerUp(event) {
    if (this.dragState) {
      if (this.dragState.id && this.nodes.has(this.dragState.id)) {
        const node = this.nodes.get(this.dragState.id);
        this.onNodeMove(
          node.id,
          { x: node.x + this.center.x, y: node.y + this.center.y },
          'end',
        );
      }
    }
    this.dragState = null;
    this.canvas.releasePointerCapture(event.pointerId);
  }

  handleWheel(event) {
    event.preventDefault();
    const delta = event.deltaY > 0 ? 1 : -1;
    this.camera.targetRadius = Math.min(
      this.camera.maxRadius,
      Math.max(this.camera.minRadius, this.camera.targetRadius + delta * 32),
    );
  }

  pickNode(x, y) {
    let closest = null;
    let min = Infinity;
    this.nodes.forEach((node) => {
      const projected = this.project(node);
      const dx = projected.x - x;
      const dy = projected.y - y;
      const distance = Math.sqrt(dx ** 2 + dy ** 2);
      if (distance < node.r * projected.scale + 8 && distance < min) {
        closest = { id: node.id, distance };
        min = distance;
      }
    });
    return closest;
  }

  drawGrid() {
    if (!this.showGrid || !this.ctx) return;
    const step = 64;
    const { width, height } = this.dimensions;
    this.ctx.save();
    this.ctx.strokeStyle = GRID_COLOR;
    this.ctx.lineWidth = 1;
    for (let x = -width; x < width * 2; x += step) {
      this.ctx.beginPath();
      this.ctx.moveTo(x, -height);
      this.ctx.lineTo(x, height * 2);
      this.ctx.stroke();
    }
    for (let y = -height; y < height * 2; y += step) {
      this.ctx.beginPath();
      this.ctx.moveTo(-width, y);
      this.ctx.lineTo(width * 2, y);
      this.ctx.stroke();
    }
    this.ctx.restore();
  }

  render() {
    if (!this.ctx) return;
    const { width, height } = this.dimensions;
    this.ctx.clearRect(0, 0, width, height);
    this.drawGrid();
    const magnetPairs = [];
    const nodes = Array.from(this.nodes.values());
    nodes.forEach((node) => {
      nodes.forEach((other) => {
        if (other === node) return;
        const dx = node.x - other.x;
        const dy = node.y - other.y;
        const dist = Math.sqrt(dx ** 2 + dy ** 2);
        if (dist > 0 && dist < MAGNET_DISTANCE) {
          magnetPairs.push([node, other]);
        }
      });
    });
    magnetPairs.forEach(([a, b]) => {
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 };
      const projected = this.project(mid);
      const radius = 14 * projected.scale;
      this.ctx.beginPath();
      this.ctx.strokeStyle = 'rgba(255,255,255,0.18)';
      this.ctx.lineWidth = 1;
      this.ctx.arc(projected.x, projected.y, radius, 0, Math.PI * 2);
      this.ctx.stroke();
    });
    nodes
      .map((node) => ({ node, projected: this.project(node) }))
      .sort((a, b) => a.projected.dist - b.projected.dist)
      .forEach(({ node, projected }) => {
        const radius = node.r * projected.scale;
        this.ctx.beginPath();
        this.ctx.fillStyle = node.color;
        this.ctx.globalAlpha = 0.88;
        this.ctx.arc(projected.x, projected.y, radius, 0, Math.PI * 2);
        this.ctx.fill();
        if (this.hoverNode === node.id) {
          this.ctx.strokeStyle = 'rgba(255,255,255,0.8)';
          this.ctx.lineWidth = 2;
          this.ctx.stroke();
        }
        this.ctx.globalAlpha = 1;
        this.ctx.fillStyle = 'rgba(0,0,0,0.6)';
        this.ctx.fillRect(projected.x - radius, projected.y + radius + 4, node.label.length * 7 * projected.scale, 18);
        this.ctx.fillStyle = 'white';
        this.ctx.font = `${12 * projected.scale}px/1.2 "Inter", sans-serif`;
        this.ctx.fillText(node.label, projected.x - radius + 6, projected.y + radius + 18);
      });
  }

  destroy() {
    this.stop();
    window.removeEventListener('resize', this.boundResize);
    this.unsubscribers.forEach((fn) => fn?.());
    this.unsubscribers = [];
    this.root.innerHTML = '';
    this.nodes.clear();
  }

  setGrid(value) {
    this.showGrid = Boolean(value);
  }
}
