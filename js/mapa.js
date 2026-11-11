// PET Alert · Mapas con Leaflet + OpenStreetMap (decisión D3).
// Política de uso de los mapas de OSM: uso moderado y mostrar siempre la atribución.
(function () {
  'use strict';

  const DEFAULT_CENTER = [4.65, -74.08]; // Bogotá
  const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';

  function baseMap(el, center, zoom) {
    const map = L.map(el, { scrollWheelZoom: false }).setView(center, zoom);
    L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
    // Si el mapa se creó dentro de algo oculto, recalcula su tamaño al mostrarse.
    setTimeout(() => map.invalidateSize(), 50);
    return map;
  }

  // Selector: la persona hace clic (o arrastra el marcador) para marcar el lugar exacto.
  function picker(el, initial, onChange) {
    const start = initial ? [initial.lat, initial.lng] : DEFAULT_CENTER;
    const map = baseMap(el, start, initial ? 15 : 12);
    let marker = null;

    function set(lat, lng, fly) {
      const point = [Number(lat.toFixed(6)), Number(lng.toFixed(6))];
      if (!marker) {
        marker = L.marker(point, { draggable: true }).addTo(map);
        marker.on('dragend', () => {
          const p = marker.getLatLng();
          set(p.lat, p.lng, false);
        });
      } else {
        marker.setLatLng(point);
      }
      if (fly) map.setView(point, Math.max(map.getZoom(), 15));
      onChange({ lat: point[0], lng: point[1] });
    }

    map.on('click', (e) => set(e.latlng.lat, e.latlng.lng, false));
    if (initial) set(initial.lat, initial.lng, false);

    return {
      set,
      refresh: () => map.invalidateSize(),
      locate: () => new Promise((resolve, reject) => {
        if (!navigator.geolocation) { reject(new Error('Tu navegador no permite obtener la ubicación.')); return; }
        navigator.geolocation.getCurrentPosition(
          (pos) => { set(pos.coords.latitude, pos.coords.longitude, true); resolve(); },
          () => reject(new Error('No se pudo obtener tu ubicación. Marca el punto en el mapa.')),
          { enableHighAccuracy: true, timeout: 10000 },
        );
      }),
    };
  }

  // Vista: exacta (marcador, solo para el dueño) o aproximada (círculo de ~1 km).
  function viewer(el, lat, lng, approx) {
    const point = [Number(lat), Number(lng)];
    const map = baseMap(el, point, approx ? 13 : 15);
    if (approx) {
      L.circle(point, { radius: 1000, color: '#155E75', fillColor: '#2A9D8F', fillOpacity: 0.18, weight: 2 }).addTo(map);
    } else {
      L.marker(point).addTo(map);
    }
    return map;
  }

  window.PetMap = { picker, viewer };
})();
