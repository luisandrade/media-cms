import React from 'react';
import PropTypes from 'prop-types';
import { ApiUrlContext } from '../utils/contexts/';
import { csrfToken } from '../utils/helpers/';
import { PageActions } from '../utils/actions/';
import { MediaListWrapper } from '../components/MediaListWrapper';
import { ManageItemList } from '../components/management-table/ManageItemList/ManageItemList';
import { AdSelector } from '../components/ads-helper/AdsSelector';
import { Page } from './_Page';

function genReqUrl(url, sort, page) {
  const ret = url + '?' + sort + ('' === sort ? '' : '&') + 'page=' + page;
  return ret;
}

function assignAdToCategories(selectedCategoryIds, selectedAdId) {
  fetch('/api/assign-ad-to-media-by-category/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken(), // si usas CSRF
    },
    body: JSON.stringify({
      category_ids: selectedCategoryIds,
      ad_id: selectedAdId,
    }),
  })
    .then((res) => res.json())
    .then((data) => {
      alert(data.message || "Ad asignado con éxito");
    })
    .catch((error) => {
      console.error("Error al asignar Ad:", error);
    });
}

export class ManageCategoryAdsPage extends Page {
  constructor(props) {
    super(props, 'category-ads');

    this.state = {
      resultsCount: null,
      requestUrl: ApiUrlContext._currentValue.archive.category_ads,
      currentPage: 1,
      sortingArgs: '',
      sortBy: 'title',
      ordering: 'desc',
      refresh: 0,
      selectedCategoryIds: [],
    };

    this.getCountFunc = this.getCountFunc.bind(this);
    this.onTablePageChange = this.onTablePageChange.bind(this);
    this.onColumnSortClick = this.onColumnSortClick.bind(this);
    this.onItemsRemoval = this.onItemsRemoval.bind(this);
    this.onItemsRemovalFail = this.onItemsRemovalFail.bind(this);
    this.handleAdSelect = this.handleAdSelect.bind(this);
  }

  handleAdSelect(adId) {
    console.log("🎯 Ad seleccionado:", adId);
    this.setState({ selectedAdId: adId });
  }

  handleCategorySelect = (selectedCategoryIds) => {
    console.log("🟢 Categorías seleccionadas:", selectedCategoryIds);
    this.setState({ selectedCategoryIds });
  };

  onTablePageChange(newPageUrl, updatedPage) {
    this.setState({
      currentPage: updatedPage,
      requestUrl: genReqUrl(ApiUrlContext._currentValue.archive.category_ads, this.state.sortingArgs, updatedPage),
    });
  }

  getCountFunc(resultsCount) {
    this.setState({
      resultsCount: resultsCount,
    });
  }

  onColumnSortClick(sort, order) {
    const newArgs = 'sort_by=' + sort + '&ordering=' + order;
    this.setState({
      sortBy: sort,
      ordering: order,
      sortingArgs: newArgs,
      requestUrl: genReqUrl(ApiUrlContext._currentValue.archive.category_ads, newArgs, this.state.currentPage),
    });
  }

  onItemsRemoval(multipleItems) {
    this.setState(
      {
        resultsCount: null,
        refresh: this.state.refresh + 1,
        requestUrl: ApiUrlContext._currentValue.archive.category_ads,
      },
      function () {
        if (multipleItems) {
          PageActions.addNotification('The ads deleted successfully.', 'commentsRemovalSucceed');
        } else {
          PageActions.addNotification('The ads deleted successfully.', 'commentRemovalSucceed');
        }
      }
    );
  }

  onItemsRemovalFail(multipleItems) {
    if (multipleItems) {
      PageActions.addNotification('The ads removal failed. Please try again.', 'commentsRemovalFailed');
    } else {
      PageActions.addNotification('The ads removal failed. Please try again.', 'commentRemovalFailed');
    }
  }

  pageContent() {
    return (
      <MediaListWrapper
        className="search-results-wrap items-list-hor"
      >
        <ManageItemList
          pageItems={50}
          manageType={'category-ads'}
          key={this.state.requestUrl + '[' + this.state.refresh + ']'}
          itemsCountCallback={this.getCountFunc}
          requestUrl={this.state.requestUrl}
          onPageChange={this.onTablePageChange}
          sortBy={this.state.sortBy}
          ordering={this.state.ordering}
          onRowsDelete={this.onItemsRemoval}
          onRowsDeleteFail={this.onItemsRemovalFail}
          onClickColumnSort={this.onColumnSortClick}
          onSelectionChange={this.handleCategorySelect}
        />
        <AdSelector onSelect={this.handleAdSelect} />
        <button
          class="ads-button"
          disabled={this.state.selectedCategoryIds.length === 0 || !this.state.selectedAdId}
          onClick={() =>
            assignAdToCategories(this.state.selectedCategoryIds, this.state.selectedAdId)
          }
        >
          Asignar
        </button>
      </MediaListWrapper>
    );
  }
}

ManageCategoryAdsPage.propTypes = {
  title: PropTypes.string.isRequired,
};

ManageCategoryAdsPage.defaultProps = {
  title: 'Manage Category ads',
};
