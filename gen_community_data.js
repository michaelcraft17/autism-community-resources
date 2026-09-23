// Regenerates community_data.js from community_resources.json. Run from the repo root:
//   node gen_community_data.js
//
// IMPORTANT: index.html loads this file as a plain <script> tag and reads
// `window.communityData` off it (see useCommunityData() in index.html). It must declare
// `window.communityData = [...]`, NOT a bare `const`/`let` — a top-level const in a
// classic (non-module) script never becomes a window property, so the page would
// silently fall back to its tiny hardcoded sample dataset instead of throwing an error.
// (This file used to get that wrong; if you're diffing against an old copy, that's why.)
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('community_resources.json', 'utf8'));
const output = `window.communityData = ${JSON.stringify(data)};\n`;
fs.writeFileSync('community_data.js', output, 'utf8');
console.log(`Done. community_data.js updated with ${data.length} entries.`);
