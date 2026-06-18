const fs = require('fs');
const data = JSON.parse(fs.readFileSync('community_resources.json', 'utf8'));
const today = new Date().toISOString().slice(0, 10);
const output = `// Community Resources Data\n// Generated from community_resources.json on: ${today}\n// Total resources: ${data.length}\n\nconst communityResourcesData = ${JSON.stringify(data, null, 2)};\n`;
fs.writeFileSync('community_data.js', output, 'utf8');
console.log(`Done. community_data.js updated with ${data.length} entries.`);
