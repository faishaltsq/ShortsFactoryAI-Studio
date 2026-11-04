import assert from 'node:assert/strict';
import {
  DEFAULT_TOKENS,
  ENERGY_TOKENS,
  SCIENCE_TOKENS,
  INFRASTRUCTURE_TOKENS,
  TOPIC_TOKENS,
} from '../tokens.ts';
import {
  FONT_FAMILIES,
  FONT_ROLES,
  TYPE_SCALE,
  SAFE_AREA,
} from '../type.ts';

/**
 * WCAG 2.1 Relative Luminance calculation for sRGB hex color.
 */
function parseHex(hex) {
  const clean = hex.replace('#', '').trim();
  const full = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean;
  const num = Number.parseInt(full, 16);
  if (!Number.isFinite(num)) throw new Error(`Invalid hex: ${hex}`);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

function relativeLuminance(hex) {
  const [r8, g8, b8] = parseHex(hex);
  const toLinear = (c8) => {
    const c = c8 / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const r = toLinear(r8);
  const g = toLinear(g8);
  const b = toLinear(b8);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(hex1, hex2) {
  const l1 = relativeLuminance(hex1);
  const l2 = relativeLuminance(hex2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

console.log('=== RUNNING THEME TOKEN INVARIANT CHECKS ===\n');

// 1. Required keys presence on ThemeTokens
const REQUIRED_TOKEN_KEYS = [
  'id',
  'name',
  'background',
  'surface',
  'elevatedSurface',
  'textPrimary',
  'textSecondary',
  'textMuted',
  'accent',
  'accentDeep',
  'accentSoft',
  'line',
  'highlight',
  'chartColors',
  'status',
  'shadow',
];

const REQUIRED_STATUS_KEYS = ['success', 'warning', 'error'];
const REQUIRED_SHADOW_KEYS = ['sm', 'md', 'lg', 'float'];

const tokenSets = [
  {name: 'DEFAULT_TOKENS', tokens: DEFAULT_TOKENS},
  {name: 'ENERGY_TOKENS', tokens: ENERGY_TOKENS},
  {name: 'SCIENCE_TOKENS', tokens: SCIENCE_TOKENS},
  {name: 'INFRASTRUCTURE_TOKENS', tokens: INFRASTRUCTURE_TOKENS},
];

for (const {name, tokens} of tokenSets) {
  for (const key of REQUIRED_TOKEN_KEYS) {
    assert.ok(key in tokens, `Missing key "${key}" in ${name}`);
    assert.ok(tokens[key] !== undefined && tokens[key] !== null, `Nil value for "${key}" in ${name}`);
  }

  for (const sKey of REQUIRED_STATUS_KEYS) {
    assert.ok(sKey in tokens.status, `Missing status key "${sKey}" in ${name}`);
  }

  for (const shKey of REQUIRED_SHADOW_KEYS) {
    assert.ok(shKey in tokens.shadow, `Missing shadow key "${shKey}" in ${name}`);
  }

  // Chart colors length 5-6
  assert.ok(
    tokens.chartColors.length >= 5 && tokens.chartColors.length <= 6,
    `chartColors length must be between 5 and 6 in ${name}, got ${tokens.chartColors.length}`
  );

  console.log(`PASS: Structure & keys invariant verified for ${name}`);
}

// 2. Cohesive Brand Shell invariant (background & text identity across topics)
for (const topic of ['energy', 'science', 'infrastructure']) {
  const topicTokens = TOPIC_TOKENS[topic];
  assert.equal(
    topicTokens.background,
    DEFAULT_TOKENS.background,
    `Topic ${topic} background must match brand shell background`
  );
  assert.equal(
    topicTokens.textPrimary,
    DEFAULT_TOKENS.textPrimary,
    `Topic ${topic} textPrimary must match brand shell textPrimary`
  );
  assert.equal(
    topicTokens.surface,
    DEFAULT_TOKENS.surface,
    `Topic ${topic} surface must match brand shell surface`
  );
}
console.log('PASS: Brand shell uniformity across topic accents');

// 3. Contrast Ratios on Background
const bg = DEFAULT_TOKENS.background;
const ratioPrimary = contrastRatio(DEFAULT_TOKENS.textPrimary, bg);
const ratioSecondary = contrastRatio(DEFAULT_TOKENS.textSecondary, bg);
const ratioMuted = contrastRatio(DEFAULT_TOKENS.textMuted, bg);

console.log(`\nContrast on background (${bg}):`);
console.log(`- textPrimary (${DEFAULT_TOKENS.textPrimary}): ${ratioPrimary.toFixed(2)}:1 (threshold >= 4.5:1)`);
console.log(`- textSecondary (${DEFAULT_TOKENS.textSecondary}): ${ratioSecondary.toFixed(2)}:1 (threshold >= 3.0:1)`);
console.log(`- textMuted (${DEFAULT_TOKENS.textMuted}): ${ratioMuted.toFixed(2)}:1 (threshold >= 3.0:1)`);

assert.ok(
  ratioPrimary >= 4.5,
  `textPrimary contrast ${ratioPrimary.toFixed(2)} must be >= 4.5:1`
);
assert.ok(
  ratioSecondary >= 3.0,
  `textSecondary contrast ${ratioSecondary.toFixed(2)} must be >= 3.0:1`
);
assert.ok(
  ratioMuted >= 3.0,
  `textMuted contrast ${ratioMuted.toFixed(2)} must be >= 3.0:1`
);
console.log('PASS: All text contrast ratio thresholds met (WCAG AA)');

// 4. Typographic Scale Invariants
const REQUIRED_SCALE_LEVELS = [
  'displayXl',
  'displayLg',
  'heading',
  'subheading',
  'body',
  'bodySmall',
  'caption',
  'techLabel',
  'micro',
];

for (const level of REQUIRED_SCALE_LEVELS) {
  assert.ok(level in TYPE_SCALE, `Missing level "${level}" in TYPE_SCALE`);
  const style = TYPE_SCALE[level];
  assert.ok(typeof style.fontSize === 'number' && style.fontSize > 0, `Invalid fontSize in ${level}`);
  assert.ok(typeof style.fontWeight === 'number' && style.fontWeight >= 400, `Invalid fontWeight in ${level}`);
  assert.ok(typeof style.fontFamily === 'string' && style.fontFamily.length > 0, `Invalid fontFamily in ${level}`);
  assert.ok(typeof style.lineHeight === 'number' && style.lineHeight > 0, `Invalid lineHeight in ${level}`);
}

// Check caption readability minimum threshold (min 34-40px on 1080 stage)
assert.ok(
  TYPE_SCALE.caption.fontSize >= 34 && TYPE_SCALE.caption.fontSize <= 48,
  `Caption fontSize (${TYPE_SCALE.caption.fontSize}) should be between 34 and 48px for mobile reading distance`
);

// Check ADR-0012 title band (88-168px)
assert.ok(
  TYPE_SCALE.displayLg.fontSize >= 88 && TYPE_SCALE.displayXl.fontSize <= 168,
  `Display sizes (${TYPE_SCALE.displayLg.fontSize} - ${TYPE_SCALE.displayXl.fontSize}px) must conform to ADR-0012 88-168px range`
);
console.log('PASS: Typographic scale levels and readability constraints verified');

// 5. Font Families and Roles
assert.equal(FONT_FAMILIES.display, 'Fraunces');
assert.equal(FONT_FAMILIES.body, 'Manrope');
assert.equal(FONT_FAMILIES.technical, 'IBM Plex Mono');

assert.ok(FONT_ROLES.display.includes('Fraunces'));
assert.ok(FONT_ROLES.body.includes('Manrope'));
assert.ok(FONT_ROLES.technical.includes('IBM Plex Mono'));
console.log('PASS: Font role family mappings verified');

// 6. Safe Area Constraints (1080x1920)
assert.equal(SAFE_AREA.stageWidth, 1080);
assert.equal(SAFE_AREA.stageHeight, 1920);
assert.ok(SAFE_AREA.top >= 160, 'SAFE_AREA.top must clear Shorts top chrome');
assert.ok(SAFE_AREA.bottom >= 380, 'SAFE_AREA.bottom must clear Shorts bottom UI');
assert.equal(SAFE_AREA.scaleFactor, 0.78, 'SAFE_AREA.scaleFactor must match ADR-0012 .safe (0.78)');
console.log('PASS: Mobile 9:16 safe area parameters verified');

console.log('\nALL TOKEN AND TYPOGRAPHY INVARIANTS PASSED.');
