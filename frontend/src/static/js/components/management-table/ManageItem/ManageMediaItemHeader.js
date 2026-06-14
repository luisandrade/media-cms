import React from 'react';
import PropTypes from 'prop-types';
import { useManagementTableHeader } from '../../../utils/hooks/';
import { translateString } from '../../../utils/helpers/';
import { MaterialIcon } from '../../_shared/material-icon/MaterialIcon.jsx';

export function ManageMediaItemHeader(props) {
  const [sort, order, isSelected, sortByColumn, checkAll] = useManagementTableHeader({ ...props, type: 'media' });

  return (
    <div className="item manage-item manage-item-header manage-media-item">
      <div className="mi-checkbox">
        <input type="checkbox" checked={isSelected} onChange={checkAll} />
      </div>
      <div
        id="title"
        onClick={sortByColumn}
        className={'mi-title mi-col-sort' + ('title' === sort ? ('asc' === order ? ' asc' : ' desc') : '')}
      >
        {translateString('Title')}
        <div className="mi-col-sort-icons">
          <span>
            <MaterialIcon type="arrow_drop_up" />
          </span>
          <span>
            <MaterialIcon type="arrow_drop_down" />
          </span>
        </div>
      </div>
      <div
        id="add_date"
        onClick={sortByColumn}
        className={'mi-added mi-col-sort' + ('add_date' === sort ? ('asc' === order ? ' asc' : ' desc') : '')}
      >
        {translateString('Date added')}
        <div className="mi-col-sort-icons">
          <span>
            <MaterialIcon type="arrow_drop_up" />
          </span>
          <span>
            <MaterialIcon type="arrow_drop_down" />
          </span>
        </div>
      </div>
      <div className="mi-author">{translateString('Author')}</div>
      <div className="mi-type">{translateString('Media type')}</div>
      <div className="mi-encoding">{translateString('Encoding status')}</div>
      <div className="mi-state">{translateString('State')}</div>
      <div className="mi-reviewed">{translateString('Reviewed')}</div>
      <div className="mi-featured">{translateString('Featured')}</div>
      <div className="mi-reported">{translateString('Reported')}</div>
    </div>
  );
}

ManageMediaItemHeader.propTypes = {
  sort: PropTypes.string.isRequired,
  order: PropTypes.string.isRequired,
  selected: PropTypes.bool.isRequired,
  onClickColumnSort: PropTypes.func,
  onCheckAllRows: PropTypes.func,
};
