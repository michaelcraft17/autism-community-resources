# Autism & Special Needs Community Resources

A comprehensive directory and interactive map of community resources for autism and special needs support services.

## 🌐 Live Website
Visit the directory: (https://michaelcraft17.github.io/autism-community-resources/)

## 📋 Features

### Resource Directory
- **Search & Filter**: Find resources by name, location, or service type with debounced search
- **Contact Information**: Direct phone numbers and website links
- **Service Categories**: Advocacy, Therapy, Education, Medical, Social Support
- **Mobile Responsive**: Works on all devices
- **Favorites**: Save and bookmark your preferred resources locally
- **Export Data**: Download search results as CSV for offline use
- **Print-Friendly**: Print resource listings with optimized layout

### Interactive Map
- **Visual Mapping**: See resources plotted on an interactive map
- **Location Search**: Find resources near specific addresses
- **Click-to-Call**: Direct access to contact information
- **Geolocation**: Find resources near your current location
- **Distance Calculation**: See how far each resource is from your location

### Accessibility & User Experience
- **Dark Mode**: Toggle between light and dark themes (preference saved)
- **Keyboard Navigation**: Full keyboard accessibility with visible focus indicators
- **Screen Reader Support**: ARIA labels and semantic HTML for assistive technologies
- **Skip Links**: Quick navigation to main content
- **Loading States**: Visual feedback during data fetching
- **Error Handling**: Clear, helpful error messages

## 🎯 Resource Types

- **🗣️ Advocacy**: Organizations providing support and advocacy services
- **🩺 Therapy**: ABA, speech, occupational, and other therapeutic services
- **🎓 Education**: Special education support and IEP assistance
- **🏥 Medical**: Diagnostic and medical treatment services
- **👥 Social**: Support groups and community programs
- **💡 General Support**: Comprehensive community resources

## 📱 How to Use

### Finding Resources
1. **Set Your Location**:
   - Click "Use My Location" for GPS-based search
   - Or enter a zip code, address, or city manually

2. **Browse & Search**:
   - View resources sorted by distance from your location
   - Use the search bar to find specific services
   - Filter by resource type using the dropdown

3. **Save Favorites**:
   - Click the heart icon (🤍) on any resource to save it
   - Access saved resources with the "Favorites" button
   - Favorites persist across browser sessions

4. **Export & Share**:
   - Click "Export Results" to download a CSV file
   - Use "Print" for a printer-friendly view
   - Share resource information with family and friends

5. **Customize Experience**:
   - Toggle dark mode with the 🌙 button
   - Your preference is automatically saved
   - Works great in low-light environments

### Interactive Map
1. View all resources on an interactive map
2. Click markers for detailed popup information
3. Resources are color-coded by type
4. Map automatically fits to show all results

## 🛠️ Technical Details

### Built With
- **HTML5** - Semantic markup with ARIA accessibility attributes
- **CSS3** - Responsive design, dark mode, print styles
- **JavaScript** - Interactive functionality with performance optimizations
- **Leaflet.js** - Interactive mapping capabilities
- **OpenStreetMap** - Geocoding and map tiles
- **Python** - Web scraping and data collection

### Performance Optimizations
- **Debounced Search**: 300ms debounce to reduce unnecessary filtering
- **Lazy Map Loading**: Map initializes only when needed
- **LocalStorage Caching**: Favorites and preferences stored locally
- **Efficient Rendering**: DOM updates only when necessary

### Accessibility Features (WCAG 2.1 Compliant)
- Semantic HTML5 structure with proper heading hierarchy
- ARIA labels and roles throughout
- Keyboard navigation support
- Focus visible indicators for all interactive elements
- Screen reader announcements for dynamic content
- Skip navigation links
- High contrast mode support
- Reduced motion support

### Data Sources
Resources are collected through web scraping from:
- Autism Society of America
- Autism Speaks
- Local community organizations
- Healthcare providers
- Educational institutions

## 📊 Data Structure

Resources include:
```json
{
  "name": "Resource Name",
  "address": "Full Address",
  "phone": "(XXX) XXX-XXXX",
  "website": "https://example.com",
  "type": "therapy|advocacy|education|medical|social",
  "description": "Service description",
  "coordinates": {"lat": 40.7128, "lng": -74.0060}
}
```

## 🚀 Contributing

This project aims to help families find autism and special needs resources in their communities.

### Adding Resources
Know of a resource that should be included? Resources can be added by:
1. Updating the `community_resources.json` file
2. Running the web scraper on additional sites
3. Submitting an issue with resource details

### Improving the Code
- Fork the repository
- Make your improvements
- Submit a pull request

### Feature Roadmap
Future enhancements being considered:
- [ ] User reviews and ratings
- [ ] Multi-language support
- [ ] Advanced filtering (insurance accepted, age ranges)
- [ ] Resource availability calendar
- [ ] Mobile app version
- [ ] Share individual resources via social media
- [ ] Email resource lists

## 📞 Emergency Resources

- **Autism Society**: 1-800-328-8476
- **Crisis Text Line**: Text HOME to 741741
- **National Suicide Prevention**: 988

## ⚠️ Disclaimer

Always verify services and information directly with providers. This directory is for informational purposes and resources may change without notice.

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

---


**Made with ❤️ for the autism and special needs community**
