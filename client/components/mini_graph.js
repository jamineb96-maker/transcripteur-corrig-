const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * Rend un mini-graphe radial dans un conteneur donné.
 *
 * @param {HTMLElement} target Élément qui accueillera le SVG.
 * @param {{nodes?: Array, edges?: Array}} options Données du graphe.
 * @returns {{destroy: Function, highlight: Function, clear: Function}}
 */
export function renderMiniGraph(target, options = {}) {
  if (!target) {
    return {
      destroy() {},
      highlight() {},
      clear() {},
    };
  }
  const { nodes = [], edges = [] } = options;
  target.innerHTML = '';

  const width = Math.max(target.clientWidth || 0, 320);
  const height = Math.max(target.clientHeight || 0, 260);

  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('role', 'presentation');
  svg.classList.add('mini-graph');

  const defs = document.createElementNS(SVG_NS, 'defs');
  const pattern = document.createElementNS(SVG_NS, 'pattern');
  pattern.setAttribute('id', 'constellation-grid');
  pattern.setAttribute('patternUnits', 'userSpaceOnUse');
  pattern.setAttribute('width', '24');
  pattern.setAttribute('height', '24');
  const patternRect = document.createElementNS(SVG_NS, 'rect');
  patternRect.setAttribute('width', '24');
  patternRect.setAttribute('height', '24');
  patternRect.setAttribute('fill', 'rgba(106, 76, 147, 0.06)');
  const patternPath = document.createElementNS(SVG_NS, 'path');
  patternPath.setAttribute('d', 'M 0 24 L 24 24 24 0');
  patternPath.setAttribute('stroke', 'rgba(106, 76, 147, 0.1)');
  patternPath.setAttribute('stroke-width', '1');
  pattern.appendChild(patternRect);
  pattern.appendChild(patternPath);
  defs.appendChild(pattern);
  svg.appendChild(defs);

  const background = document.createElementNS(SVG_NS, 'rect');
  background.setAttribute('class', 'graph-background');
  background.setAttribute('width', String(width));
  background.setAttribute('height', String(height));
  svg.appendChild(background);

  const adjacency = new Map();
  edges.forEach((edge) => {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, new Set());
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, new Set());
    adjacency.get(edge.source).add(edge.target);
    adjacency.get(edge.target).add(edge.source);
  });

  const nodePositions = new Map();
  const patientNodes = nodes.filter((n) => n.kind === 'patient');
  const resourceNodes = nodes.filter((n) => n.kind === 'resource');
  const tagNodes = nodes.filter((n) => n.kind === 'tag');

  const center = { x: width / 2, y: height / 2 };
  const baseRadius = Math.min(width, height) / 2 - 36;
  const resourceRadius = Math.max(baseRadius, 80);
  const tagRadius = resourceRadius + 45;

  patientNodes.forEach((node) => {
    nodePositions.set(node.id, { x: center.x, y: center.y });
  });

  function placeRadial(nodesList, radius, offset = 0) {
    const count = nodesList.length;
    if (!count) return;
    nodesList.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / count + offset;
      const x = center.x + radius * Math.cos(angle);
      const y = center.y + radius * Math.sin(angle);
      nodePositions.set(node.id, { x, y });
    });
  }

  placeRadial(resourceNodes, resourceRadius, Math.PI / 6);
  placeRadial(tagNodes, tagRadius, Math.PI / 12);

  const edgesGroup = document.createElementNS(SVG_NS, 'g');
  edgesGroup.setAttribute('stroke-linecap', 'round');
  const edgeElements = [];
  edges.forEach((edge) => {
    const sourcePos = nodePositions.get(edge.source);
    const targetPos = nodePositions.get(edge.target);
    if (!sourcePos || !targetPos) return;
    const line = document.createElementNS(SVG_NS, 'line');
    line.setAttribute('class', 'graph-edge');
    line.dataset.source = edge.source;
    line.dataset.target = edge.target;
    line.setAttribute('x1', sourcePos.x.toFixed(2));
    line.setAttribute('y1', sourcePos.y.toFixed(2));
    line.setAttribute('x2', targetPos.x.toFixed(2));
    line.setAttribute('y2', targetPos.y.toFixed(2));
    if (typeof edge.weight === 'number') {
      const width = Math.max(1.2, Math.min(2.4, edge.weight));
      line.setAttribute('stroke-width', String(width));
    }
    edgesGroup.appendChild(line);
    edgeElements.push(line);
  });
  svg.appendChild(edgesGroup);

  const nodesGroup = document.createElementNS(SVG_NS, 'g');
  const nodeElements = new Map();

  nodes.forEach((node) => {
    const pos = nodePositions.get(node.id);
    if (!pos) return;
    const group = document.createElementNS(SVG_NS, 'g');
    group.setAttribute('class', 'graph-node');
    group.dataset.id = node.id;
    group.dataset.kind = node.kind || 'resource';
    const circle = document.createElementNS(SVG_NS, 'circle');
    circle.setAttribute('cx', pos.x.toFixed(2));
    circle.setAttribute('cy', pos.y.toFixed(2));
    circle.setAttribute('r', node.kind === 'patient' ? '18' : '12');
    group.appendChild(circle);
    const text = document.createElementNS(SVG_NS, 'text');
    text.setAttribute('x', pos.x.toFixed(2));
    text.setAttribute('y', (pos.y + (node.kind === 'patient' ? 32 : 24)).toFixed(2));
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'middle');
    text.textContent = node.label || node.id;
    group.appendChild(text);
    nodesGroup.appendChild(group);
    nodeElements.set(node.id, group);
  });

  svg.appendChild(nodesGroup);
  target.appendChild(svg);

  function toggleHighlight(nodeIds) {
    const ids = new Set(nodeIds || []);
    const expanded = new Set(ids);
    ids.forEach((id) => {
      const neighbors = adjacency.get(id);
      if (neighbors) {
        neighbors.forEach((neighbor) => expanded.add(neighbor));
      }
    });
    nodeElements.forEach((el, id) => {
      el.classList.toggle('is-highlighted', expanded.has(id));
    });
    edgeElements.forEach((edge) => {
      const sourceActive = expanded.has(edge.dataset.source);
      const targetActive = expanded.has(edge.dataset.target);
      edge.classList.toggle('is-highlighted', sourceActive && targetActive);
    });
  }

  const listeners = [];
  nodeElements.forEach((el, id) => {
    const enter = () => toggleHighlight([id]);
    const leave = () => toggleHighlight([]);
    el.addEventListener('mouseenter', enter);
    el.addEventListener('mouseleave', leave);
    listeners.push({ el, enter, leave });
  });

  return {
    highlight(nodeIds) {
      toggleHighlight(Array.isArray(nodeIds) ? nodeIds : [nodeIds]);
    },
    clear() {
      toggleHighlight([]);
    },
    destroy() {
      listeners.forEach(({ el, enter, leave }) => {
        el.removeEventListener('mouseenter', enter);
        el.removeEventListener('mouseleave', leave);
      });
      nodeElements.clear();
      adjacency.clear();
      target.innerHTML = '';
    },
  };
}
