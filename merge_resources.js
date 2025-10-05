const fs = require('fs');

// Read existing data
const dataFile = fs.readFileSync('community_data.js', 'utf8');
const jsonFile = fs.readFileSync('community_resources.json', 'utf8');
const jsonResources = JSON.parse(jsonFile);

// Extract existing resources
const match = dataFile.match(/const communityResourcesData = (\[[\s\S]*?\]);/);
const existingResources = eval(match[1]);

// Merge (avoid duplicates)
const allResources = [...existingResources];
let added = 0;
jsonResources.forEach(newRes => {
  const exists = existingResources.find(r => r.name === newRes.name);
  if (!exists) {
    allResources.push(newRes);
    added++;
  }
});

console.log(`Merged ${added} new resources. Total: ${allResources.length}`);

// Generate new file content
const header = `
// Community Resources Data
// Generated on: ${new Date().toISOString().slice(0,19).replace('T', ' ')}
// Total resources: ${allResources.length}

const communityResourcesData = ${JSON.stringify(allResources, null, 2)};
`;

const footer = dataFile.substring(dataFile.indexOf('// Load data into the website'));

fs.writeFileSync('community_data.js', header + '\n' + footer);
console.log('✅ community_data.js updated successfully!');
