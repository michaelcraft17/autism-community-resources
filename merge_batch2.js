const fs = require('fs');
const path = require('path');
const existingPath = path.join(__dirname, 'community_resources.json');
const newPath = path.join(__dirname, 'new_autism_resources_batch2.json');
const existing = JSON.parse(fs.readFileSync(existingPath, 'utf8'));
const newEntries = JSON.parse(fs.readFileSync(newPath, 'utf8'));
const existingNames = new Set(existing.map(r => r.name.trim().toLowerCase()));
let added = 0;
for (const entry of newEntries) {
  const key = entry.name.trim().toLowerCase();
  if (!existingNames.has(key)) {
    existing.push(entry);
    existingNames.add(key);
    added++;
    console.log(`✅ Added: ${entry.name}`);
  } else {
    console.log(`⏭️  Skipped (already exists): ${entry.name}`);
  }
}
fs.writeFileSync(existingPath, JSON.stringify(existing, null, 2), 'utf8');
console.log(`\nDone. ${added} new resources added. Total: ${existing.length}`);
