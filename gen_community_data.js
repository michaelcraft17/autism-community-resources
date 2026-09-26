// Regenerates community_data_us.js / community_data_europe.js / community_data_world.js from
// the three region-split JSON files. Run from the repo root, AFTER tools/split_by_region.py:
//   python3 tools/split_by_region.py && node gen_community_data.js
//
// IMPORTANT: index.html loads these three files as plain <script> tags (see
// useCommunityData() in index.html) and each one does
// `window.communityData = (window.communityData || []).concat([...])`, NOT a bare
// `const`/`with `=` assign — using concat means load order across the three files doesn't
// matter, and a top-level const in a classic (non-module) script never becomes a window
// property anyway, so getting this wrong makes the page silently fall back to its tiny
// hardcoded sample dataset instead of throwing an error.
const fs = require('fs');

const REGIONS = [
  { key: 'us', in: 'community_resources_us.json', out: 'community_data_us.js' },
  { key: 'europe', in: 'community_resources_europe.json', out: 'community_data_europe.js' },
  { key: 'world', in: 'community_resources_world.json', out: 'community_data_world.js' },
];

let total = 0;
for (const region of REGIONS) {
  const data = JSON.parse(fs.readFileSync(region.in, 'utf8'));
  const output = `window.communityData = (window.communityData || []).concat(${JSON.stringify(data)});\n`;
  fs.writeFileSync(region.out, output, 'utf8');
  console.log(`Done. ${region.out} updated with ${data.length} entries.`);
  total += data.length;
}
console.log(`Total across all three regions: ${total} entries.`);
