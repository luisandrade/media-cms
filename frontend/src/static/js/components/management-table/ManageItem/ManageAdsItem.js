import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';

export function ManageAdsItem(props) {
  const [selected, setSelected] = useState(false);

  function onRowCheck() {
    setSelected(!selected);
    if (typeof props.onCheckRow === 'function') {
      props.onCheckRow(props.token, !selected);
    }
  }

  useEffect(() => {
    if (typeof props.onCheckRow === 'function') {
      props.onCheckRow(props.id, selected);
    }
  }, [selected]);

  return (
    <div className="item manage-item manage-ads-item">
      <div className="mi-checkbox">
        <input type="checkbox" checked={selected} onChange={onRowCheck} />
      </div>
      <div className="mi-title">
        <strong>{props.name}</strong>
      </div>
      <div className="mi-link">
        <a href={props.url} target="_blank" rel="noopener noreferrer">Ver anuncio</a>
      </div>
    </div>
  );
}

ManageAdsItem.propTypes = {
  id: PropTypes.number.isRequired,
  name: PropTypes.string.isRequired,
  url: PropTypes.string.isRequired,
  selectedRow: PropTypes.bool.isRequired,
  onCheckRow: PropTypes.func.isRequired,
  onProceedRemoval: PropTypes.func.isRequired,
  onProceedAssignAd: PropTypes.func.isRequired
};
