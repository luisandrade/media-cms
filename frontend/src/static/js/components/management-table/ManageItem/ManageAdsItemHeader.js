import React from 'react';
import PropTypes from 'prop-types';
import { useManagementTableHeader } from '../../../utils/hooks/';
import { MaterialIcon } from '../../_shared/material-icon/MaterialIcon';

export function ManageAdsItemHeader(props) {
  const [sort, order, isSelected, sortByColumn, checkAll] = useManagementTableHeader({ ...props, type: 'ads' });

  return (
    <div className="item manage-item manage-item-header manage-ads-item">
      <div className="mi-checkbox">
        <input type="checkbox" checked={isSelected} onChange={checkAll} />
      </div>

      <div
        id="name"
        onClick={sortByColumn}
        className={'mi-title mi-col-sort' + (sort === 'name' ? (order === 'asc' ? ' asc' : ' desc') : '')}
      >
        Nombre
        <div className="mi-col-sort-icons">
          <span><MaterialIcon type="arrow_drop_up" /></span>
          <span><MaterialIcon type="arrow_drop_down" /></span>
        </div>
      </div>

      <div
        id="url"
        onClick={sortByColumn}
        className={'mi-link mi-col-sort' + (sort === 'url' ? (order === 'asc' ? ' asc' : ' desc') : '')}
      >
        URL
        <div className="mi-col-sort-icons">
          <span><MaterialIcon type="arrow_drop_up" /></span>
          <span><MaterialIcon type="arrow_drop_down" /></span>
        </div>
      </div>
    </div>
  );
}

ManageAdsItemHeader.propTypes = {
  sort: PropTypes.string.isRequired,
  order: PropTypes.string.isRequired,
  selected: PropTypes.bool.isRequired,
  onClickColumnSort: PropTypes.func,
  onCheckAllRows: PropTypes.func,
};
