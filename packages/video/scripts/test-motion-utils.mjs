import assert from 'node:assert/strict';

export function calculateKenBurnsScale(frame, totalFrames, maxScale = 1.07) {
  const progress = Math.min(1, Math.max(0, frame / Math.max(1, totalFrames)));
  return 1.0 + progress * (maxScale - 1.0);
}

assert.equal(calculateKenBurnsScale(0, 300), 1.0);
assert.equal(Number(calculateKenBurnsScale(150, 300).toFixed(4)), 1.035);
assert.equal(Number(calculateKenBurnsScale(300, 300).toFixed(2)), 1.07);
assert.equal(Number(calculateKenBurnsScale(500, 300).toFixed(2)), 1.07, 'should clamp to maxScale');
assert.equal(calculateKenBurnsScale(-50, 300), 1.0, 'should clamp to 1.0');

console.log('PASS test-motion-utils scale calculation');
