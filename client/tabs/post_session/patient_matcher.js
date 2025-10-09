const DIACRITICS_REGEX = /[\u0300-\u036f]/g;

function normalizeBase(value) {
  if (typeof value !== 'string') return '';
  return value
    .normalize('NFD')
    .replace(DIACRITICS_REGEX, '')
    .toLowerCase()
    .replace(/\.[^/.]+$/, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function buildVariants(value) {
  const base = normalizeBase(value);
  if (!base) return [];
  const collapsed = base.replace(/\s+/g, '');
  return collapsed && collapsed !== base ? [base, collapsed] : [base];
}

function containsVariant(source, variant) {
  if (!variant) return false;
  const padded = ` ${source} `;
  const paddedVariant = ` ${variant} `;
  if (padded.includes(paddedVariant)) return true;
  const collapsedSource = source.replace(/\s+/g, '');
  const collapsedVariant = variant.replace(/\s+/g, '');
  if (!collapsedSource || !collapsedVariant) return false;
  return collapsedSource.includes(collapsedVariant);
}

export function resolvePatientIdFromFileName(fileName, patients = []) {
  if (typeof fileName !== 'string' || !fileName.trim()) {
    return null;
  }
  const source = normalizeBase(fileName);
  if (!source) return null;
  let bestMatch = null;
  let bestScore = -1;
  patients.forEach((patient) => {
    if (!patient || typeof patient !== 'object') return;
    const { id } = patient;
    if (typeof id !== 'string' || !id) return;
    const variants = new Set(buildVariants(patient.displayName || patient.name || ''));
    buildVariants(id).forEach((variant) => variants.add(variant));
    let localScore = -1;
    variants.forEach((variant) => {
      if (!variant) return;
      if (containsVariant(source, variant)) {
        const score = variant.replace(/\s+/g, '').length;
        if (score > localScore) {
          localScore = score;
        }
      }
    });
    if (localScore > bestScore) {
      bestScore = localScore;
      bestMatch = id;
    }
  });
  return bestScore > -1 ? bestMatch : null;
}

export function __test__normalizeBase(value) {
  return normalizeBase(value);
}
