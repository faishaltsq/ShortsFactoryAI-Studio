import assert from 'node:assert/strict';

export function paginateWords(words, wordsPerPage = 4) {
  const pages = [];
  for (let i = 0; i < words.length; i += wordsPerPage) {
    const chunk = words.slice(i, i + wordsPerPage);
    if (chunk.length > 0) {
      pages.push({
        start: chunk[0].start,
        end: chunk[chunk.length - 1].end,
        words: chunk,
      });
    }
  }
  return pages;
}

const sampleWords = [
  { word: 'AI', start: 0.1, end: 0.4 },
  { word: 'bisa', start: 0.45, end: 0.7 },
  { word: 'memprediksi', start: 0.75, end: 1.2 },
  { word: 'masa', start: 1.25, end: 1.5 },
  { word: 'depan', start: 1.55, end: 1.9 },
];

const pages = paginateWords(sampleWords, 4);
assert.equal(pages.length, 2, 'should split into 2 pages');
assert.equal(pages[0].words.length, 4);
assert.equal(pages[1].words.length, 1);
assert.equal(pages[0].start, 0.1);
assert.equal(pages[0].end, 1.5);
assert.equal(pages[1].start, 1.55);
assert.equal(pages[1].end, 1.9);

// Active page lookup test
export function getActivePage(pagesList, currentTime) {
  for (let i = 0; i < pagesList.length; i++) {
    const page = pagesList[i];
    const nextPage = pagesList[i + 1];
    const thresholdEnd = nextPage ? nextPage.start : page.end + 0.2;
    if (currentTime >= page.start && currentTime < thresholdEnd) {
      return page;
    }
  }
  return undefined;
}

assert.equal(getActivePage(pages, 0.5), pages[0]);
assert.equal(getActivePage(pages, 1.6), pages[1]);
assert.equal(getActivePage(pages, 2.5), undefined);

console.log('PASS test-captions pagination and active page matching');
