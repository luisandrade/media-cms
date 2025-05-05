import React, { useEffect, useState } from 'react';

export function AdSelector({ onSelect }) {
  const [ads, setAds] = useState([]);
  const [selectedAd, setSelectedAd] = useState('');

  useEffect(() => {
    fetch('/api/v1/ads')
      .then((res) => res.json())
      .then((data) => {
        setAds(data.results || []);
      })
      .catch((error) => {
        console.error('Error al cargar los anuncios:', error);
      });
  }, []);

  const handleChange = (e) => {
    const adId = e.target.value;
    setSelectedAd(adId);
    if (onSelect) {
      onSelect(adId);
    }
  };

  return (
    <div>
      <label htmlFor="ads-select">Selecciona un anuncio:</label>
      <select id="ads-select" value={selectedAd} onChange={handleChange}>
        <option value="">-- Selecciona --</option>
        {ads.map((ad) => (
          <option key={ad.id} value={ad.id}>
            {ad.name}
          </option>
        ))}
      </select>
    </div>
  );
}
