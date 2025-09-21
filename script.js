// Global variables
let map;
let markers = [];
let userLocation = null;
let currentData = [];

// Sample data structure - replace with your scraped data
const sampleData = [
    {
        id: 1,
        name: "Autism Society of America - Local Chapter",
        type: "advocacy",
        address: "123 Main St, Anytown, ST 12345",
        phone: "(555) 123-4567",
        lat: 40.7128,
        lng: -74.0060,
        services: ["Advocacy", "Support Groups", "Resources"],
        description: "Local chapter providing advocacy and support for individuals with autism and their families."
    },
    {
        id: 2,
        name: "Special Needs Therapy Center",
        type: "therapy",
        address: "456 Oak Ave, Anytown, ST 12345",
        phone: "(555) 987-6543",
        lat: 40.7589,
        lng: -73.9851,
        services: ["ABA Therapy", "Speech Therapy", "Occupational Therapy"],
        description: "Comprehensive therapy services for children and adults with special needs."
    },
    {
        id: 3,
        name: "Inclusive Learning Academy",
        type: "education",
        address: "789 Pine Rd, Anytown, ST 12345",
        phone: "(555) 456-7890",
        lat: 40.6782,
        lng: -73.9442,
        services: ["Special Education", "IEP Support", "Tutoring"],
        description: "Educational support and specialized programs for students with special needs."
    }
];

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    initializeMap();
    bindEventListeners();
    loadSampleData();
});

// Initialize Leaflet map
function initializeMap() {
    map = L.map('map').setView([40.7128, -74.0060], 10);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    // Add map click handler
    map.on('click', function(e) {
        // Handle map clicks if needed
    });
}

// Bind event listeners
function bindEventListeners() {
    // Search button
    document.getElementById('search-btn').addEventListener('click', handleSearch);

    // Enter key on search input
    document.getElementById('location-search').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            handleSearch();
        }
    });

    // Service type filter
    document.getElementById('service-type').addEventListener('change', handleFilter);

    // Sort dropdown
    document.getElementById('sort-by').addEventListener('change', handleSort);

    // Locate user button
    document.getElementById('locate-btn').addEventListener('click', locateUser);

    // Reset view button
    document.getElementById('reset-btn').addEventListener('click', resetView);
}

// Load sample data
function loadSampleData() {
    currentData = [...sampleData];
    displayResults(currentData);
    addMarkersToMap(currentData);
    updateResultsCount(currentData.length);
}

// Handle search functionality
function handleSearch() {
    const searchTerm = document.getElementById('location-search').value.trim();

    if (!searchTerm) {
        alert('Please enter a location to search');
        return;
    }

    // Show loading state
    showLoading();

    // Simulate geocoding (replace with actual geocoding service)
    geocodeLocation(searchTerm)
        .then(coords => {
            if (coords) {
                userLocation = coords;
                map.setView([coords.lat, coords.lng], 12);

                // Add user location marker
                if (window.userMarker) {
                    map.removeLayer(window.userMarker);
                }

                window.userMarker = L.marker([coords.lat, coords.lng], {
                    icon: L.icon({
                        iconUrl: 'data:image/svg+xml;base64,' + btoa(`
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ff4444" width="24" height="24">
                                <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
                            </svg>
                        `),
                        iconSize: [24, 24],
                        iconAnchor: [12, 24]
                    })
                }).addTo(map);

                // Calculate distances and update results
                const dataWithDistances = calculateDistances(currentData, coords);
                displayResults(dataWithDistances);
                addMarkersToMap(dataWithDistances);
            }
        })
        .catch(error => {
            console.error('Geocoding error:', error);
            alert('Could not find the specified location. Please try again.');
        })
        .finally(() => {
            hideLoading();
        });
}

// Simulate geocoding (replace with actual service like Nominatim)
function geocodeLocation(location) {
    return new Promise((resolve) => {
        // Simulate API delay
        setTimeout(() => {
            // For demo purposes, return NYC coordinates
            // In real implementation, use a geocoding service
            resolve({
                lat: 40.7128 + (Math.random() - 0.5) * 0.1,
                lng: -74.0060 + (Math.random() - 0.5) * 0.1
            });
        }, 1000);
    });
}

// Calculate distances from user location
function calculateDistances(data, userCoords) {
    return data.map(item => {
        const distance = calculateDistance(
            userCoords.lat, userCoords.lng,
            item.lat, item.lng
        );
        return { ...item, distance };
    }).sort((a, b) => a.distance - b.distance);
}

// Calculate distance between two points using Haversine formula
function calculateDistance(lat1, lon1, lat2, lon2) {
    const R = 3959; // Earth's radius in miles
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon/2) * Math.sin(dLon/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
}

// Handle filtering
function handleFilter() {
    const serviceType = document.getElementById('service-type').value;
    let filteredData = [...currentData];

    if (serviceType) {
        filteredData = filteredData.filter(item => item.type === serviceType);
    }

    displayResults(filteredData);
    addMarkersToMap(filteredData);
    updateResultsCount(filteredData.length);
}

// Handle sorting
function handleSort() {
    const sortBy = document.getElementById('sort-by').value;
    let sortedData = [...currentData];

    switch (sortBy) {
        case 'distance':
            if (userLocation) {
                sortedData = calculateDistances(sortedData, userLocation);
            }
            break;
        case 'name':
            sortedData.sort((a, b) => a.name.localeCompare(b.name));
            break;
        case 'rating':
            // Implement rating sort if you have rating data
            break;
    }

    displayResults(sortedData);
}

