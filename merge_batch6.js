const fs = require('fs');

const existing = JSON.parse(fs.readFileSync('community_resources.json', 'utf8'));
const newBatch = JSON.parse(fs.readFileSync('new_autism_resources_batch6.json', 'utf8'));

// Build dedup sets
const existingNames = new Set(existing.map(e => e.name.toLowerCase().trim()));
const existingWebsites = new Set(
  existing.filter(e => e.website).map(e => e.website.toLowerCase().trim().replace(/\/$/, ''))
);

let added = 0;
let skipped = 0;

for (const entry of newBatch) {
  const nameLower = entry.name.toLowerCase().trim();
  const websiteLower = entry.website ? entry.website.toLowerCase().trim().replace(/\/$/, '') : '';

  if (existingNames.has(nameLower)) {
    console.log(`SKIP (name dup): ${entry.name}`);
    skipped++;
    continue;
  }
  if (websiteLower && existingWebsites.has(websiteLower)) {
    console.log(`SKIP (website dup): ${entry.name} — ${entry.website}`);
    skipped++;
    continue;
  }

  existing.push(entry);
  existingNames.add(nameLower);
  if (websiteLower) existingWebsites.add(websiteLower);
  console.log(`ADD: ${entry.name}`);
  added++;
}

fs.writeFileSync('community_resources.json', JSON.stringify(existing, null, 2));
console.log(`\nDone: added=${added}, skipped=${skipped}, total=${existing.length}`);
