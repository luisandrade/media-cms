import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';

export function ManageCategoryItem(props) {
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
        <strong>{props.title}</strong>
      </div>
      <div className="mi-link">
      <strong>{props.uid}</strong>
      </div>
    </div>
  );
}

ManageCategoryItem.propTypes = {
  id: PropTypes.number.isRequired,
  title: PropTypes.string.isRequired,
  uid: PropTypes.string.isRequired,
  selectedRow: PropTypes.bool.isRequired,
  onCheckRow: PropTypes.func.isRequired,
  onProceedRemoval: PropTypes.func.isRequired,
  onProceedAssignAd: PropTypes.func.isRequired
};
