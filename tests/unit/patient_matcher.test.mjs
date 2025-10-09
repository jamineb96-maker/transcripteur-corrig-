import assert from 'node:assert/strict';
import { resolvePatientIdFromFileName, __test__normalizeBase } from '../../client/tabs/post_session/patient_matcher.js';

const patients = [
  { id: 'p1', displayName: 'Patient X' },
  { id: 'p2', displayName: 'Jean Martin' },
  { id: 'p3', displayName: 'Jean' },
  { id: 'p4', displayName: 'Chloé' },
];

assert.equal(
  resolvePatientIdFromFileName('PatientX_audio.MP3', patients),
  'p1',
  'Should match patient name ignoring spaces and case'
);

assert.equal(
  resolvePatientIdFromFileName('jean-martin_compte-rendu.wav', patients),
  'p2',
  'Should match patient with compound name'
);

assert.equal(
  resolvePatientIdFromFileName('Compte-rendu Jean.mp3', patients),
  'p3',
  'Should match shorter name when compound not present'
);

assert.equal(
  resolvePatientIdFromFileName('Rapport_p3_final.ogg', patients),
  'p3',
  'Should match using patient id'
);

assert.equal(
  resolvePatientIdFromFileName('suivi-chloe-2024.flac', patients),
  'p4',
  'Should match name with accent insensitively'
);

assert.equal(
  resolvePatientIdFromFileName('Jean Martin bilan 2024.mp3', patients),
  'p2',
  'Should prioritise the longest matching variant'
);

assert.equal(
  resolvePatientIdFromFileName('autre-patient.mp3', patients),
  null,
  'Should return null when no patient matches'
);

assert.equal(
  __test__normalizeBase('Chloé-2024.mp3'),
  'chloe 2024',
  'Normalization should lowercase, strip accents and extension'
);

console.log('All patient matcher tests passed');