// Display results in the sidebar
function displayResults(data) {
    const resultsList = document.getElementById('results-list');

    if (data.length === 0) {
        resultsList.innerHTML = '<div class="no-results"><p>No resources found for your search criteria.</p></div>';
        return;
    }

    const resultsHTML = data.map(item => `
        <div class="resource-item" onclick="focusOnMarker(${item.id})">
            <div class="resource-name">${item.name}</div>
            <div class="resource-type">${getServiceTypeLabel(item.type)}</div>
            <div class="resource-address">${item.address}</div>
            <a href="tel:${item.phone}" class="resource-phone" onclick="event.stopPropagation()">${item.phone}</a>
            ${item.distance ? `<div class="resource-distance">${item.distance.toFixed(1)} miles away</div>` : ''}
        </div>
    `).join('');

    resultsList.innerHTML = resultsHTML;
}

// Add markers to map
function addMarkersToMap(data) {
    // Clear existing markers
    markers.forEach(marker => map.removeLayer(marker));
    markers = [];

    // Add new markers
    data.forEach(item => {
        const marker = L.marker([item.lat, item.lng])
            .addTo(map)
            .bindPopup(`
                <div style="min-width: 200px;">
                    <h3 style="margin: 0 0 10px 0; color: #4A90E2;">${item.name}</h3>
                    <p style="margin: 0 0 5px 0; font-size: 12px; background: #FFB347; color: white; padding: 2px 8px; border-radius: 10px; display: inline-block;">
                        ${getServiceTypeLabel(item.type)}
                    </p>
                    <p style="margin: 5px 0;">${item.address}</p>
                    <p style="margin: 5px 0;">
                        <a href="tel:${item.phone}" style="color: #4A90E2; text-decoration: none;">📞 ${item.phone}</a>
                    </p>
                    ${item.description ? `<p style="margin: 10px 0 0 0; font-size: 14px; color: #666;">${item.description}</p>` : ''}
                </div>
            `);

        marker.resourceId = item.id;
        markers.push(marker);
    });

    // Fit map to show all markers
    if (markers.length > 0) {
        const group = new L.featureGroup(markers);
        map.fitBounds(group.getBounds().pad(0.1));
    }
}

// Focus on specific marker
function focusOnMarker(resourceId) {
    const marker = markers.find(m => m.resourceId === resourceId);
    if (marker) {
        map.setView(marker.getLatLng(), 15);
        marker.openPopup();
    }
}

// Get service type label
function getServiceTypeLabel(type) {
    const labels = {
        'therapy': 'Therapy Services',
        'education': 'Educational Support',
        'medical': 'Medical Services',
        'social': 'Social Programs',
        'respite': 'Respite Care',
        'advocacy': 'Advocacy & Legal',
        'employment': 'Employment Support'
    };
    return labels[type] || type;
}

// Locate user using browser geolocation
function locateUser() {
    if (!navigator.geolocation) {
        alert('Geolocation is not supported by this browser.');
        return;
    }

    showLoading();

    navigator.geolocation.getCurrentPosition(
        (position) => {
            userLocation = {
                lat: position.coords.latitude,
                lng: position.coords.longitude
            };

            map.setView([userLocation.lat, userLocation.lng], 12);

            // Add user location marker
            if (window.userMarker) {
                map.removeLayer(window.userMarker);
            }

            window.userMarker = L.marker([userLocation.lat, userLocation.lng], {
                icon: L.icon({
                    iconUrl: 'data:image/svg+xml;base64,' + btoa(`
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ff4444" width="24" height="24">
                            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
                        </svg>
                    `),
                    iconSize: [24, 24],
                    iconAnchor: [12, 24]
                })
            }).addTo(map).bindPopup('Your Location').openPopup();

            // Calculate distances and update results
            const dataWithDistances = calculateDistances(currentData, userLocation);
            displayResults(dataWithDistances);

            hideLoading();
        },
        (error) => {
            console.error('Geolocation error:', error);
            alert('Could not get your location. Please check your browser settings.');
            hideLoading();
        }
    );
}

// Reset map view
function resetView() {
    map.setView([40.7128, -74.0060], 10);
    document.getElementById('location-search').value = '';
    document.getElementById('service-type').value = '';

    if (window.userMarker) {
        map.removeLayer(window.userMarker);
    }

    userLocation = null;
    loadSampleData();
}

// Update results count
function updateResultsCount(count) {
    document.getElementById('results-count').textContent = `${count} resource${count !== 1 ? 's' : ''}`;
}

// Show loading state
function showLoading() {
    const button = document.getElementById('search-btn');
    button.textContent = 'Searching...';
    button.disabled = true;
}

// Hide loading state
function hideLoading() {
    const button = document.getElementById('search-btn');
    button.textContent = 'Search Resources';
    button.disabled = false;
}

// Function to load data from CSV (for integration with web scraper)
function loadDataFromCSV(csvData) {
    // Parse CSV data and convert to the required format
    // This function would be called after web scraping
    const lines = csvData.split('\n');
    const headers = lines[0].split(',');

    const data = lines.slice(1).map((line, index) => {
        const values = line.split(',');
        return {
            id: index + 1,
            name: values[0] || 'Unknown Resource',
            type: 'therapy', // Default type, could be determined from scraped data
            address: values[0] || 'Address not available',
            phone: values[1] || 'Phone not available',
            lat: 40.7128 + (Math.random() - 0.5) * 0.2, // Random coordinates for demo
            lng: -74.0060 + (Math.random() - 0.5) * 0.2,
            services: ['General Support'],
            description: 'Resource found through web scraping'
        };
    }).filter(item => item.address !== 'Address not available');

    currentData = data;
    displayResults(currentData);
    addMarkersToMap(currentData);
    updateResultsCount(currentData.length);
}

// Export function for external use
window.loadScrapedData = loadDataFromCSV;