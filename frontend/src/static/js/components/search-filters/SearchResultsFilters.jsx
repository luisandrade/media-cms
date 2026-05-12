import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { PageStore } from '../../utils/stores/';
import { translateString } from '../../utils/helpers';
import { FilterOptions } from '../_shared';
import '../management-table/ManageItemList-filters.scss';

const filters = {
  media_type: [
    { id: 'all', title: translateString('All') },
    { id: 'video', title: translateString('Video') },
    { id: 'audio', title: translateString('Audio') },
    { id: 'image', title: translateString('Image') },
    { id: 'pdf', title: translateString('Pdf') },
  ],
  upload_date: [
    { id: 'all', title: translateString('All') },
    { id: 'today', title: translateString('Today') },
    { id: 'this_week', title: translateString('This week') },
    { id: 'this_month', title: translateString('This month') },
    { id: 'this_year', title: translateString('This year') },
  ],
  sort_by: [
    { id: 'date_added_desc', title: translateString('Upload date (newest)') },
    { id: 'date_added_asc', title: translateString('Upload date (oldest)') },
    { id: 'most_views', title: translateString('View count') },
    { id: 'most_likes', title: translateString('Like count') },
  ],
};

export function SearchResultsFilters(props) {
  const [isHidden, setIsHidden] = useState(props.hidden);

  const [mediaTypeFilter, setFilter_media_type] = useState('all');
  const [uploadDateFilter, setFilter_upload_date] = useState('all');
  const [sortByFilter, setFilter_sort_by] = useState('date_added_desc');

  const containerRef = useRef(null);
  const innerContainerRef = useRef(null);

  function onWindowResize() {
    if (!isHidden) {
      containerRef.current.style.height = 24 + innerContainerRef.current.offsetHeight + 'px';
    }
  }

  function onFilterSelect(ev) {
    const args = {
      media_type: mediaTypeFilter,
      upload_date: uploadDateFilter,
      sort_by: sortByFilter,
    };

    switch (ev.currentTarget.getAttribute('filter')) {
      case 'media_type':
        args.media_type = ev.currentTarget.getAttribute('value');
        props.onFiltersUpdate(args);
        setFilter_media_type(args.media_type);
        break;
      case 'upload_date':
        args.upload_date = ev.currentTarget.getAttribute('value');
        props.onFiltersUpdate(args);
        setFilter_upload_date(args.upload_date);
        break;
      case 'sort_by':
        args.sort_by = ev.currentTarget.getAttribute('value');
        props.onFiltersUpdate(args);
        setFilter_sort_by(args.sort_by);
        break;
    }
  }

  useEffect(() => {
    setIsHidden(props.hidden);
    onWindowResize();
  }, [props.hidden]);

  useEffect(() => {
    PageStore.on('window_resize', onWindowResize);
    return () => PageStore.removeListener('window_resize', onWindowResize);
  }, []);

  return (
    <div ref={containerRef} className={'mi-filters-row' + (isHidden ? ' hidden' : '')}>
      <div ref={innerContainerRef} className="mi-filters-row-inner">
        <div className="mi-filter">
          <div className="mi-filter-title">{translateString('MEDIA TYPE')}</div>
          <div className="mi-filter-options">
            <FilterOptions
              id={'media_type'}
              options={filters.media_type}
              selected={mediaTypeFilter}
              onSelect={onFilterSelect}
            />
          </div>
        </div>

        <div className="mi-filter">
          <div className="mi-filter-title">{translateString('UPLOAD DATE')}</div>
          <div className="mi-filter-options">
            <FilterOptions
              id={'upload_date'}
              options={filters.upload_date}
              selected={uploadDateFilter}
              onSelect={onFilterSelect}
            />
          </div>
        </div>

        <div className="mi-filter">
          <div className="mi-filter-title">{translateString('SORT BY')}</div>
          <div className="mi-filter-options">
            <FilterOptions id={'sort_by'} options={filters.sort_by} selected={sortByFilter} onSelect={onFilterSelect} />
          </div>
        </div>
      </div>
    </div>
  );
}

SearchResultsFilters.propTypes = {
  hidden: PropTypes.bool,
};

SearchResultsFilters.defaultProps = {
  hidden: false,
};
